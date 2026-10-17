---
type: Warehouse Table
title: nexora_poc_catalog.bronze.raw_npi_info
description: NPI reference extract.
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
resource: databricks://nexora_poc_catalog.bronze.raw_npi_info
kairos_entity_id: table:ICS Sales Warehouse:nexora_poc_catalog.bronze.raw_npi_info
kairos_trust_level: synced
layer: bronze
relations:
- predicate: instance_of
  target: /data-assets/reference/nppes.md
---
# Definition
NPI reference extract.[^kairos-ics]

# Relationships
* **instance_of** → [NPPES NPI File](/data-assets/reference/nppes.md)

[^kairos-ics]: [Kairos context layer: ICS Sales Warehouse (synced 2026-10-01)](kairos://ICS Sales Warehouse)
