import json
import logging
import traceback
from datetime import datetime
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import desc, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from app.db.database import get_db, init_db
from app.db.models import Customer, Order, Payment, Refund, Subscription, SupportTicket
from app.db.seed_data import seed_database
from app.tools.mcp_tools import MCPTools
from app.utils import utc_now
from app.workflow.graph import WorkflowRunner

logger = logging.getLogger("support_agent.api.system_record")

async def run_workflow_background(
    ticket_id: str,
    customer_email: str,
    subject: str,
    description: str,
    customer_id: Optional[str] = None,
):
    """
    Executes the LangGraph AI workflow asynchronously via FastAPI BackgroundTasks.
    Handles exceptions safely by escalating the ticket and recording error logs.
    """
    logger.info(f"Background task starting AI workflow for ticket {ticket_id}")
    try:
        result = await WorkflowRunner.process_ticket(
            ticket_id=ticket_id,
            customer_email=customer_email,
            subject=subject,
            description=description,
            customer_id=customer_id,
        )
        is_interrupted = result.get("is_interrupted", False)
        state = result.get("state", {})
        if is_interrupted:
            logger.info(f"Ticket {ticket_id} paused at human approval checkpoint in background")
            await MCPTools.update_ticket(
                ticket_id=ticket_id,
                status="pending_approval",
                resolution_summary="Proposed consequential action is awaiting supervisor authorization.",
                resolution_path="PROPOSE_ACTION_APPROVAL",
                metadata={
                    "classification": state.get("classification"),
                    "entities": state.get("entities"),
                    "rules": state.get("rules_evaluation"),
                    "proposed_action": state.get("proposed_action"),
                    "original_proposed_action": state.get("original_proposed_action"),
                    "response_draft": state.get("response_draft"),
                    "audit_logs": state.get("audit_logs", []),
                },
            )
        else:
            logger.info(f"Ticket {ticket_id} background workflow completed successfully.")

    except Exception as exc:
        logger.error(f"Error during background AI workflow execution for ticket {ticket_id}: {exc}", exc_info=True)
        # Safely record failure and escalate ticket
        error_details = {
            "error_message": str(exc),
            "traceback": traceback.format_exc(),
            "timestamp": utc_now().isoformat(),
        }
        await MCPTools.update_ticket(
            ticket_id=ticket_id,
            status="escalated",
            resolution_summary="An error occurred during automated AI resolution. Escalated to support specialist for manual review.",
            resolution_path="ESCALATED",
            metadata={"system_error": error_details},
        )

router = APIRouter(prefix="/api/system", tags=["System of Record"])

# ==========================================
# Pydantic Schemas
# ==========================================
class CustomerCreate(BaseModel):
    id: Optional[str] = None
    name: str
    email: EmailStr
    phone: Optional[str] = None
    tier: str = "Standard"

class OrderCreate(BaseModel):
    id: Optional[str] = None
    customer_id: str
    order_number: str
    status: str = "delivered"
    total_amount: float
    currency: str = "USD"
    items: List[Dict[str, Any]] = Field(default_factory=list)
    shipping_address: Optional[str] = None
    tracking_number: Optional[str] = None

class SubscriptionCreate(BaseModel):
    id: Optional[str] = None
    customer_id: str
    plan_name: str
    status: str = "active"
    amount: float
    currency: str = "USD"
    billing_cycle: str = "monthly"

class PaymentCreate(BaseModel):
    id: Optional[str] = None
    customer_id: str
    order_id: Optional[str] = None
    subscription_id: Optional[str] = None
    amount: float
    currency: str = "USD"
    payment_method: str = "credit_card"
    transaction_ref: str
    description: Optional[str] = None

class RefundRequest(BaseModel):
    payment_id: str
    customer_id: str
    amount: float
    reason: str
    approved_by: str = "system"

class TicketCreate(BaseModel):
    id: Optional[str] = None
    customer_email: EmailStr
    customer_id: Optional[str] = None
    subject: str
    description: str
    category: str = "general"
    priority: str = "medium"
    metadata: Optional[Dict[str, Any]] = None

class TicketUpdate(BaseModel):
    status: Optional[str] = None
    priority: Optional[str] = None
    resolution_path: Optional[str] = None
    resolution_summary: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None

# ==========================================
# Seed & Status Endpoints
# ==========================================
@router.post("/seed", summary="Reset and seed system of record with realistic data")
async def seed_data(db: AsyncSession = Depends(get_db)):
    result = await seed_database(db)
    return result

# ==========================================
# Customers
# ==========================================
@router.get("/customers", summary="List all customers or search by email/ID")
async def list_customers(
    search: Optional[str] = Query(None, description="Search by name, email or ID"),
    db: AsyncSession = Depends(get_db),
):
    query = select(Customer)
    if search:
        search_pattern = f"%{search}%"
        query = query.where(
            or_(
                Customer.id.ilike(search_pattern),
                Customer.email.ilike(search_pattern),
                Customer.name.ilike(search_pattern),
            )
        )
    result = await db.execute(query)
    customers = result.scalars().all()
    return [c.to_dict() for c in customers]

@router.get("/customers/{customer_id}", summary="Get customer details with subscriptions, orders, and payments")
async def get_customer(customer_id: str, db: AsyncSession = Depends(get_db)):
    query = select(Customer).where(
        or_(Customer.id == customer_id, Customer.email == customer_id)
    )
    result = await db.execute(query)
    customer = result.scalars().first()
    if not customer:
        if "@" in customer_id:
            # Return guest/placeholder profile for unseeded customers
            name_guess = customer_id.split('@')[0].replace('.', ' ').replace('_', ' ').title()
            return {
                "id": "guest",
                "name": name_guess,
                "email": customer_id,
                "tier": "Standard",
                "created_at": utc_now().isoformat(),
                "subscriptions": [],
                "orders": [],
                "payments": [],
                "refunds": [],
            }
        raise HTTPException(status_code=404, detail="Customer not found")

    # Fetch related records
    subs = (await db.execute(select(Subscription).where(Subscription.customer_id == customer.id))).scalars().all()
    orders = (await db.execute(select(Order).where(Order.customer_id == customer.id))).scalars().all()
    payments = (await db.execute(select(Payment).where(Payment.customer_id == customer.id))).scalars().all()
    refunds = (await db.execute(select(Refund).where(Refund.customer_id == customer.id))).scalars().all()

    data = customer.to_dict()
    data["subscriptions"] = [s.to_dict() for s in subs]
    data["orders"] = [o.to_dict() for o in orders]
    data["payments"] = [p.to_dict() for p in payments]
    data["refunds"] = [r.to_dict() for r in refunds]
    return data

# ==========================================
# Orders
# ==========================================
@router.get("/orders", summary="List orders with optional customer filter")
async def list_orders(customer_id: Optional[str] = None, db: AsyncSession = Depends(get_db)):
    query = select(Order).order_by(desc(Order.created_at))
    if customer_id:
        query = query.where(Order.customer_id == customer_id)
    result = await db.execute(query)
    orders = result.scalars().all()
    return [o.to_dict() for o in orders]

@router.get("/orders/{order_id_or_number}", summary="Get order by ID or order number")
async def get_order(order_id_or_number: str, db: AsyncSession = Depends(get_db)):
    query = select(Order).where(
        or_(Order.id == order_id_or_number, Order.order_number == order_id_or_number)
    )
    result = await db.execute(query)
    order = result.scalars().first()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    return order.to_dict()

# ==========================================
# Subscriptions
# ==========================================
@router.get("/subscriptions", summary="List subscriptions with optional customer filter")
async def list_subscriptions(customer_id: Optional[str] = None, db: AsyncSession = Depends(get_db)):
    query = select(Subscription)
    if customer_id:
        query = query.where(Subscription.customer_id == customer_id)
    result = await db.execute(query)
    subs = result.scalars().all()
    return [s.to_dict() for s in subs]

# ==========================================
# Payments & Refunds
# ==========================================
@router.get("/payments", summary="List payments with optional customer filter")
async def list_payments(customer_id: Optional[str] = None, db: AsyncSession = Depends(get_db)):
    query = select(Payment).order_by(desc(Payment.created_at))
    if customer_id:
        query = query.where(Payment.customer_id == customer_id)
    result = await db.execute(query)
    payments = result.scalars().all()
    return [p.to_dict() for p in payments]

@router.get("/payments/{payment_id}", summary="Get payment by ID")
async def get_payment(payment_id: str, db: AsyncSession = Depends(get_db)):
    query = select(Payment).where(Payment.id == payment_id)
    result = await db.execute(query)
    pay = result.scalars().first()
    if not pay:
        raise HTTPException(status_code=404, detail="Payment not found")
    return pay.to_dict()

@router.post("/refunds", summary="Create and execute a refund for a payment")
async def create_refund(payload: RefundRequest, db: AsyncSession = Depends(get_db)):
    # Verify payment exists
    query = select(Payment).where(Payment.id == payload.payment_id)
    result = await db.execute(query)
    payment = result.scalars().first()
    if not payment:
        raise HTTPException(status_code=404, detail="Target payment not found")

    if payment.status == "refunded":
        raise HTTPException(status_code=400, detail="Payment has already been fully refunded")

    # Generate refund ID
    refund_id = f"ref_{int(utc_now().timestamp()*1000)}"
    refund = Refund(
        id=refund_id,
        payment_id=payment.id,
        customer_id=payload.customer_id,
        amount=payload.amount,
        currency=payment.currency,
        reason=payload.reason,
        status="processed",
        approved_by=payload.approved_by,
        created_at=utc_now(),
        processed_at=utc_now(),
    )

    # Update payment status
    if payload.amount >= payment.amount:
        payment.status = "refunded"
    else:
        payment.status = "partially_refunded"

    db.add(refund)
    await db.commit()
    await db.refresh(refund)
    return {
        "success": True,
        "refund": refund.to_dict(),
        "payment": payment.to_dict(),
        "message": f"Successfully processed refund of ${payload.amount:.2f} for payment {payment.id}",
    }

@router.get("/refunds", summary="List all processed refunds")
async def list_refunds(customer_id: Optional[str] = None, db: AsyncSession = Depends(get_db)):
    query = select(Refund).order_by(desc(Refund.created_at))
    if customer_id:
        query = query.where(Refund.customer_id == customer_id)
    result = await db.execute(query)
    refunds = result.scalars().all()
    return [r.to_dict() for r in refunds]

# ==========================================
# Support Tickets
# ==========================================
@router.get("/tickets", summary="List support tickets")
async def list_tickets(
    status: Optional[str] = None,
    customer_id: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
):
    query = select(SupportTicket).order_by(desc(SupportTicket.created_at))
    if status:
        query = query.where(SupportTicket.status == status)
    if customer_id:
        query = query.where(SupportTicket.customer_id == customer_id)
    result = await db.execute(query)
    tickets = result.scalars().all()
    return [t.to_dict() for t in tickets]

@router.get("/tickets/{ticket_id}", summary="Get ticket by ID")
async def get_ticket(ticket_id: str, db: AsyncSession = Depends(get_db)):
    query = select(SupportTicket).where(SupportTicket.id == ticket_id)
    result = await db.execute(query)
    ticket = result.scalars().first()
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found")
    return ticket.to_dict()

@router.post("/tickets", summary="Create a new support ticket and schedule background AI workflow")
async def create_ticket(
    payload: TicketCreate,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    # Look up customer if not provided
    customer_id = payload.customer_id
    if not customer_id:
        clean_email = payload.customer_email.strip().lower()
        cust_query = select(Customer).where(Customer.email.ilike(clean_email))
        cust_res = await db.execute(cust_query)
        cust = cust_res.scalars().first()
        if cust:
            customer_id = cust.id
        else:
            try:
                # Auto-register guest customer into database
                customer_id = f"cust_{int(utc_now().timestamp()*1000)}"
                name_guess = clean_email.split('@')[0].replace('.', ' ').replace('_', ' ').title()
                new_cust = Customer(
                    id=customer_id,
                    name=name_guess,
                    email=clean_email,
                    tier="Standard",
                    created_at=utc_now(),
                )
                db.add(new_cust)
                await db.flush()
            except Exception:
                await db.rollback()
                # Re-query in case it was inserted concurrently
                retry_res = await db.execute(select(Customer).where(Customer.email.ilike(clean_email)))
                found = retry_res.scalars().first()
                if found:
                    customer_id = found.id

    category_lower = (payload.category or "").lower().strip()
    is_billing = category_lower in ["billing", "billing & subscriptions", "billing & subscription", "subscription", "subscriptions"]

    ticket_id = payload.id or f"tkt_{int(utc_now().timestamp()*1000)}"
    ticket = SupportTicket(
        id=ticket_id,
        customer_id=customer_id,
        customer_email=payload.customer_email,
        subject=payload.subject,
        description=payload.description,
        category=payload.category,
        status="open" if is_billing else "in_progress",
        priority=payload.priority,
        metadata_json=json.dumps(payload.metadata or {}),
        created_at=utc_now(),
    )
    db.add(ticket)
    await db.commit()
    await db.refresh(ticket)

    # Schedule asynchronous LangGraph AI workflow in background ONLY for non-billing categories
    # Billing & Subscriptions category pauses automation and allows operator to choose AI review or manual reply
    if not is_billing:
        background_tasks.add_task(
            run_workflow_background,
            ticket_id=ticket.id,
            customer_email=ticket.customer_email,
            subject=ticket.subject,
            description=ticket.description,
            customer_id=customer_id,
        )

    return ticket.to_dict()

class TicketManualReplyRequest(BaseModel):
    subject: Optional[str] = None
    body: str
    status: str = "resolved"

@router.post("/tickets/{ticket_id}/reply", summary="Operator sends manual custom response to customer and updates ticket")
async def send_manual_ticket_reply(
    ticket_id: str,
    payload: TicketManualReplyRequest,
    db: AsyncSession = Depends(get_db),
):
    ticket_query = select(SupportTicket).where(SupportTicket.id == ticket_id)
    result = await db.execute(ticket_query)
    ticket = result.scalars().first()
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found")

    email_subject = payload.subject or f"Update on Ticket #{ticket_id}: {ticket.subject}"
    
    # Dispatch email via MCP tool
    await MCPTools.send_email(
        to_email=ticket.customer_email,
        subject=email_subject,
        body=payload.body,
        ticket_id=ticket_id,
    )

    # Update ticket in DB
    ticket.status = payload.status
    ticket.resolution_path = "MANUAL_OPERATOR_RESOLVE"
    ticket.resolution_summary = payload.body
    
    curr_meta = ticket.metadata_dict
    curr_meta["sent_email"] = {
        "to": ticket.customer_email,
        "subject": email_subject,
        "body": payload.body,
        "timestamp": utc_now().isoformat(),
        "from": "NovaDesk Support <support@novadesk.ai>",
        "type": "operator_manual_reply"
    }
    curr_meta["final_response"] = {
        "subject": email_subject,
        "body": payload.body,
    }
    ticket.metadata_json = json.dumps(curr_meta)
    ticket.updated_at = utc_now()
    
    await db.commit()
    await db.refresh(ticket)
    return ticket.to_dict()

@router.patch("/tickets/{ticket_id}", summary="Update ticket state / resolution summary")
async def update_ticket(ticket_id: str, payload: TicketUpdate, db: AsyncSession = Depends(get_db)):

    query = select(SupportTicket).where(SupportTicket.id == ticket_id)
    result = await db.execute(query)
    ticket = result.scalars().first()
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found")

    if payload.status is not None:
        ticket.status = payload.status
    if payload.priority is not None:
        ticket.priority = payload.priority
    if payload.resolution_path is not None:
        ticket.resolution_path = payload.resolution_path
    if payload.resolution_summary is not None:
        ticket.resolution_summary = payload.resolution_summary
    if payload.metadata is not None:
        import json
        curr = ticket.metadata_dict
        curr.update(payload.metadata)
        ticket.metadata_json = json.dumps(curr)

    ticket.updated_at = utc_now()
    await db.commit()
    await db.refresh(ticket)
    return ticket.to_dict()
