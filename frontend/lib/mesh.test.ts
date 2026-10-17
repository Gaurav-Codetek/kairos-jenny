import { describe, expect, it } from "vitest";

import {
  MeshIndex,
  bundleSummary,
  buildScene,
  defaultExpanded,
  labelPoint,
  layoutScene,
  roundedPath,
  LEAF_WIDTH,
  type Bundle,
  type Mesh,
  type Relationship,
  type ResourceType,
} from "@/lib/mesh";

// A small warehouse:  cat ─ bronze ─ raw, stg, t1..t4 (quiet)   pipe ─ load, xform
// Flow: raw → load → stg ;  stg → xform
function bundle(uid: string, resource_type: ResourceType, parent: string | null, extra: Partial<Bundle> = {}): Bundle {
  return {
    unique_id: uid, resource_type, name: uid.split(".").pop()!, fqn: uid.split(".").slice(2),
    entity_id: null, parent, children: {}, inherited: {}, ...extra,
  };
}

function rel(group: Relationship["group"], source: string, target: string, type = "X"): Relationship {
  return { relationship_id: `rel.${group}.${source}.${target}`, group, source, target, types: [type], origins: ["test"], confidence: null };
}

const B = {
  cat: "catalog.ws.cat",
  bronze: "schema.ws.cat.bronze",
  raw: "table.ws.cat.bronze.raw",
  stg: "table.ws.cat.bronze.stg",
  pipe: "pipeline.ws.1",
  load: "task.ws.1.load",
  xform: "task.ws.1.xform",
};
const QUIET = ["t1", "t2", "t3", "t4"].map((n) => `table.ws.cat.bronze.${n}`);

function mesh(): Mesh {
  const bundles = [
    bundle(B.cat, "catalog", null, { children: { schema: 1 } }),
    bundle(B.bronze, "schema", B.cat, { children: { table: 6 } }),
    bundle(B.raw, "table", B.bronze),
    bundle(B.stg, "table", B.bronze),
    ...QUIET.map((q) => bundle(q, "table", B.bronze)),
    bundle(B.pipe, "pipeline", null, { children: { task: 2 } }),
    bundle(B.load, "task", B.pipe),
    bundle(B.xform, "task", B.pipe),
  ];
  const relationships = [
    rel("containment", B.cat, B.bronze),
    ...[B.raw, B.stg, ...QUIET].map((t) => rel("containment", B.bronze, t)),
    rel("pipeline", B.pipe, B.load),
    rel("pipeline", B.pipe, B.xform),
    rel("flow", B.raw, B.load, "READS_TABLE"),
    rel("flow", B.load, B.stg, "WRITES_TABLE"),
    rel("flow", B.stg, B.xform, "READS_TABLE"),
    rel("depends_on", B.load, B.xform),
    // Job-level flow the agent also recorded, duplicating the task-level detail.
    rel("flow", B.pipe, B.stg, "WRITES_TABLE"),
  ];
  return { workspaces: [], bundles, relationships, stats: { bundles: {}, relationships: {}, inherited: { columns: 0, runs: 0, task_runs: 0 } } };
}

const edgeKeys = (edges: { source: string; target: string; group: string; count: number }[]) =>
  edges.map((e) => `${e.group}:${e.source}->${e.target}×${e.count}`).sort();

describe("visibility", () => {
  const idx = new MeshIndex(mesh());

  it("opens at the top level: catalogs and pipelines", () => {
    expect(Array.from(idx.visibleSet(new Set())).sort()).toEqual([B.cat, B.pipe].sort());
  });

  it("expanding shows children, and only below expanded parents", () => {
    const visible = idx.visibleSet(new Set([B.cat, B.bronze]));
    expect(visible.has(B.raw)).toBe(true);
    expect(visible.has(B.load)).toBe(false);
    // An expanded child under a collapsed parent stays hidden.
    expect(idx.visibleSet(new Set([B.bronze])).has(B.raw)).toBe(false);
  });

  it("finds the nearest visible ancestor", () => {
    expect(idx.visibleFor(B.raw, new Set([B.cat]))).toBe(B.cat);
    expect(idx.visibleFor(B.raw, new Set([B.cat, B.bronze]))).toBe(B.bronze);
  });
});

describe("roll-up", () => {
  const idx = new MeshIndex(mesh());
  const view = (expanded: string[]) => {
    const exp = new Set(expanded);
    return idx.visibleEdges(idx.visibleSet(exp), exp);
  };

  it("collapsed bundles still show how data moves between them, with a count", () => {
    // raw→load, load→stg, stg→xform and pipe→stg all live inside cat/pipe.
    expect(edgeKeys(view([]))).toEqual([
      `flow:${B.cat}->${B.pipe}×2`,
      `flow:${B.pipe}->${B.cat}×2`,
    ]);
    expect(view([]).every((e) => e.rolledUp)).toBe(true);
  });

  it("flow on an expanded bundle is dropped: its children carry the detail", () => {
    const keys = edgeKeys(view([B.pipe]));
    expect(keys).not.toContain(`flow:${B.pipe}->${B.cat}×2`);
    expect(keys).toContain(`pipeline:${B.pipe}->${B.load}×1`);
    expect(keys).toContain(`depends_on:${B.load}->${B.xform}×1`);
    expect(keys).toContain(`flow:${B.load}->${B.cat}×1`);
  });

  it("fully expanded shows the real edges, not rolled up", () => {
    const edges = view([B.cat, B.bronze, B.pipe]);
    expect(edgeKeys(edges.filter((e) => e.group === "flow"))).toEqual([
      `flow:${B.raw}->${B.load}×1`,
      `flow:${B.stg}->${B.xform}×1`,
      `flow:${B.load}->${B.stg}×1`,
    ]);
    expect(edges.some((e) => e.rolledUp)).toBe(false);
  });

  it("containment is drawn only between two visible bundles", () => {
    expect(view([]).some((e) => e.group === "containment")).toBe(false);
    expect(edgeKeys(view([B.cat]))).toContain(`containment:${B.cat}->${B.bronze}×1`);
  });
});

describe("scene", () => {
  const idx = new MeshIndex(mesh());
  const ids = (s: ReturnType<typeof buildScene>) => s.nodes.map((n) => n.id).sort();

  it("draws only lineage, never containment", () => {
    const s = buildScene(idx, new Set());
    expect(ids(s)).toEqual([B.cat, B.pipe].sort());
    expect(s.edges.every((e) => e.group !== "containment" && e.group !== "pipeline")).toBe(true);
  });

  it("opening a bundle replaces its card with the children that carry lineage", () => {
    const s = buildScene(idx, new Set([B.cat, B.bronze, B.pipe]));
    expect(ids(s)).toEqual([B.load, B.raw, B.stg, B.xform].sort()); // t1..t4 have no lineage
    const raw = s.nodes.find((n) => n.id === B.raw)!;
    expect(raw.openParent?.unique_id).toBe(B.bronze); // shown as the chip that closes it
  });

  it("a pinned bundle is drawn even without lineage", () => {
    const s = buildScene(idx, new Set([B.cat, B.bronze]), new Set([QUIET[0]]));
    expect(s.nodes.some((n) => n.id === QUIET[0])).toBe(true);
  });

  it("opens on the data flow by default — task order alone does not count", () => {
    expect(Array.from(defaultExpanded(idx)).sort()).toEqual([B.bronze, B.cat, B.pipe].sort());
    expect(defaultExpanded(idx, 2).size).toBe(0); // too much lineage: stay at the top level
  });

  it("ELK lays the flow out left to right", async () => {
    const s = buildScene(idx, new Set([B.cat, B.bronze, B.pipe]));
    const { boxes } = await layoutScene(s);
    s.nodes.forEach((n) => expect(boxes.get(n.id)?.width).toBe(LEAF_WIDTH));
    const x = (id: string) => boxes.get(id)!.x;
    expect(x(B.raw)).toBeLessThan(x(B.load)); // raw → load
    expect(x(B.load)).toBeLessThan(x(B.stg)); // load → stg
    expect(x(B.stg)).toBeLessThan(x(B.xform)); // stg → xform
  });

  it("every edge is routed, and no route crosses a card it does not connect", async () => {
    // A skip-layer edge (raw → xform) is the case that used to cut through cards.
    const m = mesh();
    m.relationships.push(rel("flow", B.raw, B.xform, "READS_TABLE"));
    const i = new MeshIndex(m);
    const s = buildScene(i, new Set([B.cat, B.bronze, B.pipe]));
    const { boxes, routes } = await layoutScene(s);
    for (const e of s.edges) {
      const pts = routes.get(e.id);
      expect(pts && pts.length >= 2).toBe(true);
      for (const [id, b] of boxes) {
        if (id === e.source || id === e.target) continue;
        for (let k = 1; k < pts!.length; k++) {
          const [p, q] = [pts![k - 1], pts![k]];
          // Orthogonal segments: test the segment's bounding box against the card, inset by 1px.
          const overlaps =
            Math.max(p.x, q.x) > b.x + 1 && Math.min(p.x, q.x) < b.x + b.width - 1 &&
            Math.max(p.y, q.y) > b.y + 1 && Math.min(p.y, q.y) < b.y + b.height - 1;
          expect(overlaps, `${e.id} crosses ${id}`).toBe(false);
        }
      }
    }
  });

  it("draws routes with rounded corners and labels on the longest run", () => {
    const pts = [{ x: 0, y: 0 }, { x: 100, y: 0 }, { x: 100, y: 40 }, { x: 300, y: 40 }];
    const d = roundedPath(pts, 10);
    expect(d.startsWith("M 0 0 L 90 0 Q 100 0 100 10")).toBe(true);
    expect(d.endsWith("L 300 40")).toBe(true);
    expect(labelPoint(pts)).toEqual({ x: 200, y: 40 });
  });
});

describe("search and summaries", () => {
  const idx = new MeshIndex(mesh());

  it("ranks exact, then prefix, then substring matches", () => {
    expect(idx.search("stg").map((b) => b.unique_id)[0]).toBe(B.stg);
    expect(idx.search("x")).toEqual([]); // needs two characters
    expect(idx.search("xfo").map((b) => b.unique_id)).toEqual([B.xform]);
  });

  it("summarises what a bundle holds and inherits", () => {
    expect(bundleSummary(bundle(B.raw, "table", B.bronze, { inherited: { columns: 51 }, format: "DELTA" }))).toBe("51 cols · DELTA");
    expect(bundleSummary(bundle(B.pipe, "pipeline", null, { children: { task: 7 }, inherited: { runs: 39 } }))).toBe("7 tasks · 39 runs");
    expect(bundleSummary(bundle(B.load, "task", B.pipe, { inherited: { task_runs: 1 }, task_type: "notebook_task" }))).toBe("1 run · notebook");
    expect(bundleSummary(bundle(B.cat, "catalog", null))).toBe("no schemas");
  });
});
