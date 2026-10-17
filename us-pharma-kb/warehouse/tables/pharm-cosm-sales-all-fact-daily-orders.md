---
type: Warehouse Table
title: nexora_poc_catalog.gold.pharm_cosm_sales_all_fact_daily_orders_20260616
description: Daily order-level sales fact (shares CONTRACT_ID / INVOICE_ID / NDC_QUALIFIER with fct_ics_867).
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
resource: databricks://nexora_poc_catalog.gold.pharm_cosm_sales_all_fact_daily_orders_20260616
kairos_entity_id: table:ICS Sales Warehouse:nexora_poc_catalog.gold.pharm_cosm_sales_all_fact_daily_orders_20260616
kairos_trust_level: synced
layer: gold
relations:
- predicate: joins_to
  target: /warehouse/tables/silver-fct-ics-867.md
---
# Definition
Daily order-level sales fact (shares CONTRACT_ID / INVOICE_ID / NDC_QUALIFIER with fct_ics_867).[^kairos-ics]

# Relationships
* **joins_to** → [nexora_poc_catalog.silver.fct_ics_867](/warehouse/tables/silver-fct-ics-867.md)

[^kairos-ics]: [Kairos context layer: ICS Sales Warehouse (synced 2026-10-01)](kairos://ICS Sales Warehouse)
