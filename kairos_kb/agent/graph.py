"""LangGraph orchestration and agent creation."""

import logging
from typing import Literal

from langchain_core.messages import SystemMessage, HumanMessage
from langgraph.graph import StateGraph, START, END
from langgraph.prebuilt import ToolNode

from kairos_kb.agent.state import AgentState
from kairos_kb.agent.tools import DATA_ENGINEER_TOOLS
from kairos_kb.config import get_settings
from kairos_kb.llm.provider import chat_model

logger = logging.getLogger(__name__)

# Initialize LLM
settings = get_settings()
try:
    llm = chat_model()
    llm_with_tools = llm.bind_tools(DATA_ENGINEER_TOOLS) if llm else None
except Exception as e:
    logger.error(f"Failed to initialize the LLM for LangGraph: {e}")
    llm = None
    llm_with_tools = None


SYSTEM_PROMPT = """You are Kairos, an AI-Native Data Platform Intelligence agent.
Your goal is to act as an expert Data Engineer investigating pipelines, Databricks architecture, and resolving issues.
You have access to a 'Synthetic Warehouse' which is a local replica of the Databricks metadata, jobs, and lineage.

When you investigate an issue or failed run, your GOAL is to:
Verify with evidence exactly what caused the error, what changed, and where it changed.

You also have an ENTITY MAP — a knowledge graph connecting every grain of the platform:
workspaces, catalogs, schemas, tables, columns, jobs, tasks, runs and task runs, plus
relationships an enrichment agent discovered by reading the actual task code. Navigate it
rather than guessing at names.

A failed run investigation normally walks the graph like this:

1. get_failed_run_details(run_id) — the failure, which tasks failed, and which were
   blocked. Blocked tasks tell you where in the chain the failure originated.
2. get_task_context(taskrun_entity_id) — resolves the failed task run to its task
   definition. This is how you get notebook_path; do not guess it. It also tells you
   what the task waits on and what it blocks.
3. get_task_error_trace(source_native_id) — the real Python/SQL trace.
4. read_databricks_text_file(notebook_path) — the code that actually ran.
5. get_data_dependencies(task_entity_id) — which tables that task reads and writes.
   This is the link classic lineage does not carry; it comes from reading the code.
6. get_entity_profile(entity_id) — what a table means, its grain, what it serves.
7. get_blast_radius(table_entity_id) — who consumes the table that broke, for impact.

Weigh your evidence honestly. A relationship marked 'discovered' was inferred by an agent
reading code and carries a confidence and a rationale — cite it as such, not as fact. If
get_data_dependencies returns nothing, that entity has not been enriched yet; say so
rather than concluding it touches nothing.

Do not just run a predefined list of steps. Think critically about the problem.
If the error mentions a missing column or mismatched schema, look at recent schema changes
or read the source code to see what logic was introduced.

Be concise, clear, and evidence-backed in your reasoning.
Use markdown for your responses.

When writing your Root Cause Analysis, you MUST structure your response with exactly these four headers:
### 🚨 Incident Summary
(Briefly summarize what failed and when)

### 🔍 Root Cause Analysis
(Explain exactly what the error is and why it happened, using evidence gathered from tools)

### ⛓️ Lineage & Impact
(Identify which tables/columns are affected and downstream dependencies)

### 🛠️ Recommended Fix
(Provide actionable steps to resolve the issue, e.g., the exact SQL or Python code change)
"""


async def supervisor_node(state: AgentState) -> dict:
    """The main reasoning node that decides whether to use tools or answer."""
    if not llm_with_tools:
        return {"messages": [SystemMessage(content="LLM is not configured properly.")]}
        
    messages = state.get("messages", [])
    
    # Ensure system prompt is present
    if not messages or not isinstance(messages[0], SystemMessage):
        messages = [SystemMessage(content=SYSTEM_PROMPT)] + messages
        
    response = await llm_with_tools.ainvoke(messages)
    
    return {"messages": [response]}


def should_continue(state: AgentState) -> Literal["tools", "__end__"]:
    """Determine if the agent invoked a tool or if it finished."""
    messages = state.get("messages", [])
    last_message = messages[-1]
    
    if last_message.tool_calls:
        return "tools"
    return "__end__"


# Build the Graph
def build_agent_graph() -> StateGraph:
    """Constructs the LangGraph for the AI Data Engineer."""
    workflow = StateGraph(AgentState)
    
    # Add nodes
    workflow.add_node("supervisor", supervisor_node)
    
    # We use the prebuilt ToolNode to execute our deterministic DB functions
    tool_node = ToolNode(DATA_ENGINEER_TOOLS)
    workflow.add_node("tools", tool_node)
    
    # Add edges
    workflow.add_edge(START, "supervisor")
    
    # Conditional logic: if tools are called, go to 'tools', else END
    workflow.add_conditional_edges(
        "supervisor",
        should_continue,
    )
    
    # After tools are executed, go back to the supervisor to evaluate the results
    workflow.add_edge("tools", "supervisor")
    
    # Compile the graph
    return workflow.compile()

# Create a singleton compiled graph instance
agent_graph = build_agent_graph() if llm else None
