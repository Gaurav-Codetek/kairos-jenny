---
type: Warehouse Table
title: nexora_poc_catalog.silver.fct_ics_867
description: Curated ICS 867 invoice-line fact enriched with HCO/system VIDs, customer data and two territory alignments.
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
resource: databricks://nexora_poc_catalog.silver.fct_ics_867
kairos_entity_id: table:ICS Sales Warehouse:nexora_poc_catalog.silver.fct_ics_867
kairos_trust_level: profiled
layer: silver
relations:
- predicate: instance_of
  target: /data-assets/sales-distribution/ics-867.md
- predicate: derived_from
  target: /warehouse/tables/bronze-stg-ics-867.md
- predicate: derived_from
  target: /warehouse/tables/silver-dim-hco.md
- predicate: derived_from
  target: /warehouse/tables/silver-curr-ztt.md
- predicate: derived_from
  target: /warehouse/tables/silver-network-all-dim-alignment.md
- predicate: feeds
  target: /warehouse/tables/gold-bi-account-sales.md
- predicate: implements
  target: /data-model/entities/shipment.md
---
# Definition
Curated ICS 867 invoice-line fact enriched with HCO/system VIDs, customer data and two territory alignments.[^kairos-ics]

# Caveats (Kairos)
* Grain check fails: INVOICE_ID + INVOICE_ITEM not unique (95 duplicates of 183 rows).
* 14 columns flagged as potential personal/sensitive data.
* Open questions: currency of WAC/AMOUNT; meaning of QUANTITY_QUALIFIER; TIME_CALENDAR_DATE vs INVOICE_DATE.

# Relationships
* **instance_of** → [ICS 867 (Cencora ICS 3PL Sales Feed)](/data-assets/sales-distribution/ics-867.md)
* **derived_from** → [nexora_poc_catalog.bronze.stg_ics_867](/warehouse/tables/bronze-stg-ics-867.md)
* **derived_from** → [nexora_poc_catalog.silver.dim_hco](/warehouse/tables/silver-dim-hco.md)
* **derived_from** → [nexora_poc_catalog.silver.curr_ztt](/warehouse/tables/silver-curr-ztt.md)
* **derived_from** → [nexora_poc_catalog.silver.network_all_dim_alignment](/warehouse/tables/silver-network-all-dim-alignment.md)
* **feeds** → [nexora_poc_catalog.gold.bi_account_sales](/warehouse/tables/gold-bi-account-sales.md)
* **implements** → [Shipment / Sale Line](/data-model/entities/shipment.md)

[^kairos-ics]: [Kairos context layer: ICS Sales Warehouse (synced 2026-10-01)](kairos://ICS Sales Warehouse)
