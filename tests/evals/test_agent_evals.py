"""Agent evaluations as pass/fail gates — opt-in: `pytest -m eval`.

These call live Databricks, TypeSafe and Azure OpenAI. For the full scored
report (and comparison with the previous run) use `python -m kairos_kb.evals`.
"""

import pytest

from kairos_kb.evals.runner import eval_classification, eval_diagnosis, load_cases

pytestmark = pytest.mark.eval

CASES = load_cases()


@pytest.mark.parametrize("case", CASES, ids=[c.id for c in CASES])
async def test_jev_classifies_golden_incident(case):
    result = await eval_classification(case, repeat=3)
    assert not result["errors"], result["errors"]
    # Allow one miss in three; a coin-flip classifier would fail this.
    assert result["accuracy"] >= 2 / 3, result


@pytest.mark.parametrize("case", [c for c in CASES if c.diagnosable], ids=[c.id for c in CASES if c.diagnosable])
async def test_agent_b_diagnoses_golden_incident(case):
    result = await eval_diagnosis(case)
    assert result["passed"], result
