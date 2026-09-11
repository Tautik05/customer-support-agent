import logging
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.db.database import get_db
from app.db.models import Customer, SupportTicket
from app.utils import utc_now
from app.workflow.graph import WorkflowRunner, support_workflow_graph

logger = logging.getLogger("support_agent.api.workflow")
router = APIRouter(prefix="/api/workflow", tags=["AI Resolution Workflow"])

# ==========================================
# Pydantic Schemas
# ==========================================
class ProcessTicketRequest(BaseModel):
    ticket_id: Optional[str] = None
    customer_email: EmailStr
    subject: str
    description: str

class HumanApprovalRequest(BaseModel):
    decision: str = Field(description="'APPROVED', 'REJECTED', or 'MODIFIED'")
    notes: Optional[str] = Field(default="", description="Operator feedback or rejection reason")
    modified_parameters: Optional[Dict[str, Any]] = Field(default=None, description="Optional overridden parameters (e.g. edited refund amount)")

# ==========================================
# Endpoints
# ==========================================
@router.post("/process", summary="Process ticket through LangGraph workflow")
async def process_ticket(payload: ProcessTicketRequest, db: AsyncSession = Depends(get_db)):
    """
    Submits a ticket into the LangGraph state machine.
    If a consequential action is proposed, it pauses at the Human Approval checkpoint.
    """
    ticket_id = payload.ticket_id or f"tkt_{int(utc_now().timestamp()*1000)}"

    # Check or create ticket record in database
    existing = (await db.execute(select(SupportTicket).where(SupportTicket.id == ticket_id))).scalars().first()
    if not existing:
        cust_res = await db.execute(select(Customer).where(Customer.email == payload.customer_email))
        cust = cust_res.scalars().first()
        customer_id = cust.id if cust else None

        new_tkt = SupportTicket(
            id=ticket_id,
            customer_id=customer_id,
            customer_email=payload.customer_email,
            subject=payload.subject,
            description=payload.description,
            status="in_progress",
            created_at=utc_now(),
        )
        db.add(new_tkt)
        await db.commit()
    else:
        customer_id = existing.customer_id

    # Execute LangGraph workflow
    result = await WorkflowRunner.process_ticket(
        ticket_id=ticket_id,
        customer_email=payload.customer_email,
        subject=payload.subject,
        description=payload.description,
        customer_id=customer_id,
    )

    state = result.get("state", {})
    is_interrupted = result.get("is_interrupted", False)

    return {
        "ticket_id": ticket_id,
        "is_waiting_human_approval": is_interrupted,
        "workflow_status": "WAITING_APPROVAL" if is_interrupted else state.get("workflow_status", "COMPLETED"),
        "resolution_path": state.get("resolution_path"),
        "classification": state.get("classification"),
        "entities": state.get("entities"),
        "rules_evaluation": state.get("rules_evaluation"),
        "proposed_action": state.get("proposed_action"),
        "original_proposed_action": state.get("original_proposed_action"),
        "response_draft": state.get("response_draft"),
        "action_result": state.get("action_result"),
        "final_response": state.get("final_response"),
        "audit_logs": state.get("audit_logs", []),
    }


@router.post("/approve/{ticket_id}", summary="Submit human approval decision to resume paused workflow")
async def submit_human_approval(
    ticket_id: str,
    payload: HumanApprovalRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    Resumes the LangGraph workflow with operator approval, rejection, or modified parameters.
    """
    if payload.decision.upper() not in ["APPROVED", "REJECTED", "MODIFIED"]:
        raise HTTPException(
            status_code=400,
            detail="Decision must be 'APPROVED', 'REJECTED', or 'MODIFIED'",
        )

    try:
        result = await WorkflowRunner.resume_ticket(
            ticket_id=ticket_id,
            decision=payload.decision.upper(),
            feedback_notes=payload.notes or "",
            modified_parameters=payload.modified_parameters,
        )
    except Exception as e:
        logger.error(f"Error resuming workflow for {ticket_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to resume workflow: {str(e)}")

    state = result.get("state", {})
    return {
        "ticket_id": ticket_id,
        "human_decision": payload.decision.upper(),
        "workflow_status": state.get("workflow_status", "COMPLETED"),
        "resolution_path": state.get("resolution_path"),
        "action_result": state.get("action_result"),
        "final_response": state.get("final_response"),
        "audit_logs": state.get("audit_logs", []),
    }

@router.get("/state/{ticket_id}", summary="Get current LangGraph workflow snapshot & audit trail")
async def get_ticket_workflow_state(ticket_id: str):
    config = {"configurable": {"thread_id": ticket_id}}
    try:
        snapshot = support_workflow_graph.get_state(config)
        if not snapshot or not snapshot.values:
            raise HTTPException(status_code=404, detail="No active workflow thread found for this ticket ID")

        values = snapshot.values
        is_interrupted = bool(snapshot.next)
        return {
            "ticket_id": ticket_id,
            "is_interrupted": is_interrupted,
            "next_nodes": snapshot.next,
            "state": values,
        }
    except Exception as e:
        raise HTTPException(status_code=404, detail=f"Workflow thread not found: {str(e)}")

@router.post("/evaluate", summary="Trigger automated benchmark evaluation suite")
async def run_evaluation():
    """Runs the 7-case golden evaluation dataset and calculates accuracy & compliance KPIs."""
    from app.evaluation.evaluate import run_evaluation_suite
    try:
        report = await run_evaluation_suite()
        return report
    except Exception as e:
        logger.error(f"Evaluation suite failed: {e}")
        raise HTTPException(status_code=500, detail=f"Evaluation failed: {str(e)}")
