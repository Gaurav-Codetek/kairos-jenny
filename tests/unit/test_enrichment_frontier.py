"""The enrichment frontier: what a seed reaches, and on what evidence.

The cases are the ICS Sales Warehouse run that queued 10 of 29 items off
target — 7 tables via stale "raw_ingestion writes …" links, a schema and a
catalog via containment verbs, a sibling via a name guess.
"""

from types import SimpleNamespace

from kairos_kb.enrichment.context import KIND_PRIORITY
from kairos_kb.enrichment.pipeline import contradicted_writes, pipeline_job_id
from kairos_kb.enrichment.runner import evidence_candidates, judge_stored_link

WS = "ws"
JOB = f"job:{WS}:572339974626818"
TASK = f"task:{WS}:572339974626818:raw_ingestion"
CALLS = "table:nexora.bronze.calls"
RAW_867 = "table:nexora.bronze.raw_ics_867"


def judge(kind, entity_id, source, target, verb, status="proposed", corroborated=()):
    return judge_stored_link(kind, entity_id, source, target, verb, status, set(corroborated))


# ── stored links ──

def test_a_proposed_write_with_no_evidence_is_not_followed_but_noted():
    other, reason, note = judge("task", TASK, TASK, CALLS, "WRITES_TABLE")
    assert other == CALLS and reason is None
    assert "calls" in note and "proposed" in note


def test_a_verified_write_is_followed():
    _, reason, _ = judge("job", JOB, JOB, RAW_867, "WRITES_TABLE", status="verified")
    assert reason == "WRITES_TABLE · verified"


def test_a_proposed_write_corroborated_by_this_runs_code_scan_is_followed():
    _, reason, _ = judge("task", TASK, TASK, RAW_867, "WRITES_TABLE", corroborated={RAW_867})
    assert reason == "WRITES_TABLE · corroborated"


def test_a_contradicted_link_is_silently_ignored():
    _, reason, note = judge("task", TASK, TASK, CALLS, "WRITES_TABLE", status="contradicted")
    assert reason is None and note is None


def test_containment_and_guesses_are_never_followed_even_when_verified():
    for verb in ("BELONGS_TO_SCHEMA", "PART_OF_CATALOG", "POSSIBLE_SIBLING", "DEPENDS_ON", "RUNS_NOTEBOOK"):
        _, reason, note = judge("table", CALLS, CALLS, "schema:nexora.bronze", verb, status="verified")
        assert reason is None and note is None, verb


def test_a_passive_verb_is_followed_by_its_meaning():
    # "raw_ics_867 WRITTEN_BY task" from the table seed reaches the task.
    other, reason, _ = judge("table", RAW_867, RAW_867, TASK, "WRITTEN_BY", status="verified")
    assert other == TASK and reason.startswith("WRITES_TABLE")


def test_a_table_seed_does_not_reach_sibling_tables():
    _, reason, _ = judge("table", RAW_867, RAW_867, CALLS, "FEEDS", status="verified")
    assert reason is None


def test_a_pipeline_reaches_only_tables_through_stored_links():
    _, reason, _ = judge("job", JOB, JOB, f"job:{WS}:1", "TRIGGERS", status="verified")
    assert reason is None


# ── this run's evidence ──

def test_a_tasks_code_queues_what_it_reads_and_writes_with_the_line():
    facts = {"tables_in_code": [
        {"table": "nexora.bronze.raw_ics_867", "entity_id": RAW_867, "modes": ["write"], "lines": [142]},
        {"table": "nexora.meta.ingestion", "entity_id": "table:nexora.meta.ingestion", "modes": ["read"], "lines": [12]},
        {"table": "nexora.bronze.calls", "entity_id": CALLS, "modes": ["named"], "lines": [30]},
    ]}
    out, notes = evidence_candidates("task", 1, facts)
    assert out == [(RAW_867, "WRITES_TABLE · code line 142"),
                   ("table:nexora.meta.ingestion", "READS_TABLE · code line 12")]
    assert len(notes) == 1 and "only named" in notes[0]


def test_a_table_seed_queues_its_history_writers_but_not_people():
    facts = {"writers": [
        {"entity_id": JOB, "linkable": True},
        {"writer": "interactive notebook session by a@b.com", "linkable": False},
    ]}
    out, _ = evidence_candidates("table", 0, facts)
    assert out == [(JOB, "WRITES_TABLE · Delta history")]


def test_a_reached_table_does_not_climb_upstream_unless_asked():
    facts = {"writers": [{"entity_id": JOB, "linkable": True}]}
    assert evidence_candidates("table", 2, facts)[0] == []
    assert evidence_candidates("table", 2, facts, include_upstream_producers=True)[0] == [
        (JOB, "WRITES_TABLE · Delta history")]


def test_tasks_are_profiled_before_tables():
    # A task's code is the evidence its tables are reached on.
    assert KIND_PRIORITY["task"] < KIND_PRIORITY["table"]


# ── contradicted links ──

def rel(source, target, verb="WRITES_TABLE", status="proposed"):
    return SimpleNamespace(source_entity_id=source, target_entity_id=target, relation_type=verb, status=status)


def test_pipeline_job_id():
    assert pipeline_job_id(JOB) == "572339974626818"
    assert pipeline_job_id(TASK) == "572339974626818"
    assert pipeline_job_id(CALLS) is None


def test_a_write_by_a_job_history_never_saw_is_contradicted():
    facts = {"history_available": True, "writers": [{"job_id": 222032016169138}]}
    bad = rel(TASK, CALLS)
    good = rel(f"task:{WS}:222032016169138:validate", CALLS)
    assert contradicted_writes([bad, good], facts, CALLS) == [bad]


def test_passive_writes_are_judged_too():
    facts = {"history_available": True, "writers": []}
    passive = rel(CALLS, TASK, verb="WRITTEN_BY")
    assert contradicted_writes([passive], facts, CALLS) == [passive]


def test_nothing_is_contradicted_without_history_or_when_verified_or_a_read():
    no_history = {"history_available": False}
    assert contradicted_writes([rel(TASK, CALLS)], no_history, CALLS) == []
    facts = {"history_available": True, "writers": []}
    assert contradicted_writes([rel(TASK, CALLS, status="verified")], facts, CALLS) == []
    assert contradicted_writes([rel(TASK, CALLS, verb="READS_TABLE")], facts, CALLS) == []
    # A write *to another table* from this one is not this table's writer.
    assert contradicted_writes([rel(CALLS, "table:x.y.z")], facts, CALLS) == []


# ── code scan: a catalog the code never spells out ──

def test_a_catalog_placeholder_resolves_on_a_unique_schema_and_table():
    from kairos_kb.enrichment.pipeline import scan_code

    known = {
        "nexora.bronze.comm_table_log": "table:ws:nexora.bronze.comm_table_log",
        "a.logs.run_log": "table:ws:a.logs.run_log",
        "b.logs.run_log": "table:ws:b.logs.run_log",
    }
    code = (
        'dw_catalog = dbutils.widgets.get("catalog")\n'
        'log_df.write.mode("append").saveAsTable(f"{dw_catalog}.bronze.comm_table_log")\n'
        'spark.table(f"{dw_catalog}.logs.run_log")\n'
    )
    found = scan_code(code, known)["tables_in_code"]
    # comm_table_log is unique across catalogs; run_log is ambiguous, so not guessed.
    assert [(t["table"], t["modes"], t["lines"]) for t in found] == [
        ("nexora.bronze.comm_table_log", ["write"], [2])]
