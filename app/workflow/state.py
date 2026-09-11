from typing import Any, Dict, List, Optional, TypedDict
from pydantic import BaseModel, Field

class TicketState(TypedDict, total=False):
    # Core ticket metadata
    ticket_id: str
    customer_email: str
    customer_id: Optional[str]
    subject: str
    description: str

    # Agent reasoning steps
    classification: Optional[Dict[str, Any]]
    entities: Optional[Dict[str, Any]]
    context_data: Optional[Dict[str, Any]]
    rules_evaluation: Optional[Dict[str, Any]]

    # Resolution decision & Human-in-the-Loop
    resolution_path: Optional[str]  # "DIRECT_RESOLVE", "ACTION_APPROVED", "ACTION_REJECTED", "ESCALATED", "PROPOSE_ACTION_APPROVAL"
    proposed_action: Optional[Dict[str, Any]]  # {action_type: str, parameters: dict, reason: str}
    original_proposed_action: Optional[Dict[str, Any]]  # Original AI proposal before any human modification
    human_approval_status: Optional[str]  # "PENDING", "APPROVED", "REJECTED", "MODIFIED"
    human_feedback_notes: Optional[str]
    response_draft: Optional[Dict[str, Any]]  # Pre-generated customer response draft for human review
    revalidation_result: Optional[Dict[str, Any]]  # Deterministic parameter revalidation result

    # Execution & Final Output
    action_result: Optional[Dict[str, Any]]
    final_response: Optional[Dict[str, Any]]
    workflow_status: str  # "IN_PROGRESS", "WAITING_APPROVAL", "COMPLETED", "ESCALATED"
    audit_logs: List[Dict[str, Any]]
    error: Optional[str]

