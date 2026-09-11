import copy
import json
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional
from langgraph.types import interrupt
from app.engine.llm_client import (
    CustomerResponseDraft,
    EntityExtraction,
    IntentClassification,
    ResolutionDecision,
    llm_client,
)
from app.engine.rules_engine import BusinessRulesEngine
from app.tools.mcp_tools import MCPTools
from app.utils import utc_now
from app.workflow.state import TicketState

logger = logging.getLogger("support_agent.workflow.nodes")

def _log_step(state: TicketState, step_name: str, details: Dict[str, Any]):
    logs = list(state.get("audit_logs", []))
    logs.append({
        "step": step_name,
        "timestamp": utc_now().isoformat(),
        "details": details,
    })
    state["audit_logs"] = logs

# ==========================================
# 1. Classify Ticket Node
# ==========================================
async def classify_ticket_node(state: TicketState) -> Dict[str, Any]:
    logger.info(f"Executing [classify_ticket_node] for ticket {state.get('ticket_id')}")
    prompt = (
        f"Analyze this customer support ticket:\n\n"
        f"Subject: {state.get('subject')}\n"
        f"Description: {state.get('description')}\n"
        f"Customer Email: {state.get('customer_email')}\n"
    )
    system_inst = (
        "You are an expert AI customer support classifier. "
        "Classify the customer's intent, category, urgency, sentiment, and whether account data lookup is needed."
    )
    classification: IntentClassification = await llm_client.generate_structured(
        prompt=prompt,
        system_instruction=system_inst,
        response_model=IntentClassification,
    )
    res_dict = classification.model_dump()
    _log_step(state, "classify_ticket", res_dict)
    return {"classification": res_dict, "audit_logs": state["audit_logs"]}

# ==========================================
# 2. Extract Entities Node
# ==========================================
async def extract_entities_node(state: TicketState) -> Dict[str, Any]:
    logger.info(f"Executing [extract_entities_node] for ticket {state.get('ticket_id')}")
    prompt = (
        f"Extract key business entities from this support ticket:\n\n"
        f"Subject: {state.get('subject')}\n"
        f"Description: {state.get('description')}\n"
        f"Customer Email: {state.get('customer_email')}\n"
    )
    system_inst = (
        "Extract identifiers like customer email, customer ID, order numbers (e.g. ORD-...), subscription IDs, "
        "payment IDs, product items, and mentioned monetary dollar amounts."
    )
    entities: EntityExtraction = await llm_client.generate_structured(
        prompt=prompt,
        system_instruction=system_inst,
        response_model=EntityExtraction,
    )
    entities_dict = entities.model_dump()
    # Fallback to ticket's email if not explicitly in description
    if not entities_dict.get("customer_email") and state.get("customer_email"):
        entities_dict["customer_email"] = state.get("customer_email")

    _log_step(state, "extract_entities", entities_dict)
    return {"entities": entities_dict, "audit_logs": state["audit_logs"]}

# ==========================================
# 3. Context Lookup Node (MCP Tools)
# ==========================================
async def context_lookup_node(state: TicketState) -> Dict[str, Any]:
    logger.info(f"Executing [context_lookup_node] for ticket {state.get('ticket_id')}")
    entities = state.get("entities", {})
    email_or_id = entities.get("customer_email") or state.get("customer_email")
    order_ref = entities.get("order_id_or_number")

    context_data: Dict[str, Any] = {
        "customer_found": False,
        "customer": None,
        "subscriptions": [],
        "orders": [],
        "payments": [],
        "order_details": None,
    }

    # 1. Lookup Customer by Email/ID
    if email_or_id:
        cust_res = await MCPTools.get_customer(email_or_id)
        if cust_res.get("found"):
            context_data["customer_found"] = True
            context_data["customer"] = cust_res["customer"]
            context_data["subscriptions"] = cust_res.get("subscriptions", [])
            context_data["orders"] = cust_res.get("orders", [])
            context_data["payments"] = cust_res.get("payments", [])
            if not state.get("customer_id") and cust_res["customer"].get("id"):
                state["customer_id"] = cust_res["customer"]["id"]

    # 2. Specific Order lookup if mentioned
    if order_ref:
        ord_res = await MCPTools.get_order(order_ref)
        if ord_res.get("found"):
            context_data["order_details"] = ord_res.get("order")

    _log_step(state, "context_lookup", {
        "customer_found": context_data["customer_found"],
        "orders_count": len(context_data["orders"]),
        "subscriptions_count": len(context_data["subscriptions"]),
        "payments_count": len(context_data["payments"]),
    })
    return {"context_data": context_data, "customer_id": state.get("customer_id"), "audit_logs": state["audit_logs"]}

# ==========================================
# 4. Evaluate Business Rules Node (Deterministic)
# ==========================================
async def evaluate_rules_node(state: TicketState) -> Dict[str, Any]:
    logger.info(f"Executing [evaluate_rules_node] for ticket {state.get('ticket_id')}")
    classification = state.get("classification", {})
    context_data = state.get("context_data", {})
    customer = context_data.get("customer")
    payments = context_data.get("payments", [])
    orders = context_data.get("orders", [])
    intent = classification.get("intent", "")

    rule_results: Dict[str, Any] = {}

    # Check 1: Duplicate Charge Detector
    dup_res = BusinessRulesEngine.evaluate_duplicate_charge(
        payments=payments,
    )
    rule_results["duplicate_detector"] = dup_res.model_dump()

    # Check 2: Refund Window Policy
    target_order = context_data.get("order_details")
    if not target_order and orders:
        target_order = orders[0]
    refund_res = BusinessRulesEngine.evaluate_order_refund_eligibility(
        order=target_order,
        payments=payments,
    )
    rule_results["refund_policy"] = refund_res.model_dump()

    # Check 3: Escalation Triggers
    esc_res = BusinessRulesEngine.evaluate_escalation_rules(
        ticket_subject=state.get("subject", ""),
        ticket_description=state.get("description", ""),
        customer=customer,
        orders=orders,
    )
    rule_results["escalation_rules"] = esc_res.model_dump()

    _log_step(state, "evaluate_business_rules", rule_results)
    return {"rules_evaluation": rule_results, "audit_logs": state["audit_logs"]}

# ==========================================
# 5. Decide Resolution Path Node
# ==========================================
async def decide_resolution_node(state: TicketState) -> Dict[str, Any]:
    logger.info(f"Executing [decide_resolution_node] for ticket {state.get('ticket_id')}")
    classification = state.get("classification", {})
    rules = state.get("rules_evaluation", {})
    context = state.get("context_data", {})
    intent = classification.get("intent", "")

    # Priority 1: Deterministic Escalation Trigger
    if rules.get("escalation_rules", {}).get("passed"):
        esc_info = rules["escalation_rules"]
        decision = {
            "resolution_path": "ESCALATED",
            "action_type": "escalate_to_human_agent",
            "action_parameters": esc_info.get("action_parameters", {}),
            "requires_human_approval": False,
            "reasoning": f"Deterministic rule escalation triggered: {esc_info.get('explanation')}",
        }
        _log_step(state, "decide_resolution", decision)
        return {
            "resolution_path": "ESCALATED",
            "proposed_action": decision,
            "original_proposed_action": copy.deepcopy(decision),
            "workflow_status": "ESCALATED",
            "audit_logs": state["audit_logs"],
        }

    # Priority 2: Deterministic Duplicate Payment Detection
    if intent == "duplicate_charge" or rules.get("duplicate_detector", {}).get("passed"):
        dup_rule = rules.get("duplicate_detector", {})
        if dup_rule.get("passed"):
            decision = {
                "resolution_path": "PROPOSE_ACTION_APPROVAL",
                "action_type": "create_refund",
                "action_parameters": dup_rule.get("action_parameters", {}),
                "requires_human_approval": True,
                "reasoning": dup_rule.get("explanation"),
            }
            _log_step(state, "decide_resolution", decision)
            return {
                "resolution_path": "PROPOSE_ACTION_APPROVAL",
                "proposed_action": decision,
                "original_proposed_action": copy.deepcopy(decision),
                "human_approval_status": "PENDING",
                "workflow_status": "WAITING_APPROVAL",
                "audit_logs": state["audit_logs"],
            }

    # Priority 3: Refund Request Evaluation
    if intent == "refund_request":
        ref_rule = rules.get("refund_policy", {})
        if ref_rule.get("passed"):
            # Eligible order within 30 days
            decision = {
                "resolution_path": "PROPOSE_ACTION_APPROVAL",
                "action_type": "create_refund",
                "action_parameters": ref_rule.get("action_parameters", {}),
                "requires_human_approval": True,
                "reasoning": ref_rule.get("explanation"),
            }
            _log_step(state, "decide_resolution", decision)
            return {
                "resolution_path": "PROPOSE_ACTION_APPROVAL",
                "proposed_action": decision,
                "original_proposed_action": copy.deepcopy(decision),
                "human_approval_status": "PENDING",
                "workflow_status": "WAITING_APPROVAL",
                "audit_logs": state["audit_logs"],
            }
        else:
            # Denied by policy (>30 days) -> Direct resolve with clear policy explanation
            decision = {
                "resolution_path": "DIRECT_RESOLVE",
                "action_type": "none",
                "action_parameters": {},
                "requires_human_approval": False,
                "reasoning": ref_rule.get("explanation", "Refund request does not meet 30-day policy criteria."),
            }
            _log_step(state, "decide_resolution", decision)
            return {
                "resolution_path": "DIRECT_RESOLVE",
                "proposed_action": decision,
                "original_proposed_action": copy.deepcopy(decision),
                "workflow_status": "IN_PROGRESS",
                "audit_logs": state["audit_logs"],
            }

    # Priority 4: Subscription Cancellation
    if intent == "subscription_cancellation":
        subs = context.get("subscriptions", [])
        if subs:
            active_sub = subs[0]
            decision = {
                "resolution_path": "PROPOSE_ACTION_APPROVAL",
                "action_type": "cancel_subscription",
                "action_parameters": {
                    "subscription_id": active_sub["id"],
                    "customer_id": active_sub["customer_id"],
                    "immediate": False,
                    "reason": "Customer requested subscription cancellation",
                },
                "requires_human_approval": True,
                "reasoning": f"Active subscription {active_sub['id']} ({active_sub['plan_name']}) eligible for cancellation at period end.",
            }
            _log_step(state, "decide_resolution", decision)
            return {
                "resolution_path": "PROPOSE_ACTION_APPROVAL",
                "proposed_action": decision,
                "original_proposed_action": copy.deepcopy(decision),
                "human_approval_status": "PENDING",
                "workflow_status": "WAITING_APPROVAL",
                "audit_logs": state["audit_logs"],
            }

    # Default / General Question -> Direct Resolve
    decision = {
        "resolution_path": "DIRECT_RESOLVE",
        "action_type": "none",
        "action_parameters": {},
        "requires_human_approval": False,
        "reasoning": "Standard inquiry or policy answer. No external mutation needed.",
    }
    _log_step(state, "decide_resolution", decision)
    return {
        "resolution_path": "DIRECT_RESOLVE",
        "proposed_action": decision,
        "original_proposed_action": copy.deepcopy(decision),
        "workflow_status": "IN_PROGRESS",
        "audit_logs": state["audit_logs"],
    }

# ==========================================
# 6. Draft Customer Response Node (Context-Aware Generator)
# ==========================================
async def draft_response_node(state: TicketState) -> Dict[str, Any]:
    """
    Generates a highly context-aware, empathetic, and specific customer-facing resolution email.
    Incorporates customer account details, orders, items, tracking, payments, rule outcomes, and actions.
    """
    logger.info(f"Executing [draft_response_node] for ticket {state.get('ticket_id')}")
    proposed = state.get("proposed_action", {})
    res_path = state.get("resolution_path", "DIRECT_RESOLVE")
    context = state.get("context_data", {})
    customer = context.get("customer", {})
    orders = context.get("orders", [])
    payments = context.get("payments", [])
    subscriptions = context.get("subscriptions", [])
    rules = state.get("rules_evaluation", {})

    prompt = (
        f"Customer Support Case Context:\n"
        f"- Ticket ID: {state.get('ticket_id')}\n"
        f"- Customer Email: {state.get('customer_email')}\n"
        f"- Customer Name: {customer.get('name') if customer else 'Valued Customer'}\n"
        f"- Subject: {state.get('subject')}\n"
        f"- Customer Message: {state.get('description')}\n"
        f"- Classification: {json.dumps(state.get('classification', {}))}\n"
        f"- Resolution Path: {res_path}\n"
        f"- Proposed Action: {json.dumps(proposed)}\n"
        f"- Rules Evaluation: {json.dumps(rules)}\n"
        f"- Account Orders: {json.dumps(orders)}\n"
        f"- Account Payments: {json.dumps(payments)}\n"
        f"- Account Subscriptions: {json.dumps(subscriptions)}\n"
    )
    system_inst = (
        "You are an empathetic, professional senior customer support specialist for NovaDesk AI.\n"
        "Draft a context-rich, personalized, and clear resolution email to the customer.\n"
        "Rules for the response:\n"
        "1. Always address the customer warmly by their name if available.\n"
        "2. Directly reference specific details: order numbers (e.g. ORD-2026-9021), product item names (e.g. iPhone 15 Pro, Sony Headphones), tracking status, or exact refund dollar amounts ($49.00 USD).\n"
        "3. If a duplicate charge or refund is authorized, confirm the exact dollar amount refunded and that it will appear on their bank statement in 3-5 business days.\n"
        "4. If a package is delayed, reassure the customer with tracking status and provide clear next steps.\n"
        "5. If a subscription cancellation is requested, confirm the plan name and explain access continues until the end of the current billing cycle without further charges.\n"
        "6. If a refund is denied due to exceeding the 30-day return policy window, politely explain the policy and offer warranty or store support.\n"
        "7. Never use generic or vague boilerplate. Be specific, empathetic, and clear."
    )
    draft: CustomerResponseDraft = await llm_client.generate_structured(
        prompt=prompt,
        system_instruction=system_inst,
        response_model=CustomerResponseDraft,
    )
    draft_dict = draft.model_dump()
    _log_step(state, "draft_response", draft_dict)

    return {
        "response_draft": draft_dict,
        "final_response": draft_dict,
        "audit_logs": state["audit_logs"],
    }

# ==========================================
# 7. Human-in-the-Loop Approval Node (Checkpoint)
# ==========================================
async def human_approval_node(state: TicketState) -> Dict[str, Any]:
    """
    Pauses execution at the HITL checkpoint if approval is PENDING.
    Provides operator with proposed action, rule checks, refund amount, and response draft.
    Resumes with human decision: APPROVED, MODIFIED, or REJECTED.
    """
    logger.info(f"Executing [human_approval_node] for ticket {state.get('ticket_id')}")
    current_status = state.get("human_approval_status", "PENDING")
    proposed = state.get("proposed_action", {})
    params = proposed.get("action_parameters", {})

    if not state.get("original_proposed_action"):
        state["original_proposed_action"] = copy.deepcopy(proposed)

    if current_status == "PENDING":
        # Trigger LangGraph interrupt - paused until human provides response via API
        human_input = interrupt({
            "message": "Human approval required for proposed consequential action.",
            "ticket_id": state.get("ticket_id"),
            "proposed_action": proposed,
            "rule_checks": state.get("rules_evaluation"),
            "refund_amount": params.get("amount"),
            "generated_response": state.get("response_draft"),
            "customer_email": state.get("customer_email"),
        })
        
        # When resumed, human_input contains the decision
        if isinstance(human_input, dict):
            decision = human_input.get("decision", "APPROVED").upper()
            notes = human_input.get("notes", "")
            modified_params = human_input.get("modified_parameters")
            
            if modified_params and state.get("proposed_action"):
                state["proposed_action"]["action_parameters"].update(modified_params)
            
            state["human_approval_status"] = decision
            state["human_feedback_notes"] = notes
        else:
            state["human_approval_status"] = "APPROVED"

    _log_step(state, "human_approval_checkpoint", {
        "decision": state.get("human_approval_status"),
        "feedback_notes": state.get("human_feedback_notes"),
        "original_proposed_action": state.get("original_proposed_action"),
        "final_parameters": state.get("proposed_action", {}).get("action_parameters"),
    })
    return {
        "human_approval_status": state.get("human_approval_status"),
        "human_feedback_notes": state.get("human_feedback_notes"),
        "proposed_action": state.get("proposed_action"),
        "original_proposed_action": state.get("original_proposed_action"),
        "audit_logs": state["audit_logs"],
    }

# ==========================================
# 8. Execute Action Node (Deterministic Revalidation & Execution)
# ==========================================
async def execute_action_node(state: TicketState) -> Dict[str, Any]:
    """
    Executes consequential actions strictly after human authorization or direct resolution.
    Revalidates parameters deterministically, executes mutations, dispatches customer email, and logs audit steps.
    """
    logger.info(f"Executing [execute_action_node] for ticket {state.get('ticket_id')}")
    approval = state.get("human_approval_status", "APPROVED")
    proposed = state.get("proposed_action", {})
    action_type = proposed.get("action_type")
    params = proposed.get("action_parameters", {})
    context = state.get("context_data", {})
    payments = context.get("payments", [])
    response_draft = state.get("response_draft") or state.get("final_response") or {}

    # ----------------------------------------------------
    # PATH 1: HUMAN REJECTION
    # ----------------------------------------------------
    if approval == "REJECTED":
        logger.info(f"Action rejected by operator for ticket {state.get('ticket_id')}")
        action_result = {
            "success": False,
            "action": action_type,
            "status": "REJECTED_BY_HUMAN",
            "message": f"Action was rejected by support operator: {state.get('human_feedback_notes', 'Policy non-compliance')}",
        }
        _log_step(state, "execute_action", {
            "action_executed": False,
            "action_type": action_type,
            "status": "REJECTED_BY_HUMAN",
            "operator_notes": state.get("human_feedback_notes"),
        })

        # Generate polite rejection email explanation
        notes = state.get("human_feedback_notes", "Your request does not meet our standard refund criteria at this time.")
        final_response_dict = {
            "subject": f"Update regarding your inquiry [Ticket #{state.get('ticket_id')}]",
            "greeting": response_draft.get("greeting", "Dear Customer,"),
            "body": f"Thank you for contacting NovaDesk support. Following a manual review by our operations team, we are unable to process your request for the following reason:\n\n{notes}\n\nWe apologize for any inconvenience.",
            "next_steps": "If you have any further questions or require additional assistance, please reply directly to this message.",
            "sentiment_score": 0.5,
        }

        # Dispatch email
        if state.get("customer_email"):
            await MCPTools.send_email(
                to_email=state["customer_email"],
                subject=final_response_dict["subject"],
                body=f"{final_response_dict['greeting']}\n\n{final_response_dict['body']}\n\n{final_response_dict.get('next_steps', '')}",
                ticket_id=state.get("ticket_id"),
            )
            _log_step(state, "dispatch_email", {"recipient": state["customer_email"], "status": "sent", "type": "rejection_notice"})

        return {
            "action_result": action_result,
            "final_response": final_response_dict,
            "resolution_path": "ACTION_REJECTED",
            "audit_logs": state["audit_logs"],
        }

    # ----------------------------------------------------
    # PATH 2: MODIFIED OR APPROVED ACTION (Consequential or Direct)
    # ----------------------------------------------------
    action_result: Dict[str, Any] = {}
    reval_result: Optional[Dict[str, Any]] = None

    if action_type == "create_refund":
        payment_id = params.get("payment_id", "")
        amount = float(params.get("amount", 0.0))

        # Deterministic parameter revalidation
        reval = BusinessRulesEngine.revalidate_refund_parameters(
            payment_id=payment_id,
            amount=amount,
            payments=payments,
        )
        reval_result = reval.model_dump()
        state["revalidation_result"] = reval_result
        _log_step(state, "parameter_revalidation", reval_result)

        if not reval.passed:
            action_result = {
                "success": False,
                "action": "create_refund",
                "status": "REVALIDATION_FAILED",
                "message": f"Deterministic parameter revalidation failed: {reval.explanation}",
            }
            _log_step(state, "execute_action", action_result)
            return {
                "action_result": action_result,
                "revalidation_result": reval_result,
                "resolution_path": "ACTION_REJECTED",
                "audit_logs": state["audit_logs"],
            }

        # Execute MCP Tool Refund
        action_result = await MCPTools.create_refund(
            payment_id=payment_id,
            amount=amount,
            reason=params.get("reason", "Customer refund approved"),
            approved_by=f"supervisor_{approval.lower()}",
        )
        _log_step(state, "execute_action", {
            "action_executed": True,
            "action_type": "create_refund",
            "parameters": {"payment_id": payment_id, "amount": amount},
            "result": action_result,
            "approval_type": approval,
        })

    elif action_type == "cancel_subscription":
        action_result = await MCPTools.cancel_subscription(
            subscription_id=params["subscription_id"],
            immediate=params.get("immediate", False),
            reason=params.get("reason", "Customer requested cancellation"),
        )
        _log_step(state, "execute_action", {
            "action_executed": True,
            "action_type": "cancel_subscription",
            "result": action_result,
        })

    else:
        action_result = {"success": True, "action": "none", "message": "No mutation required. Direct resolution applied."}
        _log_step(state, "execute_action", {"action_executed": False, "action_type": "none", "result": action_result})

    # Prepare final response payload (adjust if modified)
    final_resp = copy.deepcopy(response_draft)
    if approval == "MODIFIED" and action_type == "create_refund":
        new_amt = float(params.get("amount", 0.0))
        final_resp["body"] = f"We have reviewed your request and processed an adjusted refund of ${new_amt:.2f} USD to your original payment method. {state.get('human_feedback_notes', '')}".strip()
        final_resp["next_steps"] = "The funds should appear on your bank statement within 3-5 business days."

    # Dispatch email via MCP tool
    if state.get("customer_email") and final_resp:
        greeting = (final_resp.get("greeting") or "Dear Customer,").strip()
        body = (final_resp.get("body") or "").strip()
        next_steps = (final_resp.get("next_steps") or "").strip()
        if greeting and (body.lower().startswith(greeting.lower()) or any(body.lower().startswith(g) for g in ["hello", "dear", "hi", "good morning", "good afternoon"])):
            email_body = f"{body}\n\n{next_steps}".strip()
        else:
            email_body = f"{greeting}\n\n{body}\n\n{next_steps}".strip()

        await MCPTools.send_email(
            to_email=state["customer_email"],
            subject=final_resp.get("subject", f"Update on Ticket #{state.get('ticket_id')}"),
            body=email_body,
            ticket_id=state.get("ticket_id"),
        )
        _log_step(state, "dispatch_email", {
            "recipient": state["customer_email"],
            "subject": final_resp.get("subject"),
            "status": "sent",
        })

    res_path = "ACTION_APPROVED" if approval in ["APPROVED", "MODIFIED"] and action_type != "none" else state.get("resolution_path", "DIRECT_RESOLVE")

    return {
        "action_result": action_result,
        "final_response": final_resp,
        "revalidation_result": reval_result,
        "resolution_path": res_path,
        "audit_logs": state["audit_logs"],
    }

# ==========================================
# 9. Finalize Ticket Node (DB Persistence)
# ==========================================
async def finalize_ticket_node(state: TicketState) -> Dict[str, Any]:
    logger.info(f"Executing [finalize_ticket_node] for ticket {state.get('ticket_id')}")
    ticket_id = state.get("ticket_id")
    res_path = state.get("resolution_path", "DIRECT_RESOLVE")
    final_resp = state.get("final_response") or state.get("response_draft") or {}

    if res_path == "ESCALATED":
        status = "escalated"
        summary = f"Escalated to specialist team: {state.get('proposed_action', {}).get('reasoning', 'Manual review required')}"
    elif res_path == "ACTION_REJECTED":
        status = "closed"
        summary = f"Action rejected: {state.get('human_feedback_notes', 'Policy non-compliance')}"
    else:
        status = "resolved"
        greeting = (final_resp.get("greeting") or "").strip()
        body = (final_resp.get("body") or "").strip()
        next_steps = (final_resp.get("next_steps") or "").strip()
        if greeting and (body.lower().startswith(greeting.lower()) or any(body.lower().startswith(g) for g in ["hello", "dear", "hi", "good morning", "good afternoon"])):
            full_email = f"{body}\n\n{next_steps}".strip()
        else:
            full_email = f"{greeting}\n\n{body}\n\n{next_steps}".strip()
        summary = full_email if full_email else body

    sent_email_record = None
    if final_resp:
        sent_email_record = {
            "to": state.get("customer_email"),
            "subject": final_resp.get("subject", f"Update on Ticket #{ticket_id}"),
            "greeting": final_resp.get("greeting", "Dear Customer,"),
            "body": final_resp.get("body", ""),
            "next_steps": final_resp.get("next_steps", ""),
            "timestamp": utc_now().isoformat(),
            "from": "NovaDesk Support <support@novadesk.ai>",
        }


    # Update ticket in DB
    if ticket_id:
        await MCPTools.update_ticket(
            ticket_id=ticket_id,
            status=status,
            resolution_summary=summary,
            resolution_path=res_path,
            metadata={
                "audit_logs": state.get("audit_logs", []),
                "classification": state.get("classification"),
                "rules": state.get("rules_evaluation"),
                "proposed_action": state.get("proposed_action"),
                "original_proposed_action": state.get("original_proposed_action"),
                "human_approval_status": state.get("human_approval_status"),
                "human_feedback_notes": state.get("human_feedback_notes"),
                "revalidation_result": state.get("revalidation_result"),
                "action_result": state.get("action_result"),
                "response_draft": state.get("response_draft"),
                "final_response": final_resp,
                "sent_email": sent_email_record,
            },
        )

    _log_step(state, "finalize_ticket", {"final_status": status, "resolution_path": res_path})
    return {"workflow_status": "COMPLETED" if status == "resolved" else status.upper(), "audit_logs": state["audit_logs"]}
