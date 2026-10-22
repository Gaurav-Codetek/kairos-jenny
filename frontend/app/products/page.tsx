"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { Cpu, Layers, Plus } from "lucide-react";

import { EmptyState, Segmented, Spinner } from "@/components/kairos/ds";
import { PageHeader } from "@/components/shell/app-shell";
import { BuildProgress, CreateDialog } from "@/components/products/create-dialog";
import { EnginePanel, EngineStart } from "@/components/products/engine-panel";
import { ProductDrawer } from "@/components/products/product-drawer";
import { ProductGraph, type GraphMode } from "@/components/products/product-graph";
import { listWorkspaces, type Workspace } from "@/lib/connections";
import {
  getBuild,
  getEngine,
  latestEngine,
  runEngine,
  getProduct,
  listProducts,
  rebuildProduct,
  startProduct,
  type Build,
  type EngineRun,
  type Product,
  type ProductSummary,
} from "@/lib/products";

const LEGEND = [
  ["var(--brand)", "fact input"],
  ["var(--ok-dot)", "aggregate (fast path)"],
  ["var(--warn-dot)", "dimension input"],
];

export default function ProductsPage() {
  const [workspaces, setWorkspaces] = useState<Workspace[]>([]);
  const [workspaceId, setWorkspaceId] = useState<string | null>(null);
  const [products, setProducts] = useState<ProductSummary[] | null>(null);
  const [mode, setMode] = useState<GraphMode>("lineage");
  const [selected, setSelected] = useState<string | null>(null);
  const [product, setProduct] = useState<Product | null>(null);
  const [creating, setCreating] = useState(false);
  const [build, setBuild] = useState<Build | null>(null);
  const [engine, setEngine] = useState<EngineRun | null>(null);
  const [startingEngine, setStartingEngine] = useState(false);

  useEffect(() => {
    listWorkspaces()
      .then((ws) => {
        setWorkspaces(ws);
        setWorkspaceId((cur) => cur ?? ws[0]?.id ?? null);
      })
      .catch(() => setWorkspaces([]));
  }, []);

  const load = useCallback(() => {
    if (!workspaceId) return Promise.resolve();
    return listProducts(workspaceId)
      .then((r) => setProducts(r.products))
      .catch(() => setProducts([]));
  }, [workspaceId]);

  useEffect(() => {
    load();
  }, [load]);

  // Pick up an engine run that is still going (or just finished) for this connection.
  useEffect(() => {
    if (!workspaceId) return;
    latestEngine(workspaceId)
      .then((r) => setEngine(r && (r.status === "running" || Date.now() - Date.parse(r.started_at) < 15 * 60_000) ? r : null))
      .catch(() => undefined);
  }, [workspaceId]);

  // Follow the engine; reload the graph each time it finishes a product.
  const builtCount = engine?.proposals.filter((p) => p.status === "built").length ?? 0;
  useEffect(() => {
    if (!engine || engine.status !== "running") return;
    const t = window.setInterval(async () => {
      const r = await getEngine(engine.id).catch(() => null);
      if (r) setEngine(r);
    }, 2000);
    return () => window.clearInterval(t);
  }, [engine]);
  useEffect(() => {
    if (builtCount > 0 || engine?.status === "completed") load();
  }, [builtCount, engine?.status, load]);

  useEffect(() => {
    if (selected) getProduct(selected).then(setProduct).catch(() => setProduct(null));
  }, [selected]);

  // Follow a running build until it ends.
  useEffect(() => {
    if (!build || build.status !== "running") return;
    const t = window.setInterval(async () => {
      const b = await getBuild(build.id).catch(() => null);
      if (!b) return;
      setBuild(b);
      if (b.status === "completed") {
        await load();
        if (b.product_id) {
          setSelected(b.product_id);
          getProduct(b.product_id).then(setProduct).catch(() => undefined);
        }
        window.setTimeout(() => setBuild(null), 900);
      }
    }, 1500);
    return () => window.clearInterval(t);
  }, [build, load]);

  function chooseWorkspace(id: string) {
    setProducts(null);
    setSelected(null);
    setProduct(null);
    setWorkspaceId(id);
  }

  const shown = product && product.id === selected ? product : null;
  const busy = build?.status === "running" || engine?.status === "running";

  // The engine's plan, drawn as dashed cards until each product exists.
  const graphProducts = useMemo(() => {
    const real = products ?? [];
    if (!engine) return real;
    const names = new Set(real.map((p) => p.name.toLowerCase()));
    const roleOf = (t: string) => (/\.(DIM_|DIM)/i.test(t) ? "dimension" : /\.MART_/i.test(t) ? "aggregate" : "fact");
    const ghosts = engine.proposals
      .filter((p) => ["queued", "building", "failed"].includes(p.status) && !names.has(p.concept.toLowerCase()))
      .map((p) => ({
        id: `ghost:${p.concept}`,
        workspace_id: engine.workspace_id,
        workspace: "",
        name: p.concept,
        slug: p.concept.toLowerCase(),
        domain: null,
        description: p.intent,
        status: "draft" as const,
        intent: p.intent,
        inputs: (p.inputs ?? p.pins.map((eid, i) => ({ entity_id: eid, table: p.tables[i] ?? eid, role: roleOf(p.tables[i] ?? eid) }))).map((x) => ({
          ...x, why: "", lane: "core" as const, grain: null, trust: "profiled" as const,
        })),
        entities: [],
        dimensions: [],
        metrics: [],
        tools: [],
        health: null,
        model: null,
        built_at: null,
        confirmed_at: null,
        ghost: p.status as "queued" | "building" | "failed",
      }));
    return [...real, ...ghosts];
  }, [products, engine]);
  const ws = workspaces.find((w) => w.id === workspaceId);

  return (
    <>
      <PageHeader
        title="Data Products"
        description="Business concepts served as one unit: metrics defined once, ports, contracts, built from the map"
        actions={
          <div className="flex items-center gap-3">
            {workspaces.length > 1 && (
              <Segmented items={workspaces.map((w) => ({ id: w.id, label: w.name }))} value={workspaceId ?? ""} onChange={chooseWorkspace} />
            )}
            <span data-guide="prod:mode">
              <Segmented
                items={[
                  { id: "lineage", label: "Lineage" },
                  { id: "semantic", label: "Semantic" },
                ]}
                value={mode}
                onChange={setMode}
              />
            </span>
            <button data-guide="prod:engine" onClick={() => setStartingEngine(true)} disabled={!workspaceId || busy} className="k-btn">
              <Cpu className="h-4 w-4" />
              Run engine
            </button>
            <button data-guide="prod:new" onClick={() => setCreating(true)} disabled={!workspaceId || busy} className="k-btn k-btn-primary">
              <Plus className="h-4 w-4" />
              New data product
            </button>
          </div>
        }
      />

      <div data-guide="prod:graph" className="relative min-h-0 flex-1 overflow-hidden bg-canvas">
        {products === null ? (
          <p className="flex items-center gap-2 px-7 py-6 text-k-body text-ink-muted">
            <Spinner /> Loading data products…
          </p>
        ) : graphProducts.length === 0 && !build ? (
          <div className="flex h-full items-center justify-center">
            <div className="kairos-panel">
              <EmptyState
                icon={Layers}
                title={`No data products on ${ws?.name ?? "this connection"} yet`}
                action={
                  <div className="flex justify-center gap-2">
                    <button onClick={() => setStartingEngine(true)} className="k-btn k-btn-primary">
                      <Cpu className="h-4 w-4" /> Run the engine
                    </button>
                    <button onClick={() => setCreating(true)} className="k-btn">
                      <Plus className="h-4 w-4" /> Build one by hand
                    </button>
                  </div>
                }
              >
                Let the engine read how data flows through this warehouse and build every product it supports, or
                name one business concept, like Sales, and build it yourself.
              </EmptyState>
            </div>
          </div>
        ) : (
          <>
            <ProductGraph
              products={graphProducts}
              mode={mode}
              selected={selected}
              onSelect={(id) => setSelected(id && !id.startsWith("ghost:") ? id : null)}
              padLeft={engine ? 430 : 0}
            />
            <div className="pointer-events-none absolute bottom-4 left-1/2 flex -translate-x-1/2 items-center gap-4 rounded-full border border-hairline bg-surface/95 px-4 py-1.5 text-k-caption text-ink-muted shadow-sm">
              {mode === "lineage" ? (
                <>
                  {LEGEND.map(([c, l]) => (
                    <span key={l} className="inline-flex items-center gap-1.5">
                      <span className="h-0.5 w-4 rounded" style={{ background: c }} /> {l}
                    </span>
                  ))}
                  <span>· click a product to open it</span>
                </>
              ) : (
                <span>Dimensions shared by several products (highlighted) are the vocabulary they have in common</span>
              )}
            </div>
          </>
        )}

        {selected && !shown && (
          <div className="absolute inset-y-0 right-0 z-20 flex w-[min(620px,100%)] items-center justify-center border-l border-hairline bg-surface">
            <Spinner />
          </div>
        )}
        {shown && (
          <ProductDrawer
            key={shown.id}
            product={shown}
            onClose={() => setSelected(null)}
            onChanged={(p) => {
              setProduct(p);
              load();
            }}
            onDeleted={() => {
              setSelected(null);
              setProduct(null);
              load();
            }}
            onRebuild={async () => {
              setBuild(await rebuildProduct(shown.id));
            }}
          />
        )}
        {creating && workspaceId && (
          <CreateDialog
            workspaceId={workspaceId}
            workspaceName={ws?.name ?? ""}
            onClose={() => setCreating(false)}
            onStart={async (body) => {
              const b = await startProduct({ workspace_id: workspaceId, ...body });
              setCreating(false);
              setBuild(b);
            }}
          />
        )}
        {build && <BuildProgress build={build} />}
        {engine && (
          <EnginePanel
            run={engine}
            onClose={() => setEngine(null)}
            onOpen={(id) => setSelected(id)}
          />
        )}
        {startingEngine && workspaceId && (
          <EngineStart
            workspaceName={ws?.name ?? ""}
            existing={products?.length ?? 0}
            onClose={() => setStartingEngine(false)}
            onRun={async (rebuild) => {
              const r = await runEngine({ workspace_id: workspaceId, rebuild_existing: rebuild });
              setStartingEngine(false);
              setEngine(r);
            }}
          />
        )}
      </div>
    </>
  );
}
