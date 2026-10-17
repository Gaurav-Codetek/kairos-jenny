---
type: Warehouse Table
title: nexora_poc_catalog.bronze.raw_veeva_calls
description: Raw Veeva CRM calls/RTE with HCP/HCO/system VIDs, segments, deciles and KOL flags for Monoferric and Cosela.
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
resource: databricks://nexora_poc_catalog.bronze.raw_veeva_calls
kairos_entity_id: table:ICS Sales Warehouse:nexora_poc_catalog.bronze.raw_veeva_calls
kairos_trust_level: synced
layer: bronze
relations:
- predicate: instance_of
  target: /data-assets/promotion/crm-calls.md
---
# Definition
Raw Veeva CRM calls/RTE with HCP/HCO/system VIDs, segments, deciles and KOL flags for Monoferric and Cosela.[^kairos-ics]

# Relationships
* **instance_of** → [CRM Call Activity (Veeva)](/data-assets/promotion/crm-calls.md)

[^kairos-ics]: [Kairos context layer: ICS Sales Warehouse (synced 2026-10-01)](kairos://ICS Sales Warehouse)
