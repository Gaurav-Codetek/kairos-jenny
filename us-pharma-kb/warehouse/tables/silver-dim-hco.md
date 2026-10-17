---
type: Warehouse Table
title: nexora_poc_catalog.silver.dim_hco
description: Curated HCO master dimension keyed by ORG_VID.
tags:
- warehouse
- silver
generated:
  by: claude-opus-5.5/us-pharma-kb-builder
  at: '2026-10-02T00:00:00Z'
sources:
- id: kairos-ics
  resource: kairos://ICS Sales Warehouse
  title: 'Kairos context layer: ICS Sales Warehouse (synced 2026-10-01)'
resource: databricks://nexora_poc_catalog.silver.dim_hco
kairos_entity_id: table:ICS Sales Warehouse:nexora_poc_catalog.silver.dim_hco
kairos_trust_level: verified
layer: silver
relations:
- predicate: instance_of
  target: /data-assets/reference/veeva-opendata.md
- predicate: implements
  target: /data-model/entities/hco.md
---
# Definition
Curated HCO master dimension keyed by ORG_VID.[^kairos-ics]

# Relationships
* **instance_of** → [Veeva OpenData / Network](/data-assets/reference/veeva-opendata.md)
* **implements** → [HCO](/data-model/entities/hco.md)

[^kairos-ics]: [Kairos context layer: ICS Sales Warehouse (synced 2026-10-01)](kairos://ICS Sales Warehouse)
