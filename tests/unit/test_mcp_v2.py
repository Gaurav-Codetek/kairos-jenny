"""The v2 MCP server: 14 non-overlapping tools beside v1's 20, over the same implementations."""

import asyncio

from kairos_kb.mcp_server import server as v1
from kairos_kb.mcp_server import server_v2 as v2


def _names(server):
    tools = asyncio.run(server.list_tools())
    return [t.name for t in getattr(tools, "tools", tools)]


def test_v2_exposes_exactly_its_consolidated_tools():
    assert sorted(_names(v2.server)) == sorted(v2.TOOL_NAMES)
    assert len(v2.TOOL_NAMES) == 14


def test_v1_is_unchanged_beside_v2():
    names = _names(v1.server)
    assert len(names) == 20
    assert {"search_entities", "get_entity", "explore_entity", "get_blast_radius"} <= set(names)


def test_live_platform_tools_keep_their_own_approval_labels():
    listed = asyncio.run(v2.server.list_tools())
    tools = {t.name: t for t in getattr(listed, "tools", listed)}
    for name in ("run_sql", "check_key_uniqueness", "volume_files"):
        assert tools[name].annotations.open_world_hint is True
    assert tools["report_context_issue"].annotations.read_only_hint is False
    assert tools["find"].annotations.read_only_hint is True


def test_v2_reuses_v1_implementations_without_their_audit_wrapper():
    raw = v2._raw(v1.get_blast_radius)
    assert raw is not v1.get_blast_radius and raw.__name__ == "get_blast_radius"


def test_trace_rejects_an_unknown_direction():
    out = asyncio.run(v2._raw(v2.trace)("table:ws:c.s.t", direction="sideways"))
    assert "error" in out
