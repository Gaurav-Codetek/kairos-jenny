"""Agent API endpoints."""

from __future__ import annotations

import logging
import uuid
from typing import Any, Dict

from fastapi import APIRouter, Depends
from langchain_core.messages import HumanMessage
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from kairos_kb.agent.graph import agent_graph
from kairos_kb.agent import playbooks
from kairos_kb.agent.jev_rca import run_jev_rca
from kairos_kb.agent.rca import investigate
from kairos_kb.agent.scope import bind_incident
from kairos_kb.exceptions import KairosException
from kairos_kb.db.engine import get_db

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/agent", tags=["agent"])


class ChatRequest(BaseModel):
    message: str


class ChatResponse(BaseModel):
    response: str
    tools_used: list[str] = []


@router.post("/chat", response_model=ChatResponse)
async def chat_with_agent(body: ChatRequest):
    """Generic chat endpoint using the AI Data Engineer."""
    if not agent_graph:
        return ChatResponse(response="Agent is not configured (missing LLM credentials).")

    initial_state = {
        "messages": [HumanMessage(content=body.message)],
        "intent": "chat"
    }

    try:
        final_state = await agent_graph.ainvoke(initial_state)
        messages = final_state["messages"]
        
        # Extract the final AI response
        final_message = messages[-1].text
        
        # Optional: track which tools were called for UI transparency
        tools_used = []
        for msg in messages:
            if hasattr(msg, "tool_calls") and msg.tool_calls:
                tools_used.extend([t["name"] for t in msg.tool_calls])
                
        return ChatResponse(
            response=str(final_message),
            tools_used=tools_used
        )
    except Exception as exc:
        logger.error(f"Agent chat failed: {exc}")
        return ChatResponse(response=f"Error executing agent: {str(exc)}")


@router.post("/rca/{run_id}/structured")
async def generate_structured_rca(run_id: uuid.UUID):
    """Investigate a failed run and return a structured, persisted RCA.

    This is the contract external consumers should build on: the analysis is
    machine-readable and stored under a stable incident_id, so a remediation
    agent can act on it without parsing prose. The markdown narrative is
    included as one field, not as the whole response.
    """
    try:
        return await investigate(run_id)
    except RuntimeError as exc:
        raise KairosException(message=str(exc), status_code=502) from exc


@router.post("/rca/{run_id}/jev")
async def generate_jev_rca(run_id: str) -> Dict[str, Any]:
    """Experimental: Jev classifies the schema-drift subtype, then the agent verifies it.

    Runs beside the standard RCA without changing it. The response carries the
    markdown report plus Jev's hypothesis and the agent's own final label.
    """
    try:
        return await run_jev_rca(run_id)
    except Exception as exc:
        logger.error(f"Jev RCA failed: {exc}")
        return {"response": f"Error generating Jev RCA: {exc}", "tools_used": [], "jev": None}


@router.get("/playbooks")
async def list_rca_playbooks() -> list[Dict[str, Any]]:
    """Learned RCA playbooks, for inspection. Edit the YAML under data/playbooks to correct one."""
    return [playbooks.summary(pb) for pb in playbooks.load_all()]


@router.post("/rca/{run_id}", response_model=ChatResponse)
async def generate_rca(run_id: str):
    """Trigger the RCA runbook for a specific run ID."""
    if not agent_graph:
        return ChatResponse(response="Agent is not configured (missing LLM credentials).")

    prompt = f"""Investigate the failed Databricks job run with ID: {run_id}.
    
    Please generate a Root Cause Analysis (RCA) report. Use your tools to:
    1. Fetch the error message for this run using `get_failed_run_details`.
    2. If there are failed tasks, you MUST use `get_task_error_trace` with their `source_native_id` to get the actual Python/SQL notebook error trace.
    3. Check lineage if a specific table or pipeline step failed.
    4. Check recent changes to see if a schema or config change caused it.
    
    Return the final RCA as a detailed markdown report.
    """

    initial_state = {
        "messages": [HumanMessage(content=prompt)],
        "run_id": run_id,
        "intent": "rca_investigation"
    }

    try:
        await bind_incident(run_id)
        final_state = await agent_graph.ainvoke(initial_state)
        messages = final_state["messages"]
        final_message = messages[-1].text
        
        tools_used = []
        for msg in messages:
            if hasattr(msg, "tool_calls") and msg.tool_calls:
                tools_used.extend([t["name"] for t in msg.tool_calls])
                
        return ChatResponse(
            response=str(final_message),
            tools_used=tools_used
        )
    except Exception as exc:
        logger.error(f"Agent RCA failed: {exc}")
        return ChatResponse(response=f"Error generating RCA: {str(exc)}")
