---
type: Pipeline
title: ics_sales_ingestion (Databricks job 572339974626818)
description: Multi-task job ingesting ICS 867 files through bronze → silver → gold and writing run logs.
tags:
- warehouse
- pipeline
generated:
  by: claude-opus-5.5/us-pharma-kb-builder
  at: '2026-10-02T00:00:00Z'
sources:
- id: kairos-ics
  resource: kairos://ICS Sales Warehouse
  title: 'Kairos context layer: ICS Sales Warehouse (synced 2026-10-01)'
resource: kairos://ICS Sales Warehouse
kairos_entity_id: job:ICS Sales Warehouse:572339974626818
relations:
- predicate: generates_data
  target: /warehouse/tables/bronze-raw-ics-867.md
- predicate: generates_data
  target: /warehouse/tables/bronze-stg-ics-867.md
- predicate: generates_data
  target: /warehouse/tables/silver-fct-ics-867.md
- predicate: generates_data
  target: /warehouse/tables/gold-bi-account-sales.md
- predicate: generates_data
  target: /warehouse/tables/silver-network-all-dim-alignment.md
- predicate: generates_data
  target: /warehouse/tables/logs-bronze-layer.md
- predicate: generates_data
  target: /warehouse/tables/logs-gold-layer.md
- predicate: generates_data
  target: /warehouse/tables/bronze-comm-table-log.md
---
# Definition
Multi-task job ingesting ICS 867 files through bronze → silver → gold and writing run logs.[^kairos-ics]

# Tasks (from Kairos)
raw ingest → raw_to_stg → stg_to_fct → fct_to_bi, plus alignment and logging tasks. Writes 8 tables.

# Relationships
* **generates_data** → [nexora_poc_catalog.bronze.raw_ics_867](/warehouse/tables/bronze-raw-ics-867.md)
* **generates_data** → [nexora_poc_catalog.bronze.stg_ics_867](/warehouse/tables/bronze-stg-ics-867.md)
* **generates_data** → [nexora_poc_catalog.silver.fct_ics_867](/warehouse/tables/silver-fct-ics-867.md)
* **generates_data** → [nexora_poc_catalog.gold.bi_account_sales](/warehouse/tables/gold-bi-account-sales.md)
* **generates_data** → [nexora_poc_catalog.silver.network_all_dim_alignment](/warehouse/tables/silver-network-all-dim-alignment.md)
* **generates_data** → [nexora_poc_catalog.logs.bronze_layer_logs](/warehouse/tables/logs-bronze-layer.md)
* **generates_data** → [nexora_poc_catalog.logs.gold_layer_logs](/warehouse/tables/logs-gold-layer.md)
* **generates_data** → [nexora_poc_catalog.bronze.comm_table_log](/warehouse/tables/bronze-comm-table-log.md)

[^kairos-ics]: [Kairos context layer: ICS Sales Warehouse (synced 2026-10-01)](kairos://ICS Sales Warehouse)
