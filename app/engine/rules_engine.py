from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional
from pydantic import BaseModel
from app.utils import utc_now

class RuleEvaluationResult(BaseModel):
    rule_name: str
    passed: bool
    requires_human_approval: bool
    proposed_action: Optional[str] = None
    action_parameters: Dict[str, Any] = {}
    explanation: str
    confidence: float = 1.0

class BusinessRulesEngine:
    """
    Deterministic rules engine.
    Ensures zero hallucination for financial operations, refund eligibility, and routing constraints.
    """

    REFUND_WINDOW_DAYS: int = 30
    DUPLICATE_TIME_WINDOW_HOURS: int = 24
    SUPERVISOR_APPROVAL_THRESHOLD: float = 100.0

    @classmethod
    def evaluate_duplicate_charge(
        cls,
        payments: List[Dict[str, Any]],
        subscription_id: Optional[str] = None,
        order_id: Optional[str] = None,
    ) -> RuleEvaluationResult:
        """
        Deterministic check for duplicate payments within the duplicate time window.
        """
        if not payments or len(payments) < 2:
            return RuleEvaluationResult(
                rule_name="DUPLICATE_PAYMENT_DETECTOR",
                passed=False,
                requires_human_approval=False,
                explanation="No duplicate transactions detected (fewer than 2 payments found).",
            )

        # Filter relevant payments
        relevant = []
        for p in payments:
            if p.get("status") in ["succeeded", "partially_refunded"]:
                if subscription_id and p.get("subscription_id") == subscription_id:
                    relevant.append(p)
                elif order_id and p.get("order_id") == order_id:
                    relevant.append(p)
                elif not subscription_id and not order_id:
                    relevant.append(p)

        # Sort payments chronologically
        def parse_date(date_val):
            if isinstance(date_val, datetime):
                return date_val
            if isinstance(date_val, str):
                return datetime.fromisoformat(date_val.replace("Z", "+00:00")).replace(tzinfo=None)
            return utc_now()

        relevant.sort(key=lambda x: parse_date(x["created_at"]))

        # Check adjacent pairs for duplicate amount within window
        for i in range(len(relevant) - 1):
            p1 = relevant[i]
            p2 = relevant[i + 1]
            t1 = parse_date(p1["created_at"])
            t2 = parse_date(p2["created_at"])

            time_diff_hours = abs((t2 - t1).total_seconds()) / 3600.0
            same_amount = abs(p1["amount"] - p2["amount"]) < 0.01

            if same_amount and time_diff_hours <= cls.DUPLICATE_TIME_WINDOW_HOURS:
                duplicate_payment = p2  # The second duplicate transaction to refund
                return RuleEvaluationResult(
                    rule_name="DUPLICATE_PAYMENT_DETECTOR",
                    passed=True,
                    requires_human_approval=True,
                    proposed_action="create_refund",
                    action_parameters={
                        "payment_id": duplicate_payment["id"],
                        "customer_id": duplicate_payment.get("customer_id"),
                        "amount": duplicate_payment["amount"],
                        "reason": f"Automated refund for verified duplicate charge (Txn {duplicate_payment.get('transaction_ref', duplicate_payment.get('id', 'N/A'))}) within {time_diff_hours:.1f} hours of original charge.",
                        "original_payment_id": p1["id"],
                    },
                    explanation=f"Verified duplicate charge: Payment {p2['id']} (${p2['amount']:.2f}) occurred {time_diff_hours:.1f} hours after Payment {p1['id']} (${p1['amount']:.2f}).",
                )

        return RuleEvaluationResult(
            rule_name="DUPLICATE_PAYMENT_DETECTOR",
            passed=False,
            requires_human_approval=False,
            explanation="No duplicate charges found matching identical amounts within 24 hours.",
        )

    @classmethod
    def evaluate_order_refund_eligibility(
        cls,
        order: Optional[Dict[str, Any]],
        payments: List[Dict[str, Any]],
    ) -> RuleEvaluationResult:
        """
        Deterministic check for order return/refund window eligibility (<= 30 days).
        """
        if not order:
            return RuleEvaluationResult(
                rule_name="REFUND_WINDOW_POLICY",
                passed=False,
                requires_human_approval=False,
                explanation="No order provided for refund eligibility check.",
            )

        def parse_date(date_val):
            if isinstance(date_val, datetime):
                return date_val
            if isinstance(date_val, str):
                return datetime.fromisoformat(date_val.replace("Z", "+00:00")).replace(tzinfo=None)
            return utc_now()

        ref_date = parse_date(order.get("delivered_at") or order.get("created_at"))
        now = utc_now()
        elapsed_days = (now - ref_date).days

        # Find successful payment
        succeeded_payments = [p for p in payments if p.get("status") == "succeeded" and p.get("order_id") == order["id"]]
        if not succeeded_payments:
            succeeded_payments = [p for p in payments if p.get("status") == "succeeded"]

        if not succeeded_payments:
            return RuleEvaluationResult(
                rule_name="REFUND_WINDOW_POLICY",
                passed=False,
                requires_human_approval=False,
                explanation="No eligible successful payment record found for this order.",
            )

        target_payment = succeeded_payments[0]

        if elapsed_days > cls.REFUND_WINDOW_DAYS:
            return RuleEvaluationResult(
                rule_name="REFUND_WINDOW_POLICY",
                passed=False,
                requires_human_approval=False,
                proposed_action=None,
                explanation=f"Order {order['order_number']} was delivered/placed {elapsed_days} days ago, exceeding the strict 30-day return & refund window. Full refund cannot be automatically approved.",
            )

        # Within 30 days -> eligible for refund with human approval
        return RuleEvaluationResult(
            rule_name="REFUND_WINDOW_POLICY",
            passed=True,
            requires_human_approval=True,
            proposed_action="create_refund",
            action_parameters={
                "payment_id": target_payment["id"],
                "customer_id": order["customer_id"],
                "order_id": order["id"],
                "amount": order["total_amount"],
                "reason": f"Order {order['order_number']} return/refund within eligible {elapsed_days}-day window.",
            },
            explanation=f"Order {order['order_number']} is within the {cls.REFUND_WINDOW_DAYS}-day return window (Elapsed: {elapsed_days} days). Eligible for refund upon human sign-off.",
        )

    @classmethod
    def evaluate_escalation_rules(
        cls,
        ticket_subject: str,
        ticket_description: str,
        customer: Optional[Dict[str, Any]] = None,
        orders: Optional[List[Dict[str, Any]]] = None,
    ) -> RuleEvaluationResult:
        """
        Deterministic check for escalation triggers (VIP accounts, lost shipping, hostile sentiment).
        """
        full_text = f"{ticket_subject} {ticket_description}".lower()

        # 1. VIP / Enterprise check
        if customer and customer.get("tier") in ["VIP", "Enterprise"]:
            return RuleEvaluationResult(
                rule_name="VIP_ESCALATION_TRIGGER",
                passed=True,
                requires_human_approval=False,
                proposed_action="escalate_to_human_agent",
                action_parameters={"priority": "urgent", "assigned_tier": "VIP_Support_Team"},
                explanation=f"Customer {customer.get('name')} is in tier '{customer.get('tier')}'. Routing to dedicated VIP Support Team.",
            )

        # 2. Lost in Transit Check
        if orders:
            for ord in orders:
                if ord.get("status") in ["delayed", "in_transit"]:
                    def parse_date(date_val):
                        if isinstance(date_val, datetime):
                            return date_val
                        if isinstance(date_val, str):
                            return datetime.fromisoformat(date_val.replace("Z", "+00:00")).replace(tzinfo=None)
                        return utc_now()
                    elapsed = (utc_now() - parse_date(ord["created_at"])).days
                    if elapsed > 7 and ("lost" in full_text or "haven't received" in full_text or "where is" in full_text):
                        return RuleEvaluationResult(
                            rule_name="SHIPPING_DELAY_ESCALATION",
                            passed=True,
                            requires_human_approval=False,
                            proposed_action="escalate_to_human_agent",
                            action_parameters={"priority": "high", "order_id": ord["id"], "tracking": ord.get("tracking_number")},
                            explanation=f"Order {ord['order_number']} has been in transit for {elapsed} days. Escalating to Logistics Specialist.",
                        )

        # 3. Explicit keywords
        escalation_keywords = ["lawyer", "attorney", "sue", "legal action", "fraud department", "manager immediately", "supervisor immediately"]
        for kw in escalation_keywords:
            if kw in full_text:
                return RuleEvaluationResult(
                    rule_name="LEGAL_SUPERVISOR_ESCALATION",
                    passed=True,
                    requires_human_approval=False,
                    proposed_action="escalate_to_human_agent",
                    action_parameters={"priority": "urgent", "reason": f"Escalation keyword detected: '{kw}'"},
                    explanation=f"Customer request contains sensitive escalation phrase '{kw}'. Immediate human handover required.",
                )

        return RuleEvaluationResult(
            rule_name="ESCALATION_POLICY",
            passed=False,
            requires_human_approval=False,
            explanation="No mandatory escalation rules triggered.",
        )

    @classmethod
    def revalidate_refund_parameters(
        cls,
        payment_id: str,
        amount: float,
        payments: Optional[List[Dict[str, Any]]] = None,
        max_allowed_amount: Optional[float] = None,
    ) -> RuleEvaluationResult:
        """
        Deterministic revalidation of refund parameters before execution.
        Verifies:
        1. Amount is strictly positive.
        2. Amount does not exceed the target payment amount (or max_allowed_amount).
        3. Payment is not already marked as fully refunded.
        """
        if amount <= 0:
            return RuleEvaluationResult(
                rule_name="REFUND_PARAMETER_REVALIDATION",
                passed=False,
                requires_human_approval=True,
                explanation=f"Invalid refund amount ${amount:.2f}: Refund amount must be strictly greater than $0.00.",
            )

        target_payment = None
        if payments:
            for p in payments:
                if p.get("id") == payment_id:
                    target_payment = p
                    break

        if target_payment:
            if target_payment.get("status") == "refunded":
                return RuleEvaluationResult(
                    rule_name="REFUND_PARAMETER_REVALIDATION",
                    passed=False,
                    requires_human_approval=True,
                    explanation=f"Payment {payment_id} has already been fully refunded.",
                )
            
            orig_amount = float(target_payment.get("amount", 0.0))
            if amount > orig_amount + 0.01:
                return RuleEvaluationResult(
                    rule_name="REFUND_PARAMETER_REVALIDATION",
                    passed=False,
                    requires_human_approval=True,
                    explanation=f"Requested refund amount ${amount:.2f} exceeds original transaction amount ${orig_amount:.2f}.",
                )

        if max_allowed_amount is not None and amount > max_allowed_amount + 0.01:
            return RuleEvaluationResult(
                rule_name="REFUND_PARAMETER_REVALIDATION",
                passed=False,
                requires_human_approval=True,
                explanation=f"Requested refund amount ${amount:.2f} exceeds maximum allowed amount ${max_allowed_amount:.2f}.",
            )

        return RuleEvaluationResult(
            rule_name="REFUND_PARAMETER_REVALIDATION",
            passed=True,
            requires_human_approval=False,
            proposed_action="create_refund",
            action_parameters={"payment_id": payment_id, "amount": round(amount, 2)},
            explanation=f"Deterministic parameter revalidation passed for Payment {payment_id} (${amount:.2f}).",
        )

