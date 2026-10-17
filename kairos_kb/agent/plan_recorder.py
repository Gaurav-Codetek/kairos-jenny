"""Record Agent A's investigation as a plan, instead of asking an LLM to re-imagine one.

Agent A's tool calls really ran, so their tool names and argument formats are
known to work. What makes them instance-specific is only their argument
values. This module turns a trace into a general plan in code:

  1. Anchor: find two structured column lists among the results (an expected
     one and an actual one) whose column_diff shows the diagnosed class and
     agrees with the error's counts.
  2. Provenance: for every argument of the calls the anchor needs, find where
     that value came from in an EARLIER tool output (full, untruncated) and
     replace it with a reference — ``$node.path`` for an exact value,
     ``{{node.path}}`` for a value embedded in a string (a path, a SQL filter).
  3. Leftovers: values that only appear inside long text (a path written in
     notebook code) become ``extract`` nodes. The LLM is used only to describe
     what each such value is, so it can be found in another pipeline's code.
  4. The tail — column_diff, verify, report — is the same for every schema
     class and is appended by code.

The result still goes through validation and a dry run before it is saved.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from pydantic import BaseModel, Field

from kairos_kb.agent.graph import llm
from kairos_kb.agent.plan_library import column_diff, counts_match_error, diff_explains_class

logger = logging.getLogger(__name__)

# Strings longer than this are text to extract from, not values to reference.
TEXT_THRESHOLD = 500
# Referenced values shorter than this are too generic to trace reliably.
MIN_VALUE_LEN = 3

# Text-returning readers are replaced by their structured equivalent, so the
# plan reads whole files and gets a stable output shape.
NORMALISE = {"read_databricks_text_file": "read_code_file"}

_QUOTED = re.compile(r"'([^']{2,})'|`([^`]{2,})`")
_FILTER_CONTEXT = re.compile(r"(?:(?<![=<>!])=|<>|!=|\bLIKE|\bIN\s*\([^)]*)\s*$", re.IGNORECASE)
_PATHISH = re.compile(r"/(?:Volumes|Workspace|Users|Repos|Shared)/[^\s'\"`),]+")


@dataclass
class Call:
    idx: int
    name: str
    args: Dict[str, Any]
    result: Any
    ok: bool
    node_id: str = ""
    leaves: List[Tuple[str, Any]] = field(default_factory=list)  # (path, value) for short values
    texts: List[Tuple[str, str]] = field(default_factory=list)   # (path, text) for long strings


def _parse(content: Any) -> Any:
    if not isinstance(content, str):
        return content
    try:
        return json.loads(content)
    except (ValueError, TypeError):
        return content


def _is_failure(result: Any) -> bool:
    if isinstance(result, dict) and set(result) == {"error"}:
        return True
    return isinstance(result, str) and result.lower().startswith("error")


def _flatten(value: Any, path: str, leaves: list, texts: list) -> None:
    if isinstance(value, dict):
        for k, v in value.items():
            if re.match(r"^[A-Za-z0-9_]+$", str(k)):
                _flatten(v, f"{path}.{k}", leaves, texts)
    elif isinstance(value, list):
        for i, v in enumerate(value[:200]):
            _flatten(v, f"{path}[{i}]", leaves, texts)
    elif isinstance(value, str):
        (texts if len(value) > TEXT_THRESHOLD else leaves).append((path, value))
    elif isinstance(value, (int, float)) and not isinstance(value, bool):
        leaves.append((path, value))


def calls_from_messages(messages) -> List[Call]:
    results = {m.tool_call_id: m.content for m in messages if isinstance(m, ToolMessage)}
    calls: List[Call] = []
    for m in messages:
        if isinstance(m, AIMessage) and m.tool_calls:
            for tc in m.tool_calls:
                result = _parse(results.get(tc.get("id")))
                call = Call(idx=len(calls), name=tc["name"], args=dict(tc.get("args") or {}), result=result,
                            ok=not _is_failure(result))
                if call.ok:
                    if isinstance(result, str):
                        call.texts.append(("", result))
                    else:
                        _flatten(result, "", call.leaves, call.texts)
                calls.append(call)
    return calls


# ── 1. Anchor: the expected / actual column lists ────────────────────


def _column_candidates(calls: List[Call]) -> List[Tuple[Call, List[str], str]]:
    """(call, names, field) for every successful result that is a column list or rows."""
    out = []
    for c in calls:
        if not c.ok or not isinstance(c.result, dict):
            continue
        if isinstance(c.result.get("columns"), list) and c.result["columns"]:
            out.append((c, [str(x) for x in c.result["columns"]], ""))
        elif isinstance(c.result.get("rows"), list) and c.result["rows"]:
            rows = [r for r in c.result["rows"] if isinstance(r, dict)]
            for f in (rows[0].keys() if rows else []):
                names = [str(r.get(f)) for r in rows if r.get(f) is not None]
                if names:
                    out.append((c, names, f))
    return out


def find_anchor(calls: List[Call], failure_class: str, error_text: str) -> Optional[Dict[str, Any]]:
    candidates = _column_candidates(calls)
    best = None
    for e_call, e_names, e_field in candidates:
        for a_call, a_names, a_field in candidates:
            if e_call.idx == a_call.idx or a_field:
                continue  # the actual side is a real column list, not a field of rows
            # Only pairs that are about the same columns: most names shared.
            overlap = len({x.lower() for x in e_names} & {x.lower() for x in a_names})
            if overlap < 0.5 * min(len(e_names), len(a_names)):
                continue
            d = column_diff(e_names, a_names)
            if d["identical"]:
                continue
            if not diff_explains_class(d, failure_class)["ok"] or not counts_match_error(d, error_text)["ok"]:
                continue
            score = (
                0 if a_call.name == "get_file_columns" else 1,       # incoming data is the actual side
                len(d["extra"]) + len(d["missing"]) + len(d["moved"]),
                -max(e_call.idx, a_call.idx),                         # Agent A's latest confirmation
            )
            if best is None or score < best[0]:
                best = (score, e_call, e_field, a_call, d)
    if not best:
        return None
    _, e_call, e_field, a_call, d = best
    return {"expected": e_call, "expected_field": e_field, "actual": a_call, "diff": d}


# ── 2/3. Provenance ──────────────────────────────────────────────────


class _Leftover(BaseModel):
    value: str
    field_name: str = Field(description="snake_case name for what this value is, e.g. schema_mapping_file")
    description: str = Field(description=(
        "What this value is, phrased so it can be found in a DIFFERENT file of the same kind, e.g. "
        "'the path assigned to the schema mapping CSV constant'. Do not quote the value itself."
    ))


class _Leftovers(BaseModel):
    items: List[_Leftover]


class Recorder:
    def __init__(self, calls: List[Call], run_id: str):
        self.calls = calls
        self.run_id = run_id
        self.needed: Dict[int, Call] = {}
        self.extracts: Dict[Tuple[int, str], Dict[str, Any]] = {}  # (text call idx, text path) → spec
        self.pending_leftovers: List[Dict[str, Any]] = []

    # A value's origin: the earliest successful earlier call that holds it.
    def _leaf_source(self, value: Any, before: int) -> Optional[Tuple[Call, str]]:
        for c in self.calls[:before]:
            if not c.ok:
                continue
            for path, v in c.leaves:
                if v == value or (isinstance(value, str) and isinstance(v, (int, float)) and str(v) == value):
                    return c, path
        return None

    def _text_source(self, value: str, before: int) -> Optional[Tuple[Call, str]]:
        """The earliest earlier output with the value embedded in a string — long text or short."""
        for c in self.calls[:before]:
            if not c.ok:
                continue
            short = [(p, v) for p, v in c.leaves if isinstance(v, str)]
            for path, text in c.texts + short:
                if value in text and value != text:
                    return c, path
        return None

    def _need(self, call: Call) -> str:
        if call.idx not in self.needed:
            self.needed[call.idx] = call
            call.node_id = f"{NORMALISE.get(call.name, call.name)}_{call.idx}"
            call.args = self._generalise_args(call)
        return call.node_id

    def _ref(self, call: Call, path: str) -> str:
        return f"{self._need(call)}{path}"

    def _generalise_args(self, call: Call) -> Dict[str, Any]:
        args = dict(call.args)
        if call.name in NORMALISE:  # read_databricks_text_file → read_code_file(file_path)
            args = {"file_path": args.get("file_path")}
        return {k: self._generalise_value(v, call.idx) for k, v in args.items()}

    def _generalise_value(self, value: Any, before: int) -> Any:
        if not isinstance(value, str) or not value:
            return value
        if value == self.run_id:
            return "$input.run_id"
        whole = self._leaf_source(value, before)
        if whole and len(value) >= MIN_VALUE_LEN:
            return "$" + self._ref(*whole)
        return self._template(value, before)

    def _template(self, text: str, before: int) -> str:
        """Replace traced values inside a string with {{refs}}; leave constants alone."""
        # Candidate pieces: quoted SQL literals / identifiers, and bare paths.
        quoted = [(m.group(0), m.group(1) or m.group(2)) for m in _QUOTED.finditer(text)]
        bare = [(p, p) for p in _PATHISH.findall(text) if not any(p == q for _, q in quoted)]
        if not quoted and not bare:
            if len(text) >= 300:
                return text
            return self._trace_piece(text, before) or text
        out = text
        # A quoted value compared in a filter (= 'x', LIKE 'x', IN ('x')) selects
        # WHICH data is examined — a configured value, never a constant.
        filters = {
            m.group(1) or m.group(2) for m in _QUOTED.finditer(text)
            if _FILTER_CONTEXT.search(text[: m.start()])
        }
        # Longest first, replacing only the exact quoted/bare occurrence, so a
        # short constant cannot be substituted inside another value.
        for whole, piece in sorted(quoted + bare, key=lambda x: len(x[1]), reverse=True):
            replacement = self._trace_piece(piece, before, filter_value=piece in filters)
            if replacement is not None:
                out = out.replace(whole, whole.replace(piece, replacement))
        return out

    def _trace_piece(self, piece: str, before: int, filter_value: bool = False) -> Optional[str]:
        if piece == self.run_id:
            return "{{input.run_id}}"
        if len(piece) < MIN_VALUE_LEN:
            return None
        leaf = self._leaf_source(piece, before)
        if leaf:
            return "{{" + self._ref(*leaf) + "}}"
        # A path assembled from two traced values, e.g. File_Path + File_Name.
        if "/" in piece:
            for c in self.calls[:before]:
                if not c.ok:
                    continue
                strs = [(p, v) for p, v in c.leaves if isinstance(v, str) and len(v) >= MIN_VALUE_LEN]
                for p1, v1 in strs:
                    if piece.startswith(v1):
                        for p2, v2 in strs:
                            if piece == v1 + v2:
                                n = self._need(c)
                                return "{{" + n + p1 + "}}{{" + n + p2 + "}}"
        # Only written inside some text (code, a trace): an extract node reads it.
        text_src = self._text_source(piece, before)
        distinctive = "/" in piece or "." in piece or "_" in piece or len(piece) >= 6
        if not distinctive and filter_value:
            # A short filter value counts when the code writes it as a quoted literal.
            quoted_src = self._text_source(f"'{piece}'", before) or self._text_source(f'"{piece}"', before)
            text_src, distinctive = quoted_src, bool(quoted_src)
        if text_src and distinctive:
            call, path = text_src
            key = (call.idx, path)
            spec = self.extracts.setdefault(key, {"call": call, "path": path, "values": {}})
            self._need(call)
            if piece not in spec["values"]:
                spec["values"][piece] = None  # named after the LLM describes it
                self.pending_leftovers.append({"key": key, "value": piece, "text": self._context(call, path, piece)})
            return f"<<{key[0]}|{key[1]}|{piece}>>"
        return None

    def _context(self, call: Call, path: str, piece: str) -> str:
        if path == "":
            text = call.result
        else:
            text = next(t for p, t in call.texts + [(p, v) for p, v in call.leaves if isinstance(v, str)] if p == path)
        i = text.find(piece)
        return text[max(0, i - 300): i + len(piece) + 200]


async def _describe_leftovers(pending: List[Dict[str, Any]]) -> Dict[str, _Leftover]:
    if not pending:
        return {}
    listing = "\n\n".join(
        f"VALUE: {p['value']}\nCONTEXT:\n{p['text']}" for p in pending
    )
    result: _Leftovers = await llm.with_structured_output(_Leftovers).ainvoke([
        SystemMessage(content=(
            "Each VALUE below was read out of code or text during a pipeline investigation. For each, give a "
            "snake_case field_name and a description of what the value IS, so that the equivalent value can be "
            "located in a different file of the same kind. Return one item per VALUE, with value copied exactly."
        )),
        HumanMessage(content=listing),
    ])
    return {item.value: item for item in result.items}


async def record_plan(messages, run_id: str, failure_class: str) -> Tuple[Optional[List[Dict[str, Any]]], str]:
    """Build a plan from Agent A's trace. Returns (nodes, reason); nodes is None if it cannot."""
    calls = calls_from_messages(messages)

    trace_call = next(
        (c for c in reversed(calls)
         if c.ok and c.name == "get_task_error_trace" and isinstance(c.result, dict) and c.result.get("error")),
        None,
    )
    error_text = trace_call.result["error"] if trace_call else ""

    anchor = find_anchor(calls, failure_class, error_text)
    if not anchor:
        return None, "no pair of structured column lists in the trace explains the class"

    rec = Recorder(calls, run_id)
    expected_id = rec._need(anchor["expected"])
    actual_id = rec._need(anchor["actual"])
    trace_id = rec._need(trace_call) if trace_call else None

    # Name the leftovers and turn their placeholders into extract references.
    described = await _describe_leftovers(rec.pending_leftovers)
    extract_nodes: Dict[Tuple[int, str], Dict[str, Any]] = {}
    names_used: Dict[Tuple[int, str], Dict[str, str]] = {}
    for p in rec.pending_leftovers:
        item = described.get(p["value"])
        if not item:
            return None, f"could not describe leftover value {p['value']!r}"
        key = p["key"]
        spec = rec.extracts[key]
        node_id = f"extract_{spec['call'].idx}"
        # A text reader normalised to read_code_file returns {text}, not a string.
        src_path = ".text" if spec["call"].name in NORMALISE and spec["path"] == "" else spec["path"]
        fields = extract_nodes.setdefault(key, {
            "id": node_id, "type": "extract", "name": "extract",
            "args": {"from": f"${spec['call'].node_id}{src_path}", "fields": {}},
        })["args"]["fields"]
        fname = re.sub(r"[^a-z0-9_]", "_", item.field_name.lower()).strip("_") or "value"
        while fname in fields:
            fname += "_x"
        fields[fname] = item.description
        names_used.setdefault(key, {})[p["value"]] = f"{{{{{node_id}.{fname}}}}}"

    placeholder = re.compile(r"<<(\d+)\|([^|]*)\|(.+?)>>")

    def fill(value: Any) -> Any:
        if isinstance(value, dict):
            return {k: fill(v) for k, v in value.items()}
        if isinstance(value, list):
            return [fill(v) for v in value]
        if isinstance(value, str):
            return placeholder.sub(lambda m: names_used[(int(m.group(1)), m.group(2))][m.group(3)], value)
        return value

    # Order: calls in the order Agent A made them; each extract right after its text source.
    nodes: List[Dict[str, Any]] = []
    for call in sorted(rec.needed.values(), key=lambda c: c.idx):
        nodes.append({"id": call.node_id, "type": "tool", "name": NORMALISE.get(call.name, call.name),
                      "args": fill(call.args)})
        for key, ex in extract_nodes.items():
            if key[0] == call.idx:
                nodes.append(ex)

    nodes.append({"id": "diff", "type": "compute", "name": "column_diff", "args": {
        "expected": f"${expected_id}", "actual": f"${actual_id}", "expected_field": anchor["expected_field"],
    }})
    nodes.append({"id": "verify_class", "type": "verify", "name": "diff_explains_class",
                  "args": {"diff": "$diff", "failure_class": "$input.failure_class"}})
    facts = {"expected_columns_from": f"${expected_id}", "actual_columns_from": f"${actual_id}",
             "column_diff": "$diff"}
    if trace_id:
        nodes.append({"id": "verify_counts", "type": "verify", "name": "counts_match_error",
                      "args": {"diff": "$diff", "error": f"${trace_id}.error"}})
        facts = {"error": f"${trace_id}.error", **facts}
    nodes.append({"id": "report", "type": "report", "name": "report", "args": {"facts": facts}})
    return nodes, "recorded"
