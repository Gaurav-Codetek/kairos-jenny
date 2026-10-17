"""Azure OpenAI provider implementation.

Uses LangChain under the hood for tracing (LangSmith) and standardized interaction.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List

from langchain_core.messages import HumanMessage, SystemMessage, AIMessage, BaseMessage

from kairos_kb.exceptions import LLMProviderError
from kairos_kb.llm.base import LLMProvider

logger = logging.getLogger(__name__)


class AzureOpenAIProvider(LLMProvider):
    """Azure OpenAI implementation of the LLMProvider."""

    def __init__(self) -> None:
        from kairos_kb.llm.provider import chat_model

        self._llm = chat_model()
        if self._llm is None:
            logger.warning("No LLM service is configured. LLM features will fail.")

    async def generate_rca(
        self,
        incident_context: Dict[str, Any],
        evidence: List[Dict[str, Any]],
        lineage: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """Generate a Root Cause Analysis report using the LangGraph agent."""
        from kairos_kb.agent.graph import agent_graph
        
        if not self._llm or not agent_graph:
            raise LLMProviderError("AzureOpenAI", "LLM or Agent Graph is not configured")
        
        run_id = incident_context.get("run_id", "unknown")
        
        # We start the agent with a prompt directing it to investigate this run
        prompt = f"""Investigate the failed Databricks job run with ID: {run_id}.
        
        Please generate a Root Cause Analysis (RCA) report. Use your tools to:
        1. Fetch the error message for this run.
        2. Check lineage if a specific table or pipeline step failed.
        3. Check recent changes to see if a schema or config change caused it.
        
        Return the final RCA as a detailed markdown report.
        """
        
        from langchain_core.messages import HumanMessage
        
        initial_state = {
            "messages": [HumanMessage(content=prompt)],
            "run_id": run_id,
            "intent": "rca_investigation"
        }
        
        try:
            # Run the graph
            final_state = await agent_graph.ainvoke(initial_state)
            
            # The final response from the LLM
            final_message = final_state["messages"][-1]
            
            return {
                "root_cause": final_message.text,
                "confidence": 0.85,
                "remediation": "See RCA report for proposed fixes.",
                "evidence_used": []
            }
        except Exception as exc:
            logger.error(f"LangGraph execution failed: {exc}")
            raise LLMProviderError("AzureOpenAI", f"Graph execution failed: {str(exc)}") from exc

    async def chat(self, messages: List[Dict[str, str]]) -> str:
        """General-purpose chat completion."""
        if not self._llm:
            raise LLMProviderError("AzureOpenAI", "LLM is not configured")

        lc_messages: List[BaseMessage] = []
        for msg in messages:
            role = msg.get("role", "")
            content = msg.get("content", "")
            if role == "system":
                lc_messages.append(SystemMessage(content=content))
            elif role == "user":
                lc_messages.append(HumanMessage(content=content))
            elif role == "assistant":
                lc_messages.append(AIMessage(content=content))
            else:
                lc_messages.append(HumanMessage(content=content))

        try:
            response = await self._llm.ainvoke(lc_messages)
            return response.text
        except Exception as exc:
            raise LLMProviderError("AzureOpenAI", str(exc)) from exc
