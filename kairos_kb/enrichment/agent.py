"""The enrichment agent: reads one entity deeply, then writes its profile.

A bounded tool loop rather than a graph — the control flow here is simply
"keep calling tools until the model saves a profile or runs out of budget",
and doing it explicitly lets every tool call surface as a UI event.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage, ToolMessage

from kairos_kb.enrichment.tools import ToolContext, build_tools

logger = logging.getLogger(__name__)

# Each iteration is one LLM turn, and the model usually spends a turn per
# tool call. Deep reads on a task touching many tables burn through these
# quickly, so the budget has to be generous.
MAX_ITERATIONS = 24

# Turns held back at the end purely for save_profile. Without this the agent
# can investigate until it runs out and never write anything down.
SAVE_RESERVE = 3

SYSTEM_PROMPT = """You are the Kairos enrichment agent. You build the semantic layer of a
Synthetic Warehouse that mirrors a Databricks workspace.

You are given ONE entity at a time, along with everything the warehouse already
knows about it. That raw snapshot is only structure — your job is to turn it into
understanding, and to discover how this entity connects to the rest of the platform.

Work in two passes.

PASS 1 — INVESTIGATE.
Read whatever will tell you what this thing really is and does.
- For a task: ALWAYS read its notebook or SQL file with read_databricks_file. The code
  is the only place the real logic lives. Read the whole thing, paginating if needed.
- For a job: study settings_snapshot closely — schedule, parameters, cluster config,
  task topology, notification and retry policy — then investigate its tasks' code.
- For a table: study its columns, comments, naming, existing lineage and change history.
  Infer the grain (what one row represents) and the layer (bronze/silver/gold) if evident.
- For a catalog or schema: study what it holds and infer the domain it serves.
- If you see a Volume path, list it with list_databricks_directory and inspect data files
  with query_data_file to learn their shape.

PASS 2 — CONNECT THE DOTS.
Whenever the material shows this entity touching something else, call link_entities.
This is the most valuable thing you do. Examples of what to look for in code and config:
- tables read from or written to (spark.table, saveAsTable, INSERT INTO, MERGE, FROM)
- files read from or written to volumes or cloud storage paths
- Genie spaces, external connections, dashboards, other jobs it triggers
- parameters or widgets that name a dataset

The relation vocabulary is FIXED. Use exactly one of:
READS_TABLE, WRITES_TABLE, READS_FILE, WRITES_FILE, FEEDS (table to table),
DEPENDS_ON, TRIGGERS, RUNS_NOTEBOOK, USES_EXTERNAL, STORED_AT.
Never link containment (a table in a schema, a task in a job) — Kairos already knows
it. Never link on a name resemblance alone — put such suspicions in open_questions.

Rules that matter:
- NEVER assert a link you have not seen concrete support for. Every link needs a
  rationale quoting or describing the exact code line, config key, or API field.
- If a target is not in the warehouse, link to it anyway using its raw name or path.
  It will be registered as a discovered entity. Do not silently drop it.
- Use find_entity to turn a name you saw in code into a real entity_id where you can.
- Prefer several precise links over one vague one.
- Call link_entities for ALL the links you found in one turn rather than one per turn.
  Your turn budget is limited and each turn spent on a single link is a turn you
  cannot spend investigating.

PARENT CONTEXT.
The snapshot may include a "parent_context" block — the profile of the entity whose
links led here, and the relation that led here. Use it. A task profiled beneath its
job should read as part of that job's purpose, not as an isolated notebook. Say how
this entity contributes to what its parent does, and do not contradict the parent
without evidence.

FACTS AND TEMPLATE.
The first message may include FACTS established by code (row counts, writers from Delta
history, known relationships) and, for tables, a CLASSIFICATION with a TEMPLATE of what
the profile must cover. Facts are authoritative: build on them, never contradict them,
and do not spend turns re-deriving them. The classification is a hypothesis.

FINISH by calling save_profile exactly once with your consolidated understanding.
Be concrete and specific. Say what you actually determined; put genuine uncertainty in
open_questions rather than guessing. Do not restate the raw snapshot back at me —
the profile should add meaning that was not already in the structural metadata.
"""


def _build_llm():
    from kairos_kb.llm.provider import chat_model

    return chat_model()


def _short(value: Any, limit: int = 90) -> str:
    text = str(value)
    return text if len(text) <= limit else "…" + text[-(limit - 1):]


def describe_tool_call(name: str, args: Dict[str, Any]) -> str:
    """One human line for what a tool call is doing — the live activity feed."""
    if name == "read_databricks_file":
        return f"Reading {_short(args.get('path', ''))}"
    if name == "list_databricks_directory":
        return f"Listing {_short(args.get('path', ''))}"
    if name == "query_data_file":
        return f"Sampling data in {_short(args.get('path', ''))}"
    if name == "find_entity":
        return f"Searching the warehouse for '{_short(args.get('keyword', ''), 40)}'"
    if name == "link_entities":
        return f"Linking {args.get('relation_type', '')} → {_short(args.get('target', ''), 60)}"
    if name == "register_entity":
        return f"Registering {args.get('kind', 'entity')} {_short(args.get('reference', ''), 60)}"
    if name == "save_profile":
        return "Writing the profile"
    return f"Calling {name}"


async def _telemetry(ctx: ToolContext, **kwargs: Any) -> None:
    if ctx.telemetry is None:
        return
    try:
        await ctx.telemetry(**kwargs)
    except Exception:  # noqa: BLE001 — telemetry must never break profiling
        logger.debug("telemetry update failed", exc_info=True)


def _render_context(context_doc: Dict[str, Any]) -> str:
    """Render the gathered warehouse context as the opening user message."""
    return json.dumps(context_doc, indent=2, default=str)[:120_000]


# Tool results older than this many are trimmed before each turn. The model has
# already read them and written its links; resending a whole notebook on every
# later turn was most of an entity's input tokens.
KEEP_FULL_TOOL_RESULTS = 3
TRIMMED_TOOL_RESULT_CHARS = 1200


def compact_history(messages: List[BaseMessage]) -> None:
    """Trim older tool results in place, keeping the most recent ones whole."""
    tool_idx = [i for i, m in enumerate(messages) if isinstance(m, ToolMessage)]
    for i in tool_idx[:-KEEP_FULL_TOOL_RESULTS]:
        content = messages[i].content
        if isinstance(content, str) and len(content) > TRIMMED_TOOL_RESULT_CHARS and not content.startswith("[trimmed"):
            messages[i].content = (
                f"[trimmed: already read, {len(content):,} chars originally; its links are recorded]\n"
                + content[:TRIMMED_TOOL_RESULT_CHARS]
            )


async def profile_entity(
    ctx: ToolContext,
    context_doc: Dict[str, Any],
    *,
    max_iterations: int = MAX_ITERATIONS,
    brief: str = "",
) -> Dict[str, Any]:
    """Run the agent over one entity. Returns the profile fields it saved.

    Raises RuntimeError when the LLM is unconfigured or the agent finished
    without producing a profile.
    """
    llm = _build_llm()
    if llm is None:
        raise RuntimeError("Azure OpenAI is not configured; cannot run enrichment.")

    tools = build_tools(ctx)
    tools_by_name = {t.name: t for t in tools}
    llm_with_tools = llm.bind_tools(tools)

    # Used for the closing turns: with only save_profile available the model
    # cannot wander back into investigation when the budget is nearly gone.
    save_tool = tools_by_name.get("save_profile")
    llm_save_only = llm.bind_tools([save_tool]) if save_tool else llm_with_tools

    messages: List[BaseMessage] = [
        SystemMessage(content=SYSTEM_PROMPT),
        HumanMessage(
            content=(
                f"Profile this {ctx.kind}.\n\n"
                f"entity_id: {ctx.entity_id}\n\n"
                f"What the warehouse already knows:\n```json\n{_render_context(context_doc)}\n```"
                + (f"\n\n{brief}" if brief else "")
            )
        ),
    ]

    forced_save_announced = False

    for iteration in range(max_iterations):
        remaining = max_iterations - iteration
        # Once the reserve is reached, stop investigating and write it down.
        force_save = remaining <= SAVE_RESERVE and not ctx.profile_fields

        if force_save and not forced_save_announced:
            forced_save_announced = True
            messages.append(
                HumanMessage(
                    content=(
                        "You have run out of investigation budget. Call save_profile NOW "
                        "with what you have already determined. Everything you linked so "
                        "far is saved, so summarise what you found and put anything you "
                        "could not confirm into open_questions."
                    )
                )
            )
            await ctx.emit(
                "tool_call",
                "Investigation budget reached — forcing profile save",
                level="warning",
            )

        compact_history(messages)
        await _telemetry(ctx, activity=f"Thinking · turn {iteration + 1} of {max_iterations}")
        response: AIMessage = await (llm_save_only if force_save else llm_with_tools).ainvoke(
            messages
        )
        messages.append(response)
        usage = getattr(response, "usage_metadata", None) or {}
        await _telemetry(
            ctx,
            input_tokens=int(usage.get("input_tokens") or 0),
            output_tokens=int(usage.get("output_tokens") or 0),
            llm_calls=1,
        )

        tool_calls = getattr(response, "tool_calls", None) or []
        if not tool_calls:
            # No tool call and no profile yet — nudge once, then give up.
            if ctx.profile_fields:
                break
            if iteration >= max_iterations - 1:
                break
            messages.append(
                HumanMessage(
                    content="You have not called save_profile yet. Do it now with what you determined."
                )
            )
            continue

        for call in tool_calls:
            name = call.get("name", "")
            args = call.get("args", {}) or {}
            selected = tools_by_name.get(name)
            activity = describe_tool_call(name, args)
            await _telemetry(ctx, activity=activity, tool_calls=1)
            # Links already announce themselves as relation_found events.
            if name != "link_entities":
                await ctx.emit("tool_call", activity)

            if selected is None:
                result = f"ERROR: unknown tool '{name}'."
            else:
                try:
                    result = await selected.ainvoke(args)
                except Exception as exc:  # noqa: BLE001 - surfaced back to the model
                    logger.warning("Tool %s failed on %s: %s", name, ctx.entity_id, exc)
                    result = f"ERROR calling {name}: {exc}"

            messages.append(
                ToolMessage(content=str(result)[:60_000], tool_call_id=call.get("id", name))
            )

        if ctx.profile_fields:
            break

    if not ctx.profile_fields:
        raise RuntimeError(
            f"Agent finished without saving a profile for {ctx.entity_id} after "
            f"{max_iterations} turns. The {ctx.links_made} relationship(s) it found "
            f"were still committed and are in the entity map; only the YAML profile "
            f"is missing. Re-run this entity to produce it."
        )

    return ctx.profile_fields
