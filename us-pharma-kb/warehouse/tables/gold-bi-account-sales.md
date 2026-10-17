---
type: Warehouse Table
title: nexora_poc_catalog.gold.bi_account_sales
description: Gold BI mart rolling fct_ics_867 up to organisation/product.
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
resource: databricks://nexora_poc_catalog.gold.bi_account_sales
kairos_entity_id: table:ICS Sales Warehouse:nexora_poc_catalog.gold.bi_account_sales
kairos_trust_level: verified
layer: gold
relations:
- predicate: derived_from
  target: /warehouse/tables/silver-fct-ics-867.md
---
# Definition
Gold BI mart rolling fct_ics_867 up to organisation/product.[^kairos-ics]

# Relationships
* **derived_from** → [nexora_poc_catalog.silver.fct_ics_867](/warehouse/tables/silver-fct-ics-867.md)

[^kairos-ics]: [Kairos context layer: ICS Sales Warehouse (synced 2026-10-01)](kairos://ICS Sales Warehouse)
