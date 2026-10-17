---
type: Warehouse Table
title: nexora_poc_catalog.gold.pharm_cosm_komodo_monoferric_fact_claims_by_provider_20260616
description: Komodo claims for Monoferric (IV iron) aggregated by HCP with affiliated org/system, rolling windows and hemodialysis split.
tags:
- warehouse
- gold
generated:
  by: claude-opus-5.5/us-pharma-kb-builder
  at: '2026-10-02T00:00:00Z'
sources:
- id: kairos-ics
  resource: kairos://ICS Sales Warehouse
  title: 'Kairos context layer: ICS Sales Warehouse (synced 2026-10-01)'
resource: databricks://nexora_poc_catalog.gold.pharm_cosm_komodo_monoferric_fact_claims_by_provider_20260616
kairos_entity_id: table:ICS Sales Warehouse:nexora_poc_catalog.gold.pharm_cosm_komodo_monoferric_fact_claims_by_provider_20260616
kairos_trust_level: synced
layer: gold
relations:
- predicate: instance_of
  target: /data-assets/provider-aggregates/komodo-claims-by-provider.md
- predicate: joins_to
  target: /warehouse/tables/bronze-raw-veeva-calls.md
---
# Definition
Komodo claims for Monoferric (IV iron) aggregated by HCP with affiliated org/system, rolling windows and hemodialysis split.[^kairos-ics]

# Relationships
* **instance_of** → [Komodo Claims by Provider (HCP × Affiliation Aggregate)](/data-assets/provider-aggregates/komodo-claims-by-provider.md)
* **joins_to** → [nexora_poc_catalog.bronze.raw_veeva_calls](/warehouse/tables/bronze-raw-veeva-calls.md)

[^kairos-ics]: [Kairos context layer: ICS Sales Warehouse (synced 2026-10-01)](kairos://ICS Sales Warehouse)
