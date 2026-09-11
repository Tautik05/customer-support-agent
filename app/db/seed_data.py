import json
import logging
from datetime import datetime, timedelta
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.db.models import Customer, Subscription, Order, Payment, Refund, SupportTicket
from app.db.database import AsyncSessionLocal, init_db
from app.utils import utc_now

logger = logging.getLogger("support_agent.seed")

async def seed_database(session: AsyncSession = None) -> dict:
    """Seeds the database with realistic ground-truth support records."""
    close_session = False
    if session is None:
        session = AsyncSessionLocal()
        close_session = True

    try:
        # Check if already seeded
        result = await session.execute(select(Customer))
        existing_customers = result.scalars().all()
        if existing_customers:
            logger.info(f"Database already contains {len(existing_customers)} customers. Re-seeding clean dataset...")
            # Clean existing records
            for model in [Refund, SupportTicket, Payment, Order, Subscription, Customer]:
                await session.execute(model.__table__.delete())
            await session.commit()
            session.expunge_all()

        now = utc_now()

        # ==========================================
        # 1. Customers
        # ==========================================
        c1 = Customer(
            id="cust_101",
            name="Alice Smith",
            email="alice@example.com",
            phone="+1-555-0101",
            tier="Standard",
            status="active",
            created_at=now - timedelta(days=180),
        )
        c2 = Customer(
            id="cust_102",
            name="Bob Jones",
            email="bob@example.com",
            phone="+1-555-0102",
            tier="Standard",
            status="active",
            created_at=now - timedelta(days=90),
        )
        c3 = Customer(
            id="cust_103",
            name="Charlie Brown",
            email="charlie@example.com",
            phone="+1-555-0103",
            tier="Standard",
            status="active",
            created_at=now - timedelta(days=200),
        )
        c4 = Customer(
            id="cust_104",
            name="Diana Prince",
            email="diana@example.com",
            phone="+1-555-0104",
            tier="Standard",
            status="active",
            created_at=now - timedelta(days=60),
        )
        c5 = Customer(
            id="cust_105",
            name="Evan Wright",
            email="evan@example.com",
            phone="+1-555-0105",
            tier="Standard",
            status="active",
            created_at=now - timedelta(days=45),
        )
        c6 = Customer(
            id="cust_106",
            name="Fiona Gallagher",
            email="fiona@example.com",
            phone="+1-555-0106",
            tier="Enterprise",
            status="active",
            created_at=now - timedelta(days=365),
        )
        c7 = Customer(
            id="cust_107",
            name="George Miller",
            email="george@example.com",
            phone="+1-555-0107",
            tier="Free",
            status="active",
            created_at=now - timedelta(days=10),
        )

        session.add_all([c1, c2, c3, c4, c5, c6, c7])
        await session.flush()

        # ==========================================
        # 2. Subscriptions
        # ==========================================
        sub_alice = Subscription(
            id="sub_101",
            customer_id="cust_101",
            plan_name="Pro Monthly",
            status="active",
            amount=49.00,
            currency="USD",
            billing_cycle="monthly",
            current_period_start=now - timedelta(days=1),
            current_period_end=now + timedelta(days=29),
            cancel_at_period_end=False,
            created_at=now - timedelta(days=180),
        )
        sub_evan = Subscription(
            id="sub_501",
            customer_id="cust_105",
            plan_name="Starter Monthly",
            status="active",
            amount=29.00,
            currency="USD",
            billing_cycle="monthly",
            current_period_start=now - timedelta(days=15),
            current_period_end=now + timedelta(days=15),
            cancel_at_period_end=False,
            created_at=now - timedelta(days=45),
        )
        sub_fiona = Subscription(
            id="sub_601",
            customer_id="cust_106",
            plan_name="Enterprise Dedicated Cloud",
            status="active",
            amount=999.00,
            currency="USD",
            billing_cycle="monthly",
            current_period_start=now - timedelta(days=5),
            current_period_end=now + timedelta(days=25),
            cancel_at_period_end=False,
            created_at=now - timedelta(days=365),
        )

        session.add_all([sub_alice, sub_evan, sub_fiona])
        await session.flush()

        # ==========================================
        # 3. Orders
        # ==========================================
        # Bob Jones: Refund-eligible recent order (4 days ago, delivered 2 days ago)
        ord_bob = Order(
            id="ord_201",
            customer_id="cust_102",
            order_number="ORD-2026-9021",
            status="delivered",
            total_amount=89.99,
            currency="USD",
            items_json=json.dumps([
                {"sku": "SKU-HEADPHONE-01", "name": "Wireless Noise Cancelling Headphones", "quantity": 1, "price": 89.99}
            ]),
            shipping_address="742 Evergreen Terrace, Springfield, OR 97477",
            tracking_number="TRK-FEDEX-882910",
            created_at=now - timedelta(days=4),
            delivered_at=now - timedelta(days=2),
        )

        # Charlie Brown: Expired refund window (80 days ago)
        ord_charlie = Order(
            id="ord_301",
            customer_id="cust_103",
            order_number="ORD-2026-1184",
            status="delivered",
            total_amount=149.00,
            currency="USD",
            items_json=json.dumps([
                {"sku": "SKU-JACKET-03", "name": "Leather Winter Bomber Jacket", "quantity": 1, "price": 149.00}
            ]),
            shipping_address="123 Peanuts Lane, Minneapolis, MN 55401",
            tracking_number="TRK-UPS-392019",
            created_at=now - timedelta(days=80),
            delivered_at=now - timedelta(days=75),
        )

        # Diana Prince: Delayed / Lost in transit
        ord_diana = Order(
            id="ord_401",
            customer_id="cust_104",
            order_number="ORD-2026-7732",
            status="in_transit",
            total_amount=199.00,
            currency="USD",
            items_json=json.dumps([
                {"sku": "SKU-PURIFIER-09", "name": "Smart HEPA Air Purifier Pro", "quantity": 1, "price": 199.00}
            ]),
            shipping_address="1400 Defense Hwy, Arlington, VA 22202",
            tracking_number="TRK-USPS-992011",
            created_at=now - timedelta(days=12),
            delivered_at=None,
        )

        session.add_all([ord_bob, ord_charlie, ord_diana])
        await session.flush()

        # ==========================================
        # 4. Payments (Ground Truth for duplicate charges and refunds)
        # ==========================================
        # Alice Smith: DUPLICATE CHARGES on sub_101
        pay_alice_1 = Payment(
            id="pay_101",
            customer_id="cust_101",
            subscription_id="sub_101",
            amount=49.00,
            currency="USD",
            status="succeeded",
            payment_method="credit_card (Visa ...4242)",
            transaction_ref="txn_alice_sub_sep_01",
            description="Monthly subscription renewal: Pro Monthly",
            created_at=now - timedelta(hours=24, minutes=15),
        )
        pay_alice_2 = Payment(
            id="pay_102",
            customer_id="cust_101",
            subscription_id="sub_101",
            amount=49.00,
            currency="USD",
            status="succeeded",
            payment_method="credit_card (Visa ...4242)",
            transaction_ref="txn_alice_sub_sep_02_DUP",
            description="Monthly subscription renewal: Pro Monthly (Duplicate Charge)",
            created_at=now - timedelta(hours=24, minutes=3),  # 12 minutes later
        )

        # Bob Jones: Single payment for Order 201
        pay_bob = Payment(
            id="pay_201",
            customer_id="cust_102",
            order_id="ord_201",
            amount=89.99,
            currency="USD",
            status="succeeded",
            payment_method="credit_card (Mastercard ...8831)",
            transaction_ref="txn_bob_ord_201",
            description="Payment for Order ORD-2026-9021",
            created_at=now - timedelta(days=4),
        )

        # Charlie Brown: Payment for Order 301
        pay_charlie = Payment(
            id="pay_301",
            customer_id="cust_103",
            order_id="ord_301",
            amount=149.00,
            currency="USD",
            status="succeeded",
            payment_method="paypal (charlie@example.com)",
            transaction_ref="txn_charlie_ord_301",
            description="Payment for Order ORD-2026-1184",
            created_at=now - timedelta(days=80),
        )

        # Diana Prince: Payment for Order 401
        pay_diana = Payment(
            id="pay_401",
            customer_id="cust_104",
            order_id="ord_401",
            amount=199.00,
            currency="USD",
            status="succeeded",
            payment_method="apple_pay",
            transaction_ref="txn_diana_ord_401",
            description="Payment for Order ORD-2026-7732",
            created_at=now - timedelta(days=12),
        )

        # Evan Wright: Subscription payment
        pay_evan = Payment(
            id="pay_501",
            customer_id="cust_105",
            subscription_id="sub_501",
            amount=29.00,
            currency="USD",
            status="succeeded",
            payment_method="credit_card (Visa ...1004)",
            transaction_ref="txn_evan_sub_501",
            description="Monthly subscription renewal: Starter Monthly",
            created_at=now - timedelta(days=15),
        )

        # Fiona Gallagher: Enterprise payment
        pay_fiona = Payment(
            id="pay_601",
            customer_id="cust_106",
            subscription_id="sub_601",
            amount=999.00,
            currency="USD",
            status="succeeded",
            payment_method="wire_transfer",
            transaction_ref="txn_fiona_sub_601",
            description="Enterprise Dedicated Cloud Subscription",
            created_at=now - timedelta(days=5),
        )

        session.add_all([pay_alice_1, pay_alice_2, pay_bob, pay_charlie, pay_diana, pay_evan, pay_fiona])
        await session.flush()

        # ==========================================
        # 5. Example Initial Tickets for Reference
        # ==========================================
        tkt_alice = SupportTicket(
            id="tkt_101",
            customer_id="cust_101",
            customer_email="alice@example.com",
            subject="Double charge on my monthly subscription",
            description="I was charged twice for my subscription yesterday ($49.00 each). Please refund the duplicate payment.",
            category="billing",
            status="open",
            priority="high",
            resolution_path=None,
            resolution_summary=None,
            metadata_json=json.dumps({"source": "email", "sentiment": "frustrated"}),
            created_at=now - timedelta(hours=2),
        )

        tkt_bob = SupportTicket(
            id="tkt_102",
            customer_id="cust_102",
            customer_email="bob@example.com",
            subject="Damaged headphones received in order ORD-2026-9021",
            description="Hi, I received my noise cancelling headphones yesterday but the right ear cup is broken and does not power on. I would like a refund or replacement.",
            category="shipping",
            status="open",
            priority="medium",
            resolution_path=None,
            resolution_summary=None,
            metadata_json=json.dumps({"source": "web_form"}),
            created_at=now - timedelta(hours=5),
        )

        tkt_charlie = SupportTicket(
            id="tkt_103",
            customer_id="cust_103",
            customer_email="charlie@example.com",
            subject="Refund request for jacket bought in June (ORD-2026-1184)",
            description="I bought a winter jacket a couple of months ago but never wore it. I want to return it for a full refund of $149.",
            category="billing",
            status="open",
            priority="low",
            resolution_path=None,
            resolution_summary=None,
            metadata_json=json.dumps({"source": "web_form"}),
            created_at=now - timedelta(hours=8),
        )

        session.add_all([tkt_alice, tkt_bob, tkt_charlie])
        await session.commit()

        summary = {
            "customers": 7,
            "subscriptions": 3,
            "orders": 3,
            "payments": 7,
            "refunds": 0,
            "tickets": 3,
            "status": "success",
            "message": "Realistic seed data successfully populated with duplicate charges, eligible refunds, and edge cases."
        }
        logger.info(f"Database seeded successfully: {summary}")
        return summary

    finally:
        if close_session:
            await session.close()

if __name__ == "__main__":
    import asyncio
    async def main():
        await init_db()
        res = await seed_database()
        print("Seed result:", res)
    asyncio.run(main())
