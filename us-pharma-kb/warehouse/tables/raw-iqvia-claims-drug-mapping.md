---
type: Warehouse Table
title: nexora_poc_catalog.bronze.raw_iqvia_claims_drug_mapping
description: NDC11/USC → product attributes lookup for claims.
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
resource: databricks://nexora_poc_catalog.bronze.raw_iqvia_claims_drug_mapping
kairos_entity_id: table:ICS Sales Warehouse:nexora_poc_catalog.bronze.raw_iqvia_claims_drug_mapping
kairos_trust_level: synced
layer: bronze
relations:
- predicate: instance_of
  target: /data-assets/reference/drug-mapping.md
---
# Definition
NDC11/USC → product attributes lookup for claims.[^kairos-ics]

# Relationships
* **instance_of** → [Claims Drug Mapping (NDC → Product/Market)](/data-assets/reference/drug-mapping.md)

[^kairos-ics]: [Kairos context layer: ICS Sales Warehouse (synced 2026-10-01)](kairos://ICS Sales Warehouse)
