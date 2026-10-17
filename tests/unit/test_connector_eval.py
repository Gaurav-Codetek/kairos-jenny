"""Connector evaluations: the question bank, deterministic scoring, pipeline ordering."""

from kairos_kb.evals.connector_eval import CONNECTORS, load_questions, mention_score
from kairos_kb.evals.question_bank import _ordered


def test_question_bank_loads_with_unique_ids_and_references():
    qs = load_questions()
    assert len(qs) >= 100
    assert len({q["id"] for q in qs}) == len(qs)
    assert all(q["question"] and q["category"] for q in qs)
    assert {"curated", "generated"} <= {q["source"] for q in qs}


def test_both_connectors_are_evaluated():
    assert CONNECTORS == {"v1": "/mcp/", "v2": "/mcp-v2/"}


def test_mentions_need_one_phrase_from_every_group():
    groups = [["fct_ics_867"], ["return", "returned"]]
    assert mention_score("Use FCT_ICS_867 and subtract returns", groups)["score"] == 1.0
    partial = mention_score("Use fct_ics_867", groups)
    assert partial["score"] == 0.5 and partial["missing"] == ["return | returned"]
    assert mention_score("anything", [])["score"] == 1.0
    assert mention_score("x", ["single"])["missing"] == ["single"]  # a bare string is one group


def test_pipeline_tasks_are_ordered_by_dependency():
    tasks = [{"task_key": "fct_to_bi", "depends_on": ["stg_to_fct"]},
             {"task_key": "raw", "depends_on": []},
             {"task_key": "stg_to_fct", "depends_on": ["raw"]}]
    assert _ordered(tasks) == ["raw", "stg_to_fct", "fct_to_bi"]
    # A cycle does not hang: the rest come back in name order.
    assert _ordered([{"task_key": "a", "depends_on": ["b"]}, {"task_key": "b", "depends_on": ["a"]}]) == ["a", "b"]
