"""The variant store: lifecycle, lookup, and what Jev may choose from."""

from kairos_kb.agent import playbooks

PLAN = [{"id": "report", "type": "report", "name": "report", "args": {"facts": {}}}]


def _create(variant="Notebook compares a CSV header to a mapping file", cls="EXTRA_COLUMN"):
    return playbooks.create(failure_class=cls, variant=variant, plan=PLAN, learned_from_run="r-1",
                            dry_run={"ms": 1000, "tool_calls": 4})


def test_new_variant_is_a_draft_on_disk(playbook_store):
    v = _create()
    assert v["status"] == "draft" and v["trusted"] is False
    assert (playbook_store / "EXTRA_COLUMN" / f"{v['id']}.yaml").exists()
    assert [x["id"] for x in playbooks.variants_for("EXTRA_COLUMN")] == [v["id"]]


def test_variants_are_filed_strictly_by_class(playbook_store):
    _create(cls="EXTRA_COLUMN")
    rename = _create(cls="COLUMN_RENAME")
    assert [x["id"] for x in playbooks.variants_for("COLUMN_RENAME")] == [rename["id"]]
    assert playbooks.variants_for("COLUMN_ORDER_SWAP") == []


def test_promoted_after_repeated_success(playbook_store):
    v = _create()
    for _ in range(playbooks.PROMOTE_AFTER - 1):
        v = playbooks.record_outcome(v, success=True, ms=40000)
        assert v["status"] == "draft"
    v = playbooks.record_outcome(v, success=True, ms=40000)
    assert v["status"] == "proven"


def test_retired_after_consecutive_failures_and_hidden_from_jev(playbook_store):
    v = _create()
    for _ in range(playbooks.RETIRE_AFTER):
        v = playbooks.record_outcome(v, success=False, ms=1000, failure="verify failed")
    assert v["status"] == "retired"
    assert playbooks.variants_for("EXTRA_COLUMN") == []
    assert len(playbooks.load_all("EXTRA_COLUMN")) == 1  # kept on disk for inspection


def test_a_success_resets_the_failure_streak(playbook_store):
    v = _create()
    for _ in range(playbooks.RETIRE_AFTER - 1):
        v = playbooks.record_outcome(v, success=False, ms=1000, failure="x")
    v = playbooks.record_outcome(v, success=True, ms=1000)
    v = playbooks.record_outcome(v, success=False, ms=1000, failure="x")
    assert v["status"] != "retired" and v["stats"]["consecutive_failures"] == 1


def test_trusted_variants_are_never_retired(playbook_store):
    v = _create()
    v["trusted"] = True
    playbooks.save(v)
    for _ in range(playbooks.RETIRE_AFTER + 2):
        v = playbooks.record_outcome(v, success=False, ms=1000, failure="x")
    assert v["status"] != "retired"
    assert playbooks.variants_for("EXTRA_COLUMN")


def test_files_in_older_formats_are_ignored(playbook_store):
    (playbook_store / "EXTRA_COLUMN").mkdir(parents=True)
    (playbook_store / "EXTRA_COLUMN" / "old.yaml").write_text("id: old\nclass: EXTRA_COLUMN\nsteps: [a, b]\n")
    (playbook_store / "EXTRA_COLUMN" / "broken.yaml").write_text("id: [unclosed\n")
    assert playbooks.load_all() == []


def test_summary_lists_plan_nodes_not_args(playbook_store):
    s = playbooks.summary(_create())
    assert s["plan"] == [{"id": "report", "type": "report", "name": "report"}]
    assert playbooks.summary(None) is None
