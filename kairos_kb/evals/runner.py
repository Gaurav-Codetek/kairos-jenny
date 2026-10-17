"""Agent evaluations: score the Jev RCA path against golden incidents.

Three suites, cheapest first:

  classification  Jev's class for each incident, asked ``repeat`` times, so
                  accuracy AND consistency are measured. ~2 s per call.
  diagnosis       Jev picks a learned variant; Agent B runs it; the column
                  diff it computes is checked against the known answer.
                  ~45 s per incident.
  e2e             The whole ``run_jev_rca`` flow, as the button runs it. Uses
                  an isolated copy of the variant store so an evaluation can
                  never change what production has learned. Minutes per incident.

Every run writes ``<storage>/evals/<timestamp>.json`` and is compared with
the previous report, so a regression is called out rather than noticed later.
These call live Databricks, TypeSafe and Azure OpenAI and spend LLM budget.
"""

from __future__ import annotations

import json
import shutil
import statistics
import tempfile
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

from kairos_kb.config import get_settings

GOLDEN = Path(__file__).with_name("golden.yaml")
SUITES = ("classification", "diagnosis", "e2e")
DEFAULT_SUITES = ("classification", "diagnosis")
# A slowdown bigger than this versus the previous report is flagged.
SLOWDOWN_FACTOR = 1.5


@dataclass
class Case:
    id: str
    run_id: str
    expected_class: str
    diagnosable: bool
    description: str = ""
    note: str = ""
    expect: Dict[str, Any] = field(default_factory=dict)


def load_cases(only: Optional[List[str]] = None) -> List[Case]:
    raw = yaml.safe_load(GOLDEN.read_text(encoding="utf-8"))["cases"]
    cases = [Case(**{k: v for k, v in c.items() if k in Case.__dataclass_fields__}) for c in raw]
    return [c for c in cases if not only or c.id in only]


# ── checking a computed diff against the known answer ────────────────


def check_facts(diff: Optional[Dict[str, Any]], expect: Dict[str, Any]) -> List[str]:
    """Every expectation the diff does not meet, in words. Empty means correct."""
    if not diff:
        return ["no column diff was computed"]
    problems = []
    low = lambda xs: {str(x).lower() for x in xs}  # noqa: E731
    if "counts" in expect:
        got = [diff.get("expected_count"), diff.get("actual_count")]
        if got != list(expect["counts"]):
            problems.append(f"counts {got} != expected {expect['counts']}")
    missing_extra = low(expect.get("extra_includes", [])) - low(diff.get("extra", []))
    if missing_extra:
        problems.append(f"extra columns not reported: {sorted(missing_extra)}")
    found = {(r["expected"].lower(), r["actual"].lower()) for r in diff.get("rename_candidates", [])}
    for old, new in expect.get("renames", []):
        if (old.lower(), new.lower()) not in found:
            problems.append(f"rename {old} → {new} not reported")
    if expect.get("no_other_extra"):
        renamed = {a for _, a in found}
        other = low(diff.get("extra", [])) - renamed
        if other:
            problems.append(f"unexpected extra columns: {sorted(other)}")
    return problems


# ── suites ───────────────────────────────────────────────────────────


async def eval_classification(case: Case, repeat: int = 3) -> Dict[str, Any]:
    from kairos_kb.agent.jev_rca import classify_with_jev, gather_evidence

    state, _ = await gather_evidence(case.run_id)
    answers = [await classify_with_jev(state) for _ in range(repeat)]
    ok = [a for a in answers if a.get("status") == "ok"]
    labels = [a.get("hypothesis") for a in answers]
    correct = sum(1 for a in ok if a["hypothesis"] == case.expected_class)
    return {
        "suite": "classification",
        "case": case.id,
        "expected": case.expected_class,
        "predictions": labels,
        "accuracy": round(correct / repeat, 3),
        # Correct AND confident enough to steer the investigation.
        "usable": sum(1 for a in ok if a["hypothesis"] == case.expected_class and a.get("used_as_hint")),
        "consistent": len(set(labels)) == 1,
        "mean_confidence": round(statistics.mean(a["confidence"] for a in ok), 3) if ok else None,
        "mean_latency_ms": round(statistics.mean(a["latency_ms"] for a in ok)) if ok else None,
        "comparison_in_evidence": any("column_comparison_computed_from_error" in t for t in state.get("failed_tasks", [])),
        "errors": [a.get("reason") for a in answers if a.get("status") != "ok"],
        "passed": correct == repeat,
    }


async def eval_diagnosis(case: Case) -> Dict[str, Any]:
    from kairos_kb.agent import playbooks
    from kairos_kb.agent.jev_rca import gather_evidence, match_variant_with_jev
    from kairos_kb.agent.plan_executor import run_plan

    base = {"suite": "diagnosis", "case": case.id, "expected": case.expected_class}
    if not case.diagnosable:
        return {**base, "skipped": True, "reason": case.note.strip() or "not diagnosable on live data"}

    state, _ = await gather_evidence(case.run_id)
    variants = playbooks.variants_for(case.expected_class)
    match = await match_variant_with_jev(state, variants)
    variant = match.get("variant")
    if not variant:
        return {**base, "passed": False, "reason": f"no variant chosen ({match.get('reason') or match.get('choice')})",
                "variants_available": len(variants)}

    started = time.perf_counter()
    result = await run_plan(variant["plan"], case.run_id, case.expected_class, return_results=True)
    diff = next(
        (result["results"].get(n["id"]) for n in variant["plan"]
         if n["type"] == "compute" and n.get("name") == "column_diff"),
        None,
    )
    problems = check_facts(diff, case.expect) if result["success"] else [f"Agent B failed: {result['failure']}"]
    return {
        **base,
        "variant": variant["id"],
        "variant_status": variant.get("status"),
        "match_confidence": match.get("confidence"),
        "agent_b_success": result["success"],
        "fact_problems": problems,
        "tool_calls": result["tool_calls"],
        "ms": round((time.perf_counter() - started) * 1000),
        "passed": result["success"] and not problems,
    }


async def eval_end_to_end(case: Case) -> Dict[str, Any]:
    from kairos_kb.agent import jev_rca, playbooks

    base = {"suite": "e2e", "case": case.id, "expected": case.expected_class}
    if not case.diagnosable:
        return {**base, "skipped": True, "reason": case.note.strip() or "not diagnosable on live data"}

    # Isolation: run against a throwaway copy of the variant store, and keep
    # evaluation runs out of the production comparison log.
    real_root, real_log = playbooks._root, jev_rca._log_run
    with tempfile.TemporaryDirectory() as tmp:
        if real_root().exists():
            shutil.copytree(real_root(), Path(tmp) / "playbooks")
        playbooks._root = lambda: Path(tmp) / "playbooks"
        jev_rca._log_run = lambda record: None
        try:
            result = await jev_rca.run_jev_rca(case.run_id)
        finally:
            playbooks._root, jev_rca._log_run = real_root, real_log

    label = result.get("agent_classification")
    return {
        **base,
        "mode": result.get("mode"),
        "label": label,
        "jev": (result.get("jev") or {}).get("hypothesis"),
        "agreement": result.get("agreement"),
        "tool_calls": len(result.get("tools_used") or []),
        "ms": result.get("total_ms"),
        "variant_learned": (result.get("variant_learned") or {}).get("id"),
        "passed": label == case.expected_class,
    }


# ── orchestration and reporting ──────────────────────────────────────


async def run_evals(suites=DEFAULT_SUITES, repeat: int = 3, only: Optional[List[str]] = None) -> Dict[str, Any]:
    cases = load_cases(only)
    results: List[Dict[str, Any]] = []
    for case in cases:
        for suite in suites:
            try:
                if suite == "classification":
                    results.append(await eval_classification(case, repeat))
                elif suite == "diagnosis":
                    results.append(await eval_diagnosis(case))
                elif suite == "e2e":
                    results.append(await eval_end_to_end(case))
            except Exception as exc:  # noqa: BLE001 — one broken case must not hide the rest
                results.append({"suite": suite, "case": case.id, "passed": False, "error": f"{type(exc).__name__}: {exc}"})

    from kairos_kb.llm.provider import model_name

    settings = get_settings()
    report = {
        "at": datetime.now(timezone.utc).isoformat(),
        "models": {"llm": model_name(), "jev": settings.typesafe_model or "jev-latest"},
        "suites": list(suites),
        "repeat": repeat,
        "results": results,
        "summary": _summary(results),
    }
    previous = _previous_report()
    report["regressions"] = _regressions(previous, report) if previous else []
    report["compared_with"] = previous["at"] if previous else None
    _write(report)
    return report


def _summary(results: List[Dict[str, Any]]) -> Dict[str, Any]:
    out = {}
    for suite in SUITES:
        rows = [r for r in results if r["suite"] == suite]
        if not rows:
            continue
        scored = [r for r in rows if not r.get("skipped")]
        out[suite] = {
            "passed": sum(1 for r in scored if r.get("passed")),
            "scored": len(scored),
            "skipped": len(rows) - len(scored),
        }
        if suite == "classification" and scored:
            out[suite]["mean_accuracy"] = round(statistics.mean(r.get("accuracy", 0) for r in scored), 3)
    return out


def _reports_dir() -> Path:
    return Path(get_settings().storage_base_path) / "evals"


def _previous_report() -> Optional[Dict[str, Any]]:
    files = sorted(_reports_dir().glob("*.json"))
    if not files:
        return None
    try:
        return json.loads(files[-1].read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return None


def _regressions(prev: Dict[str, Any], cur: Dict[str, Any]) -> List[str]:
    """What got worse since the previous report: pass→fail, lower accuracy, much slower."""
    key = lambda r: (r["suite"], r["case"])  # noqa: E731
    before = {key(r): r for r in prev.get("results", [])}
    found = []
    for r in cur["results"]:
        p = before.get(key(r))
        if not p or r.get("skipped") or p.get("skipped"):
            continue
        name = f"{r['suite']}/{r['case']}"
        if p.get("passed") and not r.get("passed"):
            found.append(f"{name}: passed before, fails now")
        if (r.get("accuracy") is not None and p.get("accuracy") is not None and r["accuracy"] < p["accuracy"]):
            found.append(f"{name}: accuracy {p['accuracy']} → {r['accuracy']}")
        for t in ("ms", "mean_latency_ms"):
            if r.get(t) and p.get(t) and r[t] > p[t] * SLOWDOWN_FACTOR:
                found.append(f"{name}: {t} {p[t]} → {r[t]} (>{SLOWDOWN_FACTOR}x slower)")
    return found


def _write(report: Dict[str, Any]) -> Path:
    d = _reports_dir()
    d.mkdir(parents=True, exist_ok=True)
    path = d / f"{report['at'][:19].replace(':', '-')}.json"
    path.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    report["path"] = str(path)
    return path


def format_report(report: Dict[str, Any]) -> str:
    lines = [f"Kairos agent evals — {report['at'][:19]}  (llm={report['models']['llm']}, jev={report['models']['jev']})", ""]
    for r in report["results"]:
        status = "SKIP" if r.get("skipped") else ("PASS" if r.get("passed") else "FAIL")
        line = f"  {status}  {r['suite']:<14} {r['case']:<22}"
        if r.get("skipped"):
            line += f" {r['reason'][:90]}"
        elif r["suite"] == "classification":
            line += (f" {r.get('predictions')} acc={r.get('accuracy')} conf={r.get('mean_confidence')}"
                     f" {r.get('mean_latency_ms')}ms")
        elif r["suite"] == "diagnosis":
            line += (f" variant={r.get('variant', '-')} tools={r.get('tool_calls', '-')} {r.get('ms', '-')}ms"
                     + (f"  ✗ {'; '.join(r.get('fact_problems') or [r.get('reason', '')])}" if not r.get("passed") else ""))
        elif r["suite"] == "e2e":
            line += f" mode={r.get('mode')} label={r.get('label')} tools={r.get('tool_calls')} {r.get('ms')}ms"
        if r.get("error"):
            line += f"  error: {r['error'][:120]}"
        lines.append(line)
    lines += ["", "  summary: " + json.dumps(report["summary"])]
    if report.get("compared_with"):
        lines.append(f"  compared with {report['compared_with'][:19]}: "
                     + ("no regressions" if not report["regressions"] else f"{len(report['regressions'])} regression(s)"))
        lines += [f"    ! {x}" for x in report["regressions"]]
    lines.append(f"  report: {report.get('path')}")
    return "\n".join(lines)
