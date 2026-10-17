---
type: Dataset Type
title: 852 Inventory / Product Activity
description: Wholesaler distribution-centre inventory on hand, receipts and sales by product.
tags:
- dataset
- sales-distribution
generated:
  by: claude-opus-5.5/us-pharma-kb-builder
  at: '2026-10-02T00:00:00Z'
dataset_category: sales-distribution
grain: DC × NDC × day or week
primary_key:
- dc_id
- ndc
- report_date
join_keys:
- ndc
refresh_cadence: daily/weekly
projection: census
measures: inventory units, days on hand
phi_status: none
relations:
- predicate: derived_from
  target: /distribution-edi/edi-852.md
---
# Definition
Wholesaler distribution-centre inventory on hand, receipts and sales by product.

# Grain & keys
* **Grain:** DC × NDC × day or week
* **Primary key:** `dc_id, ndc, report_date`
* **Join keys:** `ndc` → /identifiers/product/ndc.md
* **Refresh:** daily/weekly
* **Projection:** census
* **Measures:** inventory units, days on hand
* **PHI status:** none

# Schema
Typical fields (vendor layouts differ; confirm against the data dictionary):

| Field | Meaning |
|---|---|
| `dc_id` | distribution centre |
| `on_hand_qty` | inventory |
| `receipts_qty` | received |
| `sales_qty` | shipped out |

# Typical uses
* Channel inventory and days-of-supply compliance with fee-for-service agreements
* Shortage monitoring

# Pitfalls
* Not account-level

# Vendors / sources
McKesson, Cencora, Cardinal (via IDA/fee-for-service agreements)

# Relationships
* **derived_from** → [EDI 852 Product Activity Data](/distribution-edi/edi-852.md)

