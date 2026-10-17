"""LangGraph state definitions."""

from typing import Annotated, Any, Dict, List, Optional, TypedDict

from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages


class AgentState(TypedDict):
    """The state of the AI Data Engineer agent graph."""
    
    # Message history
    messages: Annotated[list[BaseMessage], add_messages]
    
    # Intent tracking (what the user actually wants to do)
    intent: Optional[str]
    
    # Incident-specific context (if investigating an RCA)
    run_id: Optional[str]
    workspace_id: Optional[str]
    
    # Discovered facts during reasoning
    evidence: List[Dict[str, Any]]
    
    # Structured outputs
    rca_report: Optional[str]
    remediation_plan: Optional[str]
