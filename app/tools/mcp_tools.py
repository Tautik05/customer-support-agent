import json
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional
from sqlalchemy import desc, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from app.db.database import AsyncSessionLocal
from app.db.models import Customer, Order, Payment, Refund, Subscription, SupportTicket
from app.utils import utc_now

logger = logging.getLogger("support_agent.tools.mcp")

class MCPTools:
    """
    Model Context Protocol (MCP) tool implementations for customer support operations.
    Standardized tool definitions separating reasoning from business storage.
    """

    @staticmethod
    async def get_customer(identifier: str) -> Dict[str, Any]:
        """
        MCP Tool: Retrieve customer profile, subscriptions, orders, and payment history.
        identifier: Can be customer ID (e.g. 'cust_101') or email (e.g. 'alice@example.com').
        """
        async with AsyncSessionLocal() as session:
            query = select(Customer).where(
                or_(Customer.id == identifier, Customer.email.ilike(identifier.strip()))
            )
            result = await session.execute(query)
            customer = result.scalars().first()
            if not customer:
                return {
                    "found": False,
                    "error": f"Customer '{identifier}' not found in system of record.",
                }

            # Related records
            subs = (await session.execute(select(Subscription).where(Subscription.customer_id == customer.id))).scalars().all()
            orders = (await session.execute(select(Order).where(Order.customer_id == customer.id).order_by(desc(Order.created_at)))).scalars().all()
            payments = (await session.execute(select(Payment).where(Payment.customer_id == customer.id).order_by(desc(Payment.created_at)))).scalars().all()
            refunds = (await session.execute(select(Refund).where(Refund.customer_id == customer.id).order_by(desc(Refund.created_at)))).scalars().all()

            return {
                "found": True,
                "customer": customer.to_dict(),
                "subscriptions": [s.to_dict() for s in subs],
                "orders": [o.to_dict() for o in orders],
                "payments": [p.to_dict() for p in payments],
                "refunds": [r.to_dict() for r in refunds],
            }

    @staticmethod
    async def get_order(order_id_or_number: str) -> Dict[str, Any]:
        """
        MCP Tool: Retrieve order details, line items, status, tracking and payment by ID or order number.
        """
        async with AsyncSessionLocal() as session:
            query = select(Order).where(
                or_(Order.id == order_id_or_number, Order.order_number.ilike(order_id_or_number.strip()))
            )
            result = await session.execute(query)
            order = result.scalars().first()
            if not order:
                return {"found": False, "error": f"Order '{order_id_or_number}' not found."}

            # Payments for this order
            payments = (await session.execute(select(Payment).where(Payment.order_id == order.id))).scalars().all()

            return {
                "found": True,
                "order": order.to_dict(),
                "payments": [p.to_dict() for p in payments],
            }

    @staticmethod
    async def get_subscription(subscription_id_or_customer_id: str) -> Dict[str, Any]:
        """
        MCP Tool: Retrieve subscription information by subscription ID or customer ID.
        """
        async with AsyncSessionLocal() as session:
            query = select(Subscription).where(
                or_(
                    Subscription.id == subscription_id_or_customer_id,
                    Subscription.customer_id == subscription_id_or_customer_id,
                )
            )
            result = await session.execute(query)
            subs = result.scalars().all()
            if not subs:
                return {"found": False, "error": f"No subscription found for '{subscription_id_or_customer_id}'."}

            return {
                "found": True,
                "subscriptions": [s.to_dict() for s in subs],
            }

    @staticmethod
    async def get_payments(customer_id: str) -> Dict[str, Any]:
        """
        MCP Tool: Retrieve complete payment transaction history for a customer.
        """
        async with AsyncSessionLocal() as session:
            query = select(Payment).where(Payment.customer_id == customer_id).order_by(desc(Payment.created_at))
            result = await session.execute(query)
            payments = result.scalars().all()
            return {
                "customer_id": customer_id,
                "count": len(payments),
                "payments": [p.to_dict() for p in payments],
            }

    @staticmethod
    async def create_refund(
        payment_id: str,
        amount: float,
        reason: str,
        approved_by: str = "human_supervisor",
    ) -> Dict[str, Any]:
        """
        MCP Tool: Consequential action to execute a refund against a payment in the system of record.
        """
        async with AsyncSessionLocal() as session:
            query = select(Payment).where(Payment.id == payment_id)
            result = await session.execute(query)
            payment = result.scalars().first()
            if not payment:
                return {"success": False, "error": f"Payment '{payment_id}' not found."}

            if payment.status == "refunded":
                return {"success": False, "error": f"Payment '{payment_id}' has already been refunded."}

            refund_id = f"ref_{int(utc_now().timestamp()*1000)}"
            refund = Refund(
                id=refund_id,
                payment_id=payment.id,
                customer_id=payment.customer_id,
                amount=amount,
                currency=payment.currency,
                reason=reason,
                status="processed",
                approved_by=approved_by,
                created_at=utc_now(),
                processed_at=utc_now(),
            )

            if amount >= payment.amount:
                payment.status = "refunded"
            else:
                payment.status = "partially_refunded"

            session.add(refund)
            await session.commit()
            await session.refresh(refund)
            await session.refresh(payment)

            logger.info(f"MCP create_refund executed: ${amount:.2f} refunded for payment {payment_id}")
            return {
                "success": True,
                "refund": refund.to_dict(),
                "payment": payment.to_dict(),
                "message": f"Successfully refunded ${amount:.2f} {payment.currency} for transaction {payment.transaction_ref}.",
            }

    @staticmethod
    async def cancel_subscription(
        subscription_id: str,
        immediate: bool = False,
        reason: str = "Customer requested cancellation",
    ) -> Dict[str, Any]:
        """
        MCP Tool: Cancel an active customer subscription.
        """
        async with AsyncSessionLocal() as session:
            query = select(Subscription).where(Subscription.id == subscription_id)
            result = await session.execute(query)
            sub = result.scalars().first()
            if not sub:
                return {"success": False, "error": f"Subscription '{subscription_id}' not found."}

            if immediate:
                sub.status = "cancelled"
            else:
                sub.cancel_at_period_end = True

            await session.commit()
            await session.refresh(sub)
            return {
                "success": True,
                "subscription": sub.to_dict(),
                "message": f"Subscription {subscription_id} updated. Cancel status: {sub.status}, Cancel at period end: {sub.cancel_at_period_end}",
            }

    @staticmethod
    async def update_ticket(
        ticket_id: str,
        status: str,
        resolution_summary: str,
        resolution_path: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        MCP Tool: Update ticket state, resolution summary, and execution trace in system of record.
        """
        async with AsyncSessionLocal() as session:
            query = select(SupportTicket).where(SupportTicket.id == ticket_id)
            result = await session.execute(query)
            ticket = result.scalars().first()
            if not ticket:
                return {"success": False, "error": f"Ticket '{ticket_id}' not found."}

            ticket.status = status
            ticket.resolution_summary = resolution_summary
            if resolution_path:
                ticket.resolution_path = resolution_path
            if metadata:
                curr = ticket.metadata_dict
                curr.update(metadata)
                ticket.metadata_json = json.dumps(curr)

            ticket.updated_at = utc_now()
            await session.commit()
            await session.refresh(ticket)
            return {"success": True, "ticket": ticket.to_dict()}

    @staticmethod
    async def send_email(
        to_email: str,
        subject: str,
        body: str,
        ticket_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        MCP Tool: Dispatch simulated email notification to the customer.
        """
        logger.info(f"MCP send_email to [{to_email}] Subject: '{subject}'\nBody:\n{body}")
        return {
            "success": True,
            "to": to_email,
            "subject": subject,
            "body": body,
            "ticket_id": ticket_id,
            "dispatched_at": utc_now().isoformat(),
            "status": "delivered",
        }
