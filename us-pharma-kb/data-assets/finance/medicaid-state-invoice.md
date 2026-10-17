---
type: Dataset Type
title: Medicaid State Invoices (CMS-R-144)
description: Quarterly state invoices of utilisation units × URA.
tags:
- dataset
- finance
generated:
  by: claude-opus-5.5/us-pharma-kb-builder
  at: '2026-10-02T00:00:00Z'
dataset_category: finance
grain: state × NDC × quarter
primary_key:
- state
- ndc11
- quarter
join_keys:
- ndc11
refresh_cadence: quarterly
projection: census
measures: units, rebate $
phi_status: none
relations:
- predicate: measures
  target: /pricing-gtn/medicaid-rebate.md
---
# Definition
Quarterly state invoices of utilisation units × URA.

# Grain & keys
* **Grain:** state × NDC × quarter
* **Primary key:** `state, ndc11, quarter`
* **Join keys:** `ndc11` → /identifiers/product/ndc.md
* **Refresh:** quarterly
* **Projection:** census
* **Measures:** units, rebate $
* **PHI status:** none

# Schema
Typical fields (vendor layouts differ; confirm against the data dictionary):

| Field | Meaning |
|---|---|
| `units, ura` | rebate |

# Typical uses
* Medicaid liability

# Pitfalls
* Dispute 340B duplicates

# Vendors / sources
states

# Relationships
* **measures** → [Medicaid Rebate](/pricing-gtn/medicaid-rebate.md)

