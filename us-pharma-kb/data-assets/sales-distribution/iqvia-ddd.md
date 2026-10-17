---
type: Dataset Type
title: IQVIA DDD (Outlet-Level Sales)
description: Projected weekly/monthly sales from distributors to individual outlets (hospitals, clinics, pharmacies), classified by outlet type.
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
grain: outlet × product group × week
primary_key:
- dddoutletnum
- productgroup
- week
join_keys:
- dddoutletnum
- orgid
- productgroup
refresh_cadence: weekly
projection: projected from distributor reports
measures: sales units and $ (by sales category)
phi_status: none
relations:
- predicate: provided_by
  target: /service-providers/vendors/iqvia.md
---
# Definition
Projected weekly/monthly sales from distributors to individual outlets (hospitals, clinics, pharmacies), classified by outlet type.[^iqvia-data]

# Grain & keys
* **Grain:** outlet × product group × week
* **Primary key:** `dddoutletnum, productgroup, week`
* **Join keys:** `dddoutletnum` → /identifiers/provider/ddd-outlet.md, `orgid` → HCO master via outlet crosswalk, `productgroup` → /identifiers/product/cmf.md
* **Refresh:** weekly
* **Projection:** projected from distributor reports
* **Measures:** sales units and $ (by sales category)
* **PHI status:** none

# Schema
Typical fields (vendor layouts differ; confirm against the data dictionary):

| Field | Meaning |
|---|---|
| `client, report` | delivery metadata |
| `dddoutletnum, dddsubcategorycode, orgid` | outlet |
| `salescategory` | measure type (units/$) |
| `productgroup` | product |
| `datadate` | delivery date |
| `<week columns>` | one column per week (wide) |

# Typical uses
* Non-retail / institutional account sales
* Territory sales where 867 is unavailable

# Pitfalls
* Delivered wide (104 weekly columns) — unpivot before use
* Projected; do not add to 867

# Vendors / sources
IQVIA

# Relationships
* **provided_by** → [IQVIA](/service-providers/vendors/iqvia.md)

[^iqvia-data]: [IQVIA Institute: Available IQVIA Data](https://www.iqvia.com/insights/the-iqvia-institute/available-iqvia-data)
