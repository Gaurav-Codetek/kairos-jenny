import { afterEach, describe, expect, it, vi } from "vitest";

import { hiddenChannel, hiddenEntity, prepare, scrub } from "./visibility";

const ICS = { id: "ics-id", name: "ICS Sales Warehouse" };
const ZOMATO = { id: "zom-id", name: "Zomato Snowflake" };

describe("hidden connections", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("know a hidden connection's entities, bundles and agent channel", () => {
    expect(hiddenEntity("table:ICS Sales Warehouse:cat.silver.sales")).toBe(true);
    expect(hiddenEntity("catalog.ics_sales_warehouse.samples")).toBe(true);
    expect(hiddenEntity("table:Zomato Snowflake:ZOMATO.MARTS.FCT_ORDERS")).toBe(false);
    expect(hiddenEntity("rel.a2994a8ea935")).toBe(false);
    expect(hiddenChannel("mcp:ics-sales-warehouse")).toBe(true);
    expect(hiddenChannel("mcp")).toBe(false);
  });

  it("take them out of every list, by name, id, entity or owning workspace", async () => {
    expect(await scrub("/workspaces", "GET", [ICS, ZOMATO])).toEqual([ZOMATO]);
    const runs = await scrub("/enrichment/runs", "GET", { runs: [{ workspace_id: "ics-id" }, { workspace_id: "zom-id" }] });
    expect(runs.runs).toEqual([{ workspace_id: "zom-id" }]);
    const targets = await scrub("/enrichment/targets", "GET", {
      count: 2,
      targets: [{ entity_id: "catalog:ICS Sales Warehouse:x" }, { entity_id: "catalog:Zomato Snowflake:ZOMATO" }],
    });
    expect(targets).toEqual({ count: 1, targets: [{ entity_id: "catalog:Zomato Snowflake:ZOMATO" }] });
    const activity = await scrub("/agents/activity", "GET", { activity: [{ channel: "mcp:ics-sales-warehouse" }, { channel: "mcp" }] });
    expect(activity.activity).toEqual([{ channel: "mcp" }]);
  });

  it("take a hidden connection's calls out of the agent totals", async () => {
    const s = await scrub("/agents/stats", "GET", {
      calls: 100, errors: 4, error_rate: 0.04,
      by_channel: { mcp: { calls: 60, errors: 1 }, "mcp:ics-sales-warehouse": { calls: 40, errors: 3 } },
      most_requested: [{ entity_id: "table:ICS Sales Warehouse:t" }],
    });
    expect(s).toMatchObject({ calls: 60, errors: 1, by_channel: { mcp: { calls: 60, errors: 1 } }, most_requested: [] });
  });

  it("keep the mesh whole for what's left: no relationship to a hidden bundle", async () => {
    const m = await scrub("/mesh", "GET", {
      workspaces: [{ ...ICS, slug: "ics_sales_warehouse" }, { ...ZOMATO, slug: "zomato_snowflake" }],
      bundles: [
        { unique_id: "catalog.ics_sales_warehouse.samples", resource_type: "catalog" },
        { unique_id: "catalog.zomato_snowflake.zomato", resource_type: "catalog" },
        { unique_id: "schema.zomato_snowflake.zomato.marts", resource_type: "schema" },
      ],
      relationships: [
        { source: "catalog.zomato_snowflake.zomato", target: "schema.zomato_snowflake.zomato.marts", group: "containment" },
        { source: "catalog.ics_sales_warehouse.samples", target: "schema.zomato_snowflake.zomato.marts", group: "flow" },
      ],
      stats: {},
    });
    expect(m.bundles.map((b) => b.unique_id)).toEqual(["catalog.zomato_snowflake.zomato", "schema.zomato_snowflake.zomato.marts"]);
    expect(m.relationships).toHaveLength(1);
    expect(m.stats).toMatchObject({ bundles: { catalog: 1, schema: 1 }, relationships: { containment: 1 } });
  });

  it("ask for totals on the visible connections only", async () => {
    await scrub("/workspaces", "GET", [ICS, ZOMATO]);
    expect(await prepare("/warehouse/map", "GET")).toBe("/warehouse/map?workspace_id=zom-id");
    expect(await prepare("/enrichment/discovered?limit=5", "GET")).toBe("/enrichment/discovered?limit=5&workspace_id=zom-id");
    expect(await prepare("/companion/pulse?workspace_id=zom-id", "GET")).toBe("/companion/pulse?workspace_id=zom-id");
  });
});
