import { fetchApi } from "@/lib/api";

// ── industry knowledge packs and their bindings to the warehouse ─────

export interface KnowledgePack {
  id: string;
  name: string;
  title: string | null;
  version: string;
  okf_version: string | null;
  concepts: number;
  source_path: string;
  loaded_at: string;
}

export interface PacksResponse {
  packs: KnowledgePack[];
  concept_types: Record<string, number>;
}

export type BindingStatus = "proposed" | "confirmed" | "rejected";
export type BindingPredicate = "instance_of" | "identified_by";

export interface BindingEvidence {
  matched_fields?: string[];
  matched_patterns?: string[];
  matched_keys?: string[];
  name_hints?: string[];
  meaning_similarity?: number;
  distinctive_matches?: number;
  coverage?: number;
  column_name?: string;
  rule?: string;
  by?: string;
}

export interface Binding {
  id: string;
  workspace_id: string;
  entity_id: string;
  concept_id: string;
  concept_title: string | null;
  concept_type: string | null;
  predicate: BindingPredicate;
  confidence: number;
  evidence: BindingEvidence | null;
  method: "auto" | "person";
  status: BindingStatus;
  reviewed_by: string | null;
  reviewed_at: string | null;
  note: string | null;
}

export interface BindingsResponse {
  total: number;
  counts: Partial<Record<BindingStatus, number>>;
  bindings: Binding[];
}

export interface ConceptHit {
  concept_id: string;
  type: string;
  title: string;
  description: string | null;
  matched_by: string[];
  warehouse_entities_bound: number;
}

export interface Concept {
  concept_id: string;
  type: string;
  title: string;
  description: string | null;
  pack: { name: string; version: string } | null;
  tags: string[] | null;
  fields: Record<string, unknown> | null;
  sections: Record<string, string>;
  relations: {
    out: { predicate: string; concept_id: string; title: string | null }[];
    in: { predicate: string; concept_id: string; title: string | null }[];
  };
  in_this_warehouse: { entity_id: string; as: BindingPredicate; status: BindingStatus; confidence: number }[];
}

export function getPacks(): Promise<PacksResponse> {
  return fetchApi("/knowledge/packs");
}

export function reloadPack(): Promise<Record<string, unknown>> {
  return fetchApi("/knowledge/packs/load", { method: "POST" });
}

export function classifyWorkspace(id: string): Promise<Record<string, number>> {
  return fetchApi(`/knowledge/classify/${id}`, { method: "POST" });
}

export function listBindings(params: {
  predicate: BindingPredicate;
  status: BindingStatus;
  q?: string;
  limit?: number;
}): Promise<BindingsResponse> {
  const qs = new URLSearchParams({ predicate: params.predicate, status: params.status, limit: String(params.limit ?? 300) });
  if (params.q) qs.set("q", params.q);
  return fetchApi(`/knowledge/bindings?${qs}`);
}

export function reviewBinding(id: string, status: BindingStatus, note?: string): Promise<Binding> {
  return fetchApi(`/knowledge/bindings/${id}`, { method: "PATCH", body: JSON.stringify({ status, note }) });
}

export function searchKnowledge(q: string, types?: string): Promise<{ results: ConceptHit[] }> {
  const qs = new URLSearchParams({ q, limit: "15" });
  if (types) qs.set("types", types);
  return fetchApi(`/knowledge/search?${qs}`);
}

export function getConcept(id: string): Promise<Concept> {
  return fetchApi(`/knowledge/concept?id=${encodeURIComponent(id)}`);
}

/** "table:ws:cat.sch.tbl" → "cat.sch.tbl"; "column:ws:cat.sch.tbl.col" → "cat.sch.tbl.col". */
export function entityLabel(entityId: string): string {
  const i = entityId.indexOf(":", entityId.indexOf(":") + 1);
  return i >= 0 ? entityId.slice(i + 1) : entityId;
}

/** One line on why Kairos proposed a binding. */
export function why(e: BindingEvidence | null): string {
  if (!e) return "";
  if (e.by === "person") return "bound by hand";
  if (e.column_name) return `column name ${e.column_name}`;
  const parts: string[] = [];
  if (e.matched_keys?.length) parts.push(`keys ${e.matched_keys.slice(0, 5).join(", ")}`);
  const fields = (e.matched_fields ?? []).filter((f) => !e.matched_keys?.includes(f));
  if (fields.length) parts.push(`fields ${fields.slice(0, 5).join(", ")}${fields.length > 5 ? "…" : ""}`);
  if (e.matched_patterns?.length) parts.push(`patterns ${e.matched_patterns.join(", ")}`);
  if (e.name_hints?.length) parts.push(`name says ${e.name_hints.join(", ")}`);
  if (e.meaning_similarity != null) parts.push(`meaning ${e.meaning_similarity.toFixed(2)}`);
  return parts.join(" · ");
}
