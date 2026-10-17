---
type: Warehouse Table
title: nexora_poc_catalog.bronze.comm_table_log
description: One row per source file processed by ICS ingestion.
tags:
- warehouse
- operational
generated:
  by: claude-opus-5.5/us-pharma-kb-builder
  at: '2026-10-02T00:00:00Z'
sources:
- id: kairos-ics
  resource: kairos://ICS Sales Warehouse
  title: 'Kairos context layer: ICS Sales Warehouse (synced 2026-10-01)'
resource: databricks://nexora_poc_catalog.bronze.comm_table_log
kairos_entity_id: table:ICS Sales Warehouse:nexora_poc_catalog.bronze.comm_table_log
kairos_trust_level: profiled
layer: operational
---
# Definition
One row per source file processed by ICS ingestion.[^kairos-ics]

[^kairos-ics]: [Kairos context layer: ICS Sales Warehouse (synced 2026-10-01)](kairos://ICS Sales Warehouse)
