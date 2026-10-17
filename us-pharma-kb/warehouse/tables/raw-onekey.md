---
type: Warehouse Table
title: nexora_poc_catalog.bronze.raw_onekey
description: IQVIA OneKey reference extract.
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
resource: databricks://nexora_poc_catalog.bronze.raw_onekey
kairos_entity_id: table:ICS Sales Warehouse:nexora_poc_catalog.bronze.raw_onekey
kairos_trust_level: synced
layer: bronze
relations:
- predicate: instance_of
  target: /data-assets/reference/iqvia-onekey.md
---
# Definition
IQVIA OneKey reference extract.[^kairos-ics]

# Relationships
* **instance_of** → [IQVIA OneKey](/data-assets/reference/iqvia-onekey.md)

[^kairos-ics]: [Kairos context layer: ICS Sales Warehouse (synced 2026-10-01)](kairos://ICS Sales Warehouse)
