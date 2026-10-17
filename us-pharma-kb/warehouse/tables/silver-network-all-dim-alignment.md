---
type: Warehouse Table
title: nexora_poc_catalog.silver.network_all_dim_alignment
description: Account (VID) territory/region/national alignment.
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
resource: databricks://nexora_poc_catalog.silver.network_all_dim_alignment
kairos_entity_id: table:ICS Sales Warehouse:nexora_poc_catalog.silver.network_all_dim_alignment
kairos_trust_level: verified
layer: silver
relations:
- predicate: instance_of
  target: /data-assets/reference/account-alignment.md
---
# Definition
Account (VID) territory/region/national alignment.[^kairos-ics]

# Relationships
* **instance_of** → [Account / Network Alignment](/data-assets/reference/account-alignment.md)

[^kairos-ics]: [Kairos context layer: ICS Sales Warehouse (synced 2026-10-01)](kairos://ICS Sales Warehouse)
