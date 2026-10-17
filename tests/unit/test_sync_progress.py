"""Live sync progress: what the Connections screen polls while a sync runs."""

import uuid

from kairos_kb.ingestion import progress as sync_progress
from kairos_kb.ingestion.progress import NullProgress, SyncProgress


def test_a_sync_reports_phases_steps_counts_and_a_log():
    p = SyncProgress(uuid.uuid4(), {"run_limit": 25})
    p.phase_start("catalog", "Catalog: catalogs, schemas, tables and columns")
    p.set_step("Reading tables in nexora.bronze", index=2, total=7, unit="schema in nexora")
    p.bump("tables", 3)
    p.bump("columns", 40)
    p.phase_end("catalog", 43)
    p.phase_skip("lineage", "skip lineage was selected")

    snap = p.snapshot()
    assert snap["status"] == "running"
    assert snap["phases"]["catalog"]["status"] == "completed"
    assert snap["phases"]["catalog"]["items"] == 43
    assert snap["phases"]["jobs"]["status"] == "pending"
    assert snap["phases"]["lineage"]["status"] == "skipped"
    assert snap["counts"] == {"tables": 3, "columns": 40}
    # Newest first, so the panel shows the latest line on top.
    assert snap["log"][0]["message"].startswith("Lineage skipped")
    assert snap["server_now"]


def test_a_position_is_only_set_when_the_total_is_known():
    p = SyncProgress(uuid.uuid4(), {})
    p.set_step("Listing jobs")
    assert p.snapshot()["position"] is None
    p.set_step("ICS: tasks", index=4, total=12, unit="job")
    assert p.snapshot()["position"] == {"index": 4, "total": 12, "unit": "job"}


def test_finish_and_fail_are_terminal_states():
    ok = SyncProgress(uuid.uuid4(), {})
    ok.finish({"catalog": {"tables": 3}})
    assert ok.snapshot()["status"] == "completed" and ok.snapshot()["finished_at"]
    bad = SyncProgress(uuid.uuid4(), {})
    bad.fail("token expired")
    assert bad.snapshot()["status"] == "failed" and bad.snapshot()["error"] == "token expired"
    assert bad.snapshot()["log"][0]["level"] == "error"


def test_the_log_is_bounded():
    p = SyncProgress(uuid.uuid4(), {})
    for i in range(500):
        p.note(f"line {i}")
    assert len(p.snapshot()["log"]) == 80


def test_a_sync_nobody_watches_reports_into_nothing():
    n = NullProgress()
    n.phase_start("catalog", "x")
    n.set_step("y", index=1, total=2)
    n.bump("tables")
    n.note("z")
    n.phase_end("catalog", 1)


def test_latest_is_per_workspace_and_not_running_without_a_task():
    ws = uuid.uuid4()
    assert sync_progress.latest(ws) is None
    p = sync_progress.begin(ws, {})
    assert sync_progress.latest(ws) is p
    assert not sync_progress.is_running(ws)  # no task attached


# ── choosing pipelines to sync ──

def test_pipelines_are_chosen_by_name_or_id_case_insensitively():
    from kairos_kb.ingestion.job_sync import select_jobs

    jobs = [
        {"job_id": 572339974626818, "settings": {"name": "ICS Sales Warehouse"}},
        {"job_id": 222032016169138, "settings": {"name": "schema_validation_test"}},
        {"job_id": 1, "settings": {"name": "chat"}},
    ]
    chosen, unmatched = select_jobs(jobs, [" ics sales warehouse ", "222032016169138", "no_such_job"])
    assert [j["job_id"] for j in chosen] == [572339974626818, 222032016169138]
    assert unmatched == ["no_such_job"]


def test_a_blank_pipeline_filter_means_every_pipeline():
    from kairos_kb.ingestion.job_sync import select_jobs

    jobs = [{"job_id": 1, "settings": {"name": "a"}}]
    assert select_jobs(jobs, None) == (jobs, [])
    assert select_jobs(jobs, ["", "  "]) == (jobs, [])
