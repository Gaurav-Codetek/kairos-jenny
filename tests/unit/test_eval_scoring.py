"""The evaluation harness's own scoring — an eval that scores wrongly is worse than none."""

from kairos_kb.agent.plan_library import column_diff
from kairos_kb.evals.runner import _regressions, check_facts, load_cases

RENAME = column_diff(["A", "SALES_QTY", "C"], ["A", "SOLD_QTY", "C"])
RENAME_PLUS_EXTRA = column_diff(["A", "SALES_QTY", "C"], ["A", "SOLD_QTY", "C", "NEW"])


def test_correct_diagnosis_meets_every_expectation():
    expect = {"counts": [3, 3], "renames": [["SALES_QTY", "SOLD_QTY"]], "no_other_extra": True}
    assert check_facts(RENAME, expect) == []


def test_each_wrong_fact_is_named():
    expect = {"counts": [3, 4], "renames": [["SALES_QTY", "UNITS"]], "extra_includes": ["NEW"]}
    problems = check_facts(RENAME, expect)
    assert any("counts [3, 3]" in p for p in problems)
    assert any("rename SALES_QTY → UNITS" in p for p in problems)
    assert any("extra columns not reported: ['new']" in p for p in problems)


def test_no_other_extra_catches_an_unexplained_column():
    problems = check_facts(RENAME_PLUS_EXTRA, {"renames": [["SALES_QTY", "SOLD_QTY"]], "no_other_extra": True})
    assert problems == ["unexpected extra columns: ['new']"]


def test_missing_diff_fails():
    assert check_facts(None, {}) == ["no column diff was computed"]


def test_regressions_are_detected_and_skips_ignored():
    prev = {"results": [
        {"suite": "diagnosis", "case": "a", "passed": True, "ms": 40000},
        {"suite": "classification", "case": "a", "passed": True, "accuracy": 1.0, "mean_latency_ms": 1500},
        {"suite": "diagnosis", "case": "b", "skipped": True},
    ]}
    cur = {"results": [
        {"suite": "diagnosis", "case": "a", "passed": False, "ms": 90000},
        {"suite": "classification", "case": "a", "passed": False, "accuracy": 0.667, "mean_latency_ms": 1600},
        {"suite": "diagnosis", "case": "b", "passed": False},
    ]}
    found = _regressions(prev, cur)
    assert "diagnosis/a: passed before, fails now" in found
    assert any(f.startswith("diagnosis/a: ms 40000 → 90000") for f in found)
    assert "classification/a: accuracy 1.0 → 0.667" in found
    assert not any("/b" in f for f in found)  # was skipped before: nothing to compare


def test_golden_set_is_well_formed():
    cases = load_cases()
    assert cases and len({c.id for c in cases}) == len(cases)
    for c in cases:
        assert c.expected_class in {"COLUMN_RENAME", "EXTRA_COLUMN", "COLUMN_ORDER_SWAP", "NOT_SCHEMA_RELATED"}
        assert c.diagnosable or c.note, f"{c.id}: say why it is not diagnosable"
