---
type: Warehouse Table
title: intelliegencedatacatalog.ddd_sales.raw_ddd
description: Raw IQVIA DDD delivery in wide format (one column per week, Sep 2024 – Jan 2026).
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
resource: databricks://intelliegencedatacatalog.ddd_sales.raw_ddd
kairos_entity_id: table:ICS Sales Warehouse:intelliegencedatacatalog.ddd_sales.raw_ddd
kairos_trust_level: synced
layer: bronze
relations:
- predicate: instance_of
  target: /data-assets/sales-distribution/iqvia-ddd.md
---
# Definition
Raw IQVIA DDD delivery in wide format (one column per week, Sep 2024 – Jan 2026).[^kairos-ics]

# Relationships
* **instance_of** → [IQVIA DDD (Outlet-Level Sales)](/data-assets/sales-distribution/iqvia-ddd.md)

[^kairos-ics]: [Kairos context layer: ICS Sales Warehouse (synced 2026-10-01)](kairos://ICS Sales Warehouse)
