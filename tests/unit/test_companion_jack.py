"""Jack: only the data products and the live pulse, with the browser's arguments turned into Kairos's."""

import json

from kairos_kb.companion import jack


async def test_jack_sees_only_data_products_and_the_live_pulse(monkeypatch):
    called = []

    async def call_tool(workspace_id, name, args):
        called.append((name, args))
        return {"ok": True}

    monkeypatch.setattr("kairos_kb.companion.chat.call_tool", call_tool)
    for name in ("report_gap", "notebook", "moments"):
        assert "error" in json.loads(await jack.run_tool("w", name, {}))
    assert called == []
    assert {c["name"] for c in jack.TOOL_CONFIGS} == set(jack.TOOLS) == {"pulse_now", "list_products", "query",
                                                                        "compare_to_normal"}


async def test_the_agents_string_arguments_become_kairos_arguments(monkeypatch):
    seen = {}

    async def call_tool(workspace_id, name, args):
        seen[name] = args
        return {"rows": []}

    monkeypatch.setattr("kairos_kb.companion.chat.call_tool", call_tool)
    await jack.run_tool("w", "query", {"product": "Sales", "metrics": "gmv, orders", "by": "city",
                                       "filters": '[{"dimension": "city", "op": "=", "value": "Pune"}]', "limit": "5"})
    assert seen["query"] == {"product": "Sales", "metrics": ["gmv", "orders"], "by": ["city"],
                             "filters": [{"dimension": "city", "op": "=", "value": "Pune"}], "order": "", "limit": 5}
    await jack.run_tool("w", "compare_to_normal", {"product": "Sales", "metric": "gmv", "hours": "5, 6"})
    assert seen["compare_to_normal"]["hours"] == [5, 6]
    assert "error" in json.loads(await jack.run_tool("w", "query", {"product": "Sales", "metrics": "gmv", "filters": "not json"}))
