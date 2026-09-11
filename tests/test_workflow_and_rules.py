import pytest
from datetime import timedelta
from httpx import AsyncClient, ASGITransport
from app.main import app
from app.engine.rules_engine import BusinessRulesEngine
from app.tools.mcp_tools import MCPTools
from app.utils import utc_now

@pytest.mark.asyncio
async def test_mcp_customer_lookup():
    res = await MCPTools.get_customer("alice@example.com")
    assert res["found"] is True
    assert res["customer"]["name"] == "Alice Smith"
    assert len(res["payments"]) >= 2

@pytest.mark.asyncio
async def test_deterministic_duplicate_rule():
    now = utc_now()
    test_payments = [
        {"id": "pay_test_1", "amount": 49.00, "currency": "USD", "status": "succeeded", "created_at": now - timedelta(hours=1)},
        {"id": "pay_test_2", "amount": 49.00, "currency": "USD", "status": "succeeded", "created_at": now},
    ]
    rule_res = BusinessRulesEngine.evaluate_duplicate_charge(payments=test_payments)
    
    assert rule_res.passed is True
    assert rule_res.requires_human_approval is True
    assert rule_res.proposed_action == "create_refund"
    assert rule_res.action_parameters["amount"] == 49.00

@pytest.mark.asyncio
async def test_deterministic_parameter_revalidation():
    test_payments = [
        {"id": "pay_1", "amount": 100.00, "status": "succeeded"},
        {"id": "pay_2", "amount": 50.00, "status": "refunded"},
    ]
    # Test valid amount <= payment amount
    res_valid = BusinessRulesEngine.revalidate_refund_parameters("pay_1", 100.00, payments=test_payments)
    assert res_valid.passed is True

    # Test valid partial amount
    res_partial = BusinessRulesEngine.revalidate_refund_parameters("pay_1", 25.00, payments=test_payments)
    assert res_partial.passed is True

    # Test negative amount
    res_neg = BusinessRulesEngine.revalidate_refund_parameters("pay_1", -10.00, payments=test_payments)
    assert res_neg.passed is False

    # Test excessive amount > payment
    res_excess = BusinessRulesEngine.revalidate_refund_parameters("pay_1", 150.00, payments=test_payments)
    assert res_excess.passed is False

    # Test already refunded payment
    res_refunded = BusinessRulesEngine.revalidate_refund_parameters("pay_2", 50.00, payments=test_payments)
    assert res_refunded.passed is False

@pytest.mark.asyncio
async def test_deterministic_refund_window_policy():
    # Bob Jones: within 30 days
    ord_bob = await MCPTools.get_order("ORD-2026-9021")
    pay_bob = await MCPTools.get_payments("cust_102")
    rule_bob = BusinessRulesEngine.evaluate_order_refund_eligibility(
        order=ord_bob["order"],
        payments=pay_bob["payments"],
    )
    assert rule_bob.passed is True
    assert rule_bob.requires_human_approval is True

    # Charlie Brown: > 30 days
    ord_charlie = await MCPTools.get_order("ORD-2026-1184")
    pay_charlie = await MCPTools.get_payments("cust_103")
    rule_charlie = BusinessRulesEngine.evaluate_order_refund_eligibility(
        order=ord_charlie["order"],
        payments=pay_charlie["payments"],
    )
    assert rule_charlie.passed is False
    assert rule_charlie.proposed_action is None

@pytest.mark.asyncio
async def test_langgraph_duplicate_charge_hitl_approve_and_send():
    """
    Tests complete Billing HITL flow:
    1. Submit duplicate charge ticket
    2. Workflow pre-generates customer response draft and pauses at checkpoint
    3. Operator inspects proposed action, amount, rules, and draft response
    4. Operator approves ('Approve & Send')
    5. Parameters are revalidated deterministically, refund executed, email sent, and ticket resolved.
    """
    from app.db.database import AsyncSessionLocal
    from app.db.models import Payment
    from sqlalchemy import update
    async with AsyncSessionLocal() as session:
        await session.execute(
            update(Payment).where(Payment.id.in_(["pay_101", "pay_102"])).values(status="succeeded")
        )
        await session.commit()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        ticket_payload = {
            "ticket_id": "test_hitl_approve_01",
            "customer_email": "alice@example.com",
            "subject": "Duplicate charge on subscription",
            "description": "I got billed twice $49.00 for my Pro subscription. Please refund the second charge.",
        }
        res = await ac.post("/api/workflow/process", json=ticket_payload)
        assert res.status_code == 200
        data = res.json()
        
        # Verify paused at human approval checkpoint
        assert data["is_waiting_human_approval"] is True
        assert data["proposed_action"]["action_type"] == "create_refund"
        assert data["proposed_action"]["action_parameters"]["amount"] == 49.00
        assert data["response_draft"] is not None or data["final_response"] is not None

        # Operator submits Approve & Send
        approval_payload = {
            "decision": "APPROVED",
            "notes": "Verified duplicate charge on account. Approved $49.00 refund.",
        }
        resume_res = await ac.post(f"/api/workflow/approve/{ticket_payload['ticket_id']}", json=approval_payload)
        assert resume_res.status_code == 200
        resumed_data = resume_res.json()
        
        # Verify workflow completed, refund executed, and email dispatched
        assert resumed_data["workflow_status"] == "COMPLETED"
        assert resumed_data["resolution_path"] == "ACTION_APPROVED"
        assert resumed_data["action_result"]["success"] is True
        assert resumed_data["final_response"]["body"] != ""

        # Verify audit logs contain parameter revalidation and execution steps
        steps = [l["step"] for l in resumed_data["audit_logs"]]
        assert "human_approval_checkpoint" in steps
        assert "parameter_revalidation" in steps
        assert "execute_action" in steps
        assert "dispatch_email" in steps
        assert "finalize_ticket" in steps

@pytest.mark.asyncio
async def test_langgraph_duplicate_charge_hitl_modify_amount():
    """
    Tests Billing HITL flow when operator modifies the refund parameters:
    1. Workflow pauses at checkpoint
    2. Operator modifies refund amount to $20.00
    3. Modified parameters revalidated, refund executed for $20.00, updated email sent.
    """
    from app.db.database import AsyncSessionLocal
    from app.db.models import Payment
    from sqlalchemy import update
    async with AsyncSessionLocal() as session:
        await session.execute(
            update(Payment).where(Payment.id.in_(["pay_101", "pay_102"])).values(status="succeeded")
        )
        await session.commit()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        ticket_payload = {
            "ticket_id": "test_hitl_modify_01",
            "customer_email": "alice@example.com",
            "subject": "Duplicate charge on subscription",
            "description": "I got billed twice $49.00 for my Pro subscription.",
        }
        res = await ac.post("/api/workflow/process", json=ticket_payload)
        assert res.status_code == 200
        data = res.json()
        assert data["is_waiting_human_approval"] is True

        # Operator modifies refund amount to $20.00
        modify_payload = {
            "decision": "MODIFIED",
            "notes": "Approved partial goodwill credit of $20.00",
            "modified_parameters": {"amount": 20.00},
        }
        resume_res = await ac.post(f"/api/workflow/approve/{ticket_payload['ticket_id']}", json=modify_payload)
        assert resume_res.status_code == 200
        resumed_data = resume_res.json()

        assert resumed_data["workflow_status"] == "COMPLETED"
        assert resumed_data["action_result"]["success"] is True
        assert resumed_data["action_result"]["refund"]["amount"] == 20.00
        assert "20.00" in resumed_data["final_response"]["body"] or "goodwill" in resumed_data["final_response"]["body"].lower()

@pytest.mark.asyncio
async def test_langgraph_duplicate_charge_hitl_rejection():
    """
    Tests Billing HITL flow when operator rejects the action:
    1. Workflow pauses at checkpoint
    2. Operator rejects refund with notes
    3. Refund is NOT executed, rejection notice sent to customer, ticket closed.
    """
    from app.db.database import AsyncSessionLocal
    from app.db.models import Payment
    from sqlalchemy import update
    async with AsyncSessionLocal() as session:
        await session.execute(
            update(Payment).where(Payment.id.in_(["pay_101", "pay_102"])).values(status="succeeded")
        )
        await session.commit()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        ticket_payload = {
            "ticket_id": "test_hitl_reject_01",
            "customer_email": "alice@example.com",
            "subject": "Duplicate charge on subscription",
            "description": "I got billed twice $49.00 for my Pro subscription.",
        }
        res = await ac.post("/api/workflow/process", json=ticket_payload)
        assert res.status_code == 200
        data = res.json()
        assert data["is_waiting_human_approval"] is True

        # Operator rejects
        reject_payload = {
            "decision": "REJECTED",
            "notes": "Charges were for two separate legitimate annual add-ons.",
        }
        resume_res = await ac.post(f"/api/workflow/approve/{ticket_payload['ticket_id']}", json=reject_payload)
        assert resume_res.status_code == 200
        resumed_data = resume_res.json()

        assert resumed_data["workflow_status"] == "CLOSED"
        assert resumed_data["resolution_path"] == "ACTION_REJECTED"
        assert resumed_data["action_result"]["success"] is False
        assert resumed_data["action_result"]["status"] == "REJECTED_BY_HUMAN"
        assert "separate legitimate" in resumed_data["final_response"]["body"] or "unable to process" in resumed_data["final_response"]["body"].lower()

@pytest.mark.asyncio
async def test_langgraph_direct_resolve_expired_refund():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        ticket_payload = {
            "ticket_id": "test_tkt_charlie_expired_01",
            "customer_email": "charlie@example.com",
            "subject": "Refund request for ORD-2026-1184",
            "description": "I bought a jacket in June (ORD-2026-1184) and want a refund of $149.",
        }
        res = await ac.post("/api/workflow/process", json=ticket_payload)
        assert res.status_code == 200
        data = res.json()
        
        # Should directly resolve without human approval since policy denies refund
        assert data["is_waiting_human_approval"] is False
        assert data["resolution_path"] == "DIRECT_RESOLVE"
        assert data["workflow_status"] == "COMPLETED"
        assert "30-day" in data["proposed_action"]["reasoning"] or "policy" in data["proposed_action"]["reasoning"].lower()

@pytest.mark.asyncio
async def test_automated_evaluation_suite_endpoint():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        res = await ac.post("/api/workflow/evaluate")
        assert res.status_code == 200
        report = res.json()
        assert report["total_test_cases"] == 7
        assert report["metrics"]["deterministic_rule_compliance"] == 100.0
        assert report["metrics"]["resolution_routing_accuracy"] >= 85.0
        assert report["metrics"]["human_approval_gating_compliance"] == 100.0

@pytest.mark.asyncio
async def test_immediate_ticket_submission_with_background_task():
    """
    Verifies that for non-billing categories (e.g. shipping), POST /api/system/tickets
    returns immediately with status 'in_progress' and schedules the background AI workflow.
    For billing categories, it returns with status 'open' allowing operator review.
    """
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        # Non-billing category -> in_progress (auto background workflow)
        payload_shipping = {
            "customer_email": "diana@example.com",
            "subject": "Delayed shipment ORD-1234",
            "category": "shipping",
            "description": "Where is my package?",
        }
        res_ship = await ac.post("/api/system/tickets", json=payload_shipping)
        assert res_ship.status_code == 200
        assert res_ship.json()["status"] == "in_progress"

        # Billing category -> open (pauses automation, operator choice)
        payload_billing = {
            "customer_email": "alice@example.com",
            "subject": "Duplicate charge on subscription",
            "category": "billing",
            "description": "I was billed twice $49.00 for my Pro subscription.",
        }
        res_bill = await ac.post("/api/system/tickets", json=payload_billing)
        assert res_bill.status_code == 200
        assert res_bill.json()["status"] == "open"

@pytest.mark.asyncio
async def test_operator_manual_custom_reply():
    """
    Verifies that an operator can submit a manual custom response to a billing ticket,
    resolving the ticket and dispatching an email to the customer.
    """
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        create_res = await ac.post("/api/system/tickets", json={
            "customer_email": "manual_cust@example.com",
            "subject": "Billing inquiry about invoice",
            "category": "billing",
            "description": "Can you clarify the line item breakdown?",
        })
        tkt = create_res.json()
        assert tkt["status"] == "open"

        # Operator writes custom response
        reply_res = await ac.post(f"/api/system/tickets/{tkt['id']}/reply", json={
            "body": "Hello, here is the detailed breakdown of your invoice line items. Let us know if you need anything else.",
            "status": "resolved",
        })
        assert reply_res.status_code == 200
        data = reply_res.json()
        assert data["status"] == "resolved"
        assert data["resolution_path"] == "MANUAL_OPERATOR_RESOLVE"
        assert "breakdown" in data["resolution_summary"]


@pytest.mark.asyncio
async def test_background_workflow_exception_handling():
    """
    Verifies that if an error occurs during background workflow execution,
    the background worker catches it safely and marks the ticket as 'escalated'.
    """
    from app.api.routes_system_record import run_workflow_background
    import unittest.mock as mock

    # Create a test ticket in DB
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        res = await ac.post("/api/system/tickets", json={
            "customer_email": "test_err@example.com",
            "subject": "Error Isolation Test",
            "category": "technical",
            "description": "Trigger simulated error test.",
        })
        tkt_id = res.json()["id"]

    # Mock WorkflowRunner to raise a runtime exception
    with mock.patch("app.workflow.graph.WorkflowRunner.process_ticket", side_effect=RuntimeError("Simulated LLM Connection Failure")):
        await run_workflow_background(
            ticket_id=tkt_id,
            customer_email="test_err@example.com",
            subject="Error Isolation Test",
            description="Trigger simulated error test.",
        )

    # Verify ticket was safely escalated
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        tkt_res = await ac.get(f"/api/system/tickets/{tkt_id}")
        assert tkt_res.status_code == 200
        assert tkt_res.json()["status"] == "escalated"
