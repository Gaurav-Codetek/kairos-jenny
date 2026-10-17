---
type: Warehouse Table
title: nexora_poc_catalog.bronze.stg_ics_867
description: Typed, de-duplicated ICS 867 staging rows from the raw_to_stg task.
tags:
- warehouse
- bronze
generated:
  by: claude-opus-5.5/us-pharma-kb-builder
  at: '2026-10-02T00:00:00Z'
sources:
- id: kairos-ics
  resource: kairos://ICS Sales Warehouse
  title: 'Kairos context layer: ICS Sales Warehouse (synced 2026-10-01)'
resource: databricks://nexora_poc_catalog.bronze.stg_ics_867
kairos_entity_id: table:ICS Sales Warehouse:nexora_poc_catalog.bronze.stg_ics_867
kairos_trust_level: verified
layer: bronze
relations:
- predicate: instance_of
  target: /data-assets/sales-distribution/ics-867.md
- predicate: feeds
  target: /warehouse/tables/silver-fct-ics-867.md
---
# Definition
Typed, de-duplicated ICS 867 staging rows from the raw_to_stg task.[^kairos-ics]

# Relationships
* **instance_of** → [ICS 867 (Cencora ICS 3PL Sales Feed)](/data-assets/sales-distribution/ics-867.md)
* **feeds** → [nexora_poc_catalog.silver.fct_ics_867](/warehouse/tables/silver-fct-ics-867.md)

[^kairos-ics]: [Kairos context layer: ICS Sales Warehouse (synced 2026-10-01)](kairos://ICS Sales Warehouse)
