---
type: Warehouse Table
title: nexora_poc_catalog.gold.rx_mx_claims
description: Uploaded patient-level Rx + Mx claims table in IQVIA LAAD layout (claim status, reject codes, copay card, NBRx, Dx/Px codes).
tags:
- warehouse
- gold
generated:
  by: claude-opus-5.5/us-pharma-kb-builder
  at: '2026-10-02T00:00:00Z'
sources:
- id: kairos-ics
  resource: kairos://ICS Sales Warehouse
  title: 'Kairos context layer: ICS Sales Warehouse (synced 2026-10-01)'
resource: databricks://nexora_poc_catalog.gold.rx_mx_claims
kairos_entity_id: table:ICS Sales Warehouse:nexora_poc_catalog.gold.rx_mx_claims
kairos_trust_level: synced
layer: gold
relations:
- predicate: instance_of
  target: /data-assets/patient-claims/iqvia-laad.md
- predicate: joins_to
  target: /warehouse/tables/raw-iqvia-claims-drug-mapping.md
---
# Definition
Uploaded patient-level Rx + Mx claims table in IQVIA LAAD layout (claim status, reject codes, copay card, NBRx, Dx/Px codes).[^kairos-ics]

# Note
Layout matches IQVIA LAAD (inferred from column names; vendor not stated in metadata). Columns are typed STRING — cast dates (fill_date_new/written_date_new exist) and numerics.

# Relationships
* **instance_of** → [IQVIA LAAD (Longitudinal Access & Adjudication Data)](/data-assets/patient-claims/iqvia-laad.md)
* **joins_to** → [nexora_poc_catalog.bronze.raw_iqvia_claims_drug_mapping](/warehouse/tables/raw-iqvia-claims-drug-mapping.md)

[^kairos-ics]: [Kairos context layer: ICS Sales Warehouse (synced 2026-10-01)](kairos://ICS Sales Warehouse)
