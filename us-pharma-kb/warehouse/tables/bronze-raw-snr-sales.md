---
type: Warehouse Table
title: nexora_poc_catalog.bronze.raw_snr_sales
description: SNR market × product weekly sales with 340B flag, WAC $, AWP and units.
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
resource: databricks://nexora_poc_catalog.bronze.raw_snr_sales
kairos_entity_id: table:ICS Sales Warehouse:nexora_poc_catalog.bronze.raw_snr_sales
kairos_trust_level: synced
layer: bronze
relations:
- predicate: instance_of
  target: /data-assets/sales-distribution/snr-sales.md
---
# Definition
SNR market × product weekly sales with 340B flag, WAC $, AWP and units.[^kairos-ics]

# Relationships
* **instance_of** → [SNR Sales Feed (Market × Product, with 340B Flag)](/data-assets/sales-distribution/snr-sales.md)

[^kairos-ics]: [Kairos context layer: ICS Sales Warehouse (synced 2026-10-01)](kairos://ICS Sales Warehouse)
