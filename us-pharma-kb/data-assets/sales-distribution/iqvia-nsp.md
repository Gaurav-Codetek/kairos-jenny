---
type: Dataset Type
title: IQVIA National Sales Perspectives (NSP)
description: Projected national $ and unit purchases by channel (retail, clinics, hospitals, LTC, mail, etc.).
tags:
- dataset
- sales-distribution
generated:
  by: claude-opus-5.5/us-pharma-kb-builder
  at: '2026-10-02T00:00:00Z'
sources:
- id: iqvia-data
  resource: https://www.iqvia.com/insights/the-iqvia-institute/available-iqvia-data
  title: 'IQVIA Institute: Available IQVIA Data'
resource: https://www.iqvia.com/insights/the-iqvia-institute/available-iqvia-data
dataset_category: sales-distribution
grain: product × channel × month
primary_key:
- product
- channel
- month
join_keys:
- product
refresh_cadence: monthly
projection: projected
measures: purchases $ and units
phi_status: none
---
# Definition
Projected national $ and unit purchases by channel (retail, clinics, hospitals, LTC, mail, etc.).[^iqvia-data]

# Grain & keys
* **Grain:** product × channel × month
* **Primary key:** `product, channel, month`
* **Join keys:** `product` → /identifiers/product/cmf.md
* **Refresh:** monthly
* **Projection:** projected
* **Measures:** purchases $ and units
* **PHI status:** none

# Schema
Typical fields (vendor layouts differ; confirm against the data dictionary):

| Field | Meaning |
|---|---|
| `channel` | outlet class |
| `dollars, units` | measures |

# Typical uses
* Market sizing
* Channel mix

# Pitfalls
* National/regional only

# Vendors / sources
IQVIA

[^iqvia-data]: [IQVIA Institute: Available IQVIA Data](https://www.iqvia.com/insights/the-iqvia-institute/available-iqvia-data)
