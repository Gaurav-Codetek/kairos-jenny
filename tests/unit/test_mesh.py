"""Mesh building rules: flow direction, ids, dedupe, and folding sub-grains into bundles."""

import pytest

from kairos_kb.warehouse.mesh import _VOLUME_PATH, MeshBuilder, _bundle_for, _depends_on_keys, _flow

# (verb, source type, target type) → expected (reverse?, group), or None when it is not flow.
# "reverse" flips the stored edge so it runs in data-flow direction.
FLOW_CASES = [
    # a dataset flows INTO the processor that reads it — whichever way the agent stored it
    (("READS_TABLE", "task", "table"), (True, "flow")),
    (("READ_BY_TASK", "table", "task"), (False, "flow")),
    (("READ_BY_TASK", "task", "table"), (True, "flow")),
    (("READS_VOLUME_FILE", "task", "volume"), (True, "flow")),
    (("READ_BY_JOB", "pipeline", "table"), (True, "flow")),
    # a processor flows INTO the dataset it writes
    (("WRITES_TABLE", "task", "table"), (False, "flow")),
    (("WRITTEN_BY_TASK", "table", "task"), (True, "flow")),
    (("CREATED_BY_JOB", "table", "pipeline"), (True, "flow")),
    # table → table
    (("DERIVES_FROM", "table", "table"), (True, "flow")),
    (("FEEDS_TABLE", "table", "table"), (False, "flow")),
    (("TRANSFORMS_TO", "table", "table"), (False, "flow")),
    (("STORED_AT", "table", "volume"), (True, "storage")),
    # task order
    (("DEPENDS_ON_TASK", "task", "task"), (True, "depends_on")),
    # not flow: stays out of the mesh
    (("MENTIONS_IN_LOG", "table", "table"), None),
    (("LIKELY_VARIANT_OF", "table", "table"), None),
    (("PART_OF_JOB", "task", "pipeline"), None),
    (("SHARES_NOTEBOOK_WITH", "task", "task"), None),
    (("GATES_LAYER_FOR", "task", "table"), None),
]


@pytest.mark.parametrize("case,expected", FLOW_CASES)
def test_discovered_verbs_normalise_to_data_flow(case, expected):
    assert _flow(*case) == expected


def test_depends_on_keys_accepts_both_shapes():
    assert _depends_on_keys(["a", {"task_key": "b"}, {"other": 1}]) == ["a", "b"]
    assert _depends_on_keys(None) == []


def test_volume_path_parsing():
    m = _VOLUME_PATH.match("/Volumes/cat/sch/vol/config/map.csv")
    assert m.groups()[:3] == ("cat", "sch", "vol")
    assert _VOLUME_PATH.match("abfss://container@account.dfs.core.windows.net/tables/x") is None


def _mesh():
    m = MeshBuilder()
    cat = m.add("catalog", "ws", ["Cat"], name="Cat", entity_id="catalog:WS:Cat", parent=None)
    sch = m.add("schema", "ws", ["Cat", "bronze"], name="bronze", entity_id="schema:WS:Cat.bronze", parent=cat)
    tbl = m.add("table", "ws", ["Cat", "bronze", "raw"], name="raw", entity_id="table:WS:Cat.bronze.raw", parent=sch)
    vol = m.add("volume", "ws", ["Cat", "bronze", "vol"], name="vol", entity_id=None, parent=sch)
    return m, cat, sch, tbl, vol


def test_unique_ids_are_dbt_style():
    _, cat, sch, tbl, vol = _mesh()
    assert (cat, sch, tbl, vol) == ("catalog.ws.cat", "schema.ws.cat.bronze", "table.ws.cat.bronze.raw",
                                    "volume.ws.cat.bronze.vol")


def test_relationships_dedupe_and_merge_their_evidence():
    m, _, _, tbl, vol = _mesh()
    m.relate("storage", "STORED_AT", vol, tbl, "discovered", confidence=0.6)
    m.relate("storage", "STORED_AT_VOLUME", vol, tbl, "discovered", confidence=0.9)
    m.relate("storage", "STORED_AT", vol, tbl, "lineage")
    assert len(m.rels) == 1
    rel = next(iter(m.rels.values()))
    assert rel["types"] == ["STORED_AT", "STORED_AT_VOLUME"]
    assert rel["origins"] == ["discovered", "lineage"]
    assert rel["confidence"] == 0.9
    assert rel["relationship_id"].startswith("rel.")


def test_self_loops_and_unknown_bundles_are_dropped():
    m, _, _, tbl, _ = _mesh()
    m.relate("flow", "X", tbl, tbl, "discovered")
    m.relate("flow", "X", tbl, "table.ws.nowhere", "discovered")
    assert m.rels == {}


def test_sub_grains_map_onto_their_bundle():
    m, _, _, tbl, vol = _mesh()
    assert _bundle_for(m, "column:WS:Cat.bronze.raw.amount") == tbl       # columns fold into the table
    assert _bundle_for(m, "file:ws:/Volumes/Cat/bronze/vol/config/map.csv") == vol  # files into the volume
    assert _bundle_for(m, "notebook:WS:/Users/x/nb") is None               # not a bundle kind
