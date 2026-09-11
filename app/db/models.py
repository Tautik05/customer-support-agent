from datetime import datetime
from typing import Any, Dict, List, Optional
from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import relationship
from app.db.database import Base
from app.utils import utc_now

class Customer(Base):
    __tablename__ = "customers"

    id = Column(String(64), primary_key=True, index=True)
    name = Column(String(128), nullable=False)
    email = Column(String(128), unique=True, index=True, nullable=False)
    phone = Column(String(64), nullable=True)
    tier = Column(String(32), default="Standard")  # "Free", "Standard", "VIP", "Enterprise"
    status = Column(String(32), default="active")  # "active", "suspended", "churned"
    created_at = Column(DateTime, default=utc_now)

    # Relationships
    subscriptions = relationship("Subscription", back_populates="customer", cascade="all, delete-orphan")
    orders = relationship("Order", back_populates="customer", cascade="all, delete-orphan")
    payments = relationship("Payment", back_populates="customer", cascade="all, delete-orphan")
    tickets = relationship("SupportTicket", back_populates="customer")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "email": self.email,
            "phone": self.phone,
            "tier": self.tier,
            "status": self.status,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }

class Subscription(Base):
    __tablename__ = "subscriptions"

    id = Column(String(64), primary_key=True, index=True)
    customer_id = Column(String(64), ForeignKey("customers.id"), nullable=False, index=True)
    plan_name = Column(String(128), nullable=False)  # e.g. "Pro Monthly", "Enterprise Annual"
    status = Column(String(32), default="active")  # "active", "past_due", "cancelled", "trial"
    amount = Column(Float, nullable=False)
    currency = Column(String(8), default="USD")
    billing_cycle = Column(String(32), default="monthly")  # "monthly", "annual"
    current_period_start = Column(DateTime, nullable=True)
    current_period_end = Column(DateTime, nullable=True)
    cancel_at_period_end = Column(Boolean, default=False)
    created_at = Column(DateTime, default=utc_now)

    # Relationships
    customer = relationship("Customer", back_populates="subscriptions")
    payments = relationship("Payment", back_populates="subscription")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "customer_id": self.customer_id,
            "plan_name": self.plan_name,
            "status": self.status,
            "amount": self.amount,
            "currency": self.currency,
            "billing_cycle": self.billing_cycle,
            "current_period_start": self.current_period_start.isoformat() if self.current_period_start else None,
            "current_period_end": self.current_period_end.isoformat() if self.current_period_end else None,
            "cancel_at_period_end": self.cancel_at_period_end,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }

class Order(Base):
    __tablename__ = "orders"

    id = Column(String(64), primary_key=True, index=True)
    customer_id = Column(String(64), ForeignKey("customers.id"), nullable=False, index=True)
    order_number = Column(String(64), unique=True, index=True, nullable=False)
    status = Column(String(32), default="delivered")  # "processing", "shipped", "in_transit", "delivered", "delayed", "cancelled", "returned"
    total_amount = Column(Float, nullable=False)
    currency = Column(String(8), default="USD")
    items_json = Column(Text, default="[]")  # JSON encoded list of items
    shipping_address = Column(Text, nullable=True)
    tracking_number = Column(String(64), nullable=True)
    created_at = Column(DateTime, default=utc_now)
    delivered_at = Column(DateTime, nullable=True)

    # Relationships
    customer = relationship("Customer", back_populates="orders")
    payments = relationship("Payment", back_populates="order")

    @property
    def items(self) -> List[Dict[str, Any]]:
        try:
            return json.loads(self.items_json) if self.items_json else []
        except Exception:
            return []

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "customer_id": self.customer_id,
            "order_number": self.order_number,
            "status": self.status,
            "total_amount": self.total_amount,
            "currency": self.currency,
            "items": self.items,
            "shipping_address": self.shipping_address,
            "tracking_number": self.tracking_number,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "delivered_at": self.delivered_at.isoformat() if self.delivered_at else None,
        }

class Payment(Base):
    __tablename__ = "payments"

    id = Column(String(64), primary_key=True, index=True)
    customer_id = Column(String(64), ForeignKey("customers.id"), nullable=False, index=True)
    order_id = Column(String(64), ForeignKey("orders.id"), nullable=True, index=True)
    subscription_id = Column(String(64), ForeignKey("subscriptions.id"), nullable=True, index=True)
    amount = Column(Float, nullable=False)
    currency = Column(String(8), default="USD")
    status = Column(String(32), default="succeeded")  # "succeeded", "refunded", "partially_refunded", "pending", "failed"
    payment_method = Column(String(64), default="credit_card")  # "credit_card", "paypal", "apple_pay"
    transaction_ref = Column(String(128), unique=True, index=True, nullable=False)
    description = Column(Text, nullable=True)
    created_at = Column(DateTime, default=utc_now)

    # Relationships
    customer = relationship("Customer", back_populates="payments")
    order = relationship("Order", back_populates="payments")
    subscription = relationship("Subscription", back_populates="payments")
    refunds = relationship("Refund", back_populates="payment")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "customer_id": self.customer_id,
            "order_id": self.order_id,
            "subscription_id": self.subscription_id,
            "amount": self.amount,
            "currency": self.currency,
            "status": self.status,
            "payment_method": self.payment_method,
            "transaction_ref": self.transaction_ref,
            "description": self.description,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }

class Refund(Base):
    __tablename__ = "refunds"

    id = Column(String(64), primary_key=True, index=True)
    payment_id = Column(String(64), ForeignKey("payments.id"), nullable=False, index=True)
    customer_id = Column(String(64), ForeignKey("customers.id"), nullable=False, index=True)
    amount = Column(Float, nullable=False)
    currency = Column(String(8), default="USD")
    reason = Column(Text, nullable=False)
    status = Column(String(32), default="processed")  # "pending_approval", "approved", "rejected", "processed"
    approved_by = Column(String(64), default="system")  # "system", "human_agent", "supervisor"
    created_at = Column(DateTime, default=utc_now)
    processed_at = Column(DateTime, nullable=True)

    # Relationships
    payment = relationship("Payment", back_populates="refunds")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "payment_id": self.payment_id,
            "customer_id": self.customer_id,
            "amount": self.amount,
            "currency": self.currency,
            "reason": self.reason,
            "status": self.status,
            "approved_by": self.approved_by,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "processed_at": self.processed_at.isoformat() if self.processed_at else None,
        }

class SupportTicket(Base):
    __tablename__ = "support_tickets"

    id = Column(String(64), primary_key=True, index=True)
    customer_id = Column(String(64), ForeignKey("customers.id"), nullable=True, index=True)
    customer_email = Column(String(128), index=True, nullable=False)
    subject = Column(String(256), nullable=False)
    description = Column(Text, nullable=False)
    category = Column(String(64), default="general")  # "billing", "shipping", "cancellation", "technical", "general"
    status = Column(String(32), default="open")  # "open", "in_progress", "pending_approval", "resolved", "escalated", "closed"
    priority = Column(String(32), default="medium")  # "low", "medium", "high", "urgent"
    resolution_path = Column(String(64), nullable=True)  # "DIRECT_RESOLVE", "ACTION_APPROVED", "ACTION_REJECTED", "ESCALATED"
    resolution_summary = Column(Text, nullable=True)
    metadata_json = Column(Text, default="{}")  # Stores LangGraph execution trace, extracted entities, proposed action
    created_at = Column(DateTime, default=utc_now)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now)

    # Relationships
    customer = relationship("Customer", back_populates="tickets")

    @property
    def metadata_dict(self) -> Dict[str, Any]:
        try:
            return json.loads(self.metadata_json) if self.metadata_json else {}
        except Exception:
            return {}

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "customer_id": self.customer_id,
            "customer_email": self.customer_email,
            "subject": self.subject,
            "description": self.description,
            "category": self.category,
            "status": self.status,
            "priority": self.priority,
            "resolution_path": self.resolution_path,
            "resolution_summary": self.resolution_summary,
            "metadata": self.metadata_dict,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }
