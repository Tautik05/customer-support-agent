import pytest
from httpx import AsyncClient, ASGITransport
from app.main import app
from app.utils import utc_now

@pytest.mark.asyncio
async def test_health():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        response = await ac.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"

@pytest.mark.asyncio
async def test_get_customer_with_duplicate_charges():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        # Fetch Alice Smith (cust_101)
        response = await ac.get("/api/system/customers/cust_101")
        assert response.status_code == 200
        data = response.json()
        assert data["email"] == "alice@example.com"
        assert len(data["subscriptions"]) >= 1
        assert len(data["payments"]) >= 2
        
        # Verify duplicate charge scenario in ground truth
        payments = data["payments"]
        sub_payments = [p for p in payments if p["subscription_id"] == "sub_101"]
        assert len(sub_payments) >= 2
        assert sub_payments[0]["amount"] == 49.00
        assert sub_payments[1]["amount"] == 49.00

@pytest.mark.asyncio
async def test_get_order_cases():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        # Case 1: Bob Jones (recent delivered order, eligible for return/refund)
        res_bob = await ac.get("/api/system/orders/ord_201")
        assert res_bob.status_code == 200
        assert res_bob.json()["status"] == "delivered"
        assert res_bob.json()["total_amount"] == 89.99

        # Case 2: Charlie Brown (80 days old order, outside 30 day window)
        res_charlie = await ac.get("/api/system/orders/ord_301")
        assert res_charlie.status_code == 200
        assert res_charlie.json()["order_number"] == "ORD-2026-1184"

        # Case 3: Diana Prince (in transit)
        res_diana = await ac.get("/api/system/orders/ord_401")
        assert res_diana.status_code == 200
        assert res_diana.json()["status"] == "in_transit"

@pytest.mark.asyncio
async def test_create_and_update_ticket():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        # Create ticket
        new_ticket = {
            "customer_email": "alice@example.com",
            "subject": "Test Duplicate Charge Ticket",
            "description": "I got billed twice for Pro plan.",
            "category": "billing",
            "priority": "high",
        }
        res = await ac.post("/api/system/tickets", json=new_ticket)
        assert res.status_code == 200
        tkt = res.json()
        assert tkt["customer_id"] == "cust_101"
        assert tkt["status"] == "open"


        # Update ticket
        update_data = {
            "status": "resolved",
            "resolution_path": "ACTION_APPROVED",
            "resolution_summary": "Refund of $49.00 processed for duplicate payment pay_102",
        }
        patch_res = await ac.patch(f"/api/system/tickets/{tkt['id']}", json=update_data)
        assert patch_res.status_code == 200
        updated = patch_res.json()
        assert updated["status"] == "resolved"
        assert updated["resolution_path"] == "ACTION_APPROVED"

@pytest.mark.asyncio
async def test_create_refund_execution():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        # Create a new payment to test refunding idempotently
        new_pay = {
            "id": f"pay_test_{int(utc_now().timestamp()*1000)}",
            "customer_id": "cust_105",
            "amount": 29.00,
            "currency": "USD",
            "payment_method": "credit_card",
            "transaction_ref": f"txn_test_{int(utc_now().timestamp()*1000)}",
            "description": "Test payment for refund verification"
        }
        # Look up cust_105
        cust_res = await ac.get("/api/system/customers/cust_105")
        assert cust_res.status_code == 200

        refund_req = {
            "payment_id": "pay_501",
            "customer_id": "cust_105",
            "amount": 29.00,
            "reason": "Test subscription refund",
            "approved_by": "human_supervisor",
        }
        res = await ac.post("/api/system/refunds", json=refund_req)
        # 200 if fresh, 400 if already refunded earlier
        assert res.status_code in [200, 400]
        if res.status_code == 200:
            data = res.json()
            assert data["success"] is True
            assert data["payment"]["status"] in ["refunded", "partially_refunded"]
            assert data["refund"]["amount"] == 29.00
