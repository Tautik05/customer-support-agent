import logging
from typing import Any, AsyncGenerator, Dict, Optional
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from app.workflow.nodes import (
    classify_ticket_node,
    context_lookup_node,
    decide_resolution_node,
    draft_response_node,
    evaluate_rules_node,
    execute_action_node,
    extract_entities_node,
    finalize_ticket_node,
    human_approval_node,
)
from app.workflow.state import TicketState

logger = logging.getLogger("support_agent.workflow.graph")

def route_after_decision(state: TicketState) -> str:
    path = state.get("resolution_path", "DIRECT_RESOLVE")
    if path == "ESCALATED":
        return "finalize"
    else:
        # Both PROPOSE_ACTION_APPROVAL and DIRECT_RESOLVE generate response draft first
        return "draft_response"

def route_after_draft(state: TicketState) -> str:
    path = state.get("resolution_path", "DIRECT_RESOLVE")
    if path == "PROPOSE_ACTION_APPROVAL":
        return "human_approval"
    else:
        return "execute_action"

def build_support_graph():
    builder = StateGraph(TicketState)

    # Add all workflow nodes
    builder.add_node("classify", classify_ticket_node)
    builder.add_node("extract", extract_entities_node)
    builder.add_node("lookup", context_lookup_node)
    builder.add_node("rules", evaluate_rules_node)
    builder.add_node("decide", decide_resolution_node)
    builder.add_node("draft_response", draft_response_node)
    builder.add_node("human_approval", human_approval_node)
    builder.add_node("execute_action", execute_action_node)
    builder.add_node("finalize", finalize_ticket_node)

    # Connect initial nodes
    builder.add_edge(START, "classify")
    builder.add_edge("classify", "extract")
    builder.add_edge("extract", "lookup")
    builder.add_edge("lookup", "rules")
    builder.add_edge("rules", "decide")

    # Conditional branching from decide
    builder.add_conditional_edges(
        "decide",
        route_after_decision,
        {
            "finalize": "finalize",
            "draft_response": "draft_response",
        },
    )

    # Conditional branching from draft_response
    builder.add_conditional_edges(
        "draft_response",
        route_after_draft,
        {
            "human_approval": "human_approval",
            "execute_action": "execute_action",
        },
    )

    # Path from human approval
    builder.add_edge("human_approval", "execute_action")
    builder.add_edge("execute_action", "finalize")
    builder.add_edge("finalize", END)

    # Checkpointer for Human-in-the-loop state persistence
    checkpointer = MemorySaver()
    graph = builder.compile(checkpointer=checkpointer)
    return graph

# Global compiled graph instance
support_workflow_graph = build_support_graph()

class WorkflowRunner:
    """Manages LangGraph execution, checkpointing, and human resume operations."""

    @staticmethod
    async def process_ticket(
        ticket_id: str,
        customer_email: str,
        subject: str,
        description: str,
        customer_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Runs the workflow until completion or until paused at a human approval checkpoint."""
        config = {"configurable": {"thread_id": ticket_id}}
        initial_state: TicketState = {
            "ticket_id": ticket_id,
            "customer_email": customer_email,
            "customer_id": customer_id,
            "subject": subject,
            "description": description,
            "human_approval_status": "PENDING",
            "workflow_status": "IN_PROGRESS",
            "audit_logs": [],
        }

        logger.info(f"Starting LangGraph workflow execution for thread {ticket_id}")
        result_state = await support_workflow_graph.ainvoke(initial_state, config=config)
        
        # Check current state from checkpointer to inspect if interrupted
        state_snapshot = support_workflow_graph.get_state(config)
        is_interrupted = bool(state_snapshot.next)

        return {
            "state": result_state or state_snapshot.values,
            "is_interrupted": is_interrupted,
            "next_nodes": state_snapshot.next,
            "thread_id": ticket_id,
        }

    @staticmethod
    async def resume_ticket(
        ticket_id: str,
        decision: str,  # "APPROVED", "REJECTED", "MODIFIED"
        feedback_notes: str = "",
        modified_parameters: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Resumes a paused workflow at the human approval checkpoint."""
        config = {"configurable": {"thread_id": ticket_id}}
        
        resume_payload = {
            "decision": decision.upper(),
            "notes": feedback_notes,
            "modified_parameters": modified_parameters,
        }

        from langgraph.types import Command
        logger.info(f"Resuming thread {ticket_id} with human decision: {decision}")
        
        result_state = await support_workflow_graph.ainvoke(
            Command(resume=resume_payload),
            config=config,
        )

        state_snapshot = support_workflow_graph.get_state(config)
        is_interrupted = bool(state_snapshot.next)

        return {
            "state": result_state or state_snapshot.values,
            "is_interrupted": is_interrupted,
            "next_nodes": state_snapshot.next,
            "thread_id": ticket_id,
        }
