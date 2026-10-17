---
type: Warehouse Table
title: nexora_poc_catalog.silver.curr_ztt
description: Current zip → territory/team snapshot.
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
resource: databricks://nexora_poc_catalog.silver.curr_ztt
kairos_entity_id: table:ICS Sales Warehouse:nexora_poc_catalog.silver.curr_ztt
kairos_trust_level: verified
layer: silver
relations:
- predicate: instance_of
  target: /data-assets/reference/zip-to-territory.md
---
# Definition
Current zip → territory/team snapshot.[^kairos-ics]

# Relationships
* **instance_of** → [Zip-to-Territory (ZTT) Alignment](/data-assets/reference/zip-to-territory.md)

[^kairos-ics]: [Kairos context layer: ICS Sales Warehouse (synced 2026-10-01)](kairos://ICS Sales Warehouse)
