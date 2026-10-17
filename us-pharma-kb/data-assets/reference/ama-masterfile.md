---
type: Dataset Type
title: AMA Physician Masterfile
description: Record of US physicians incl. residents, with ME numbers, specialties and PDRP status.
tags:
- dataset
- reference
generated:
  by: claude-opus-5.5/us-pharma-kb-builder
  at: '2026-10-02T00:00:00Z'
dataset_category: reference
grain: physician
primary_key:
- me_number
join_keys:
- me_number
refresh_cadence: monthly
projection: census
measures: n/a
phi_status: licensed
---
# Definition
Record of US physicians incl. residents, with ME numbers, specialties and PDRP status.

# Grain & keys
* **Grain:** physician
* **Primary key:** `me_number`
* **Join keys:** `me_number` → /identifiers/provider/ama-me-number.md
* **Refresh:** monthly
* **Projection:** census
* **Measures:** n/a
* **PHI status:** licensed

# Schema
Typical fields (vendor layouts differ; confirm against the data dictionary):

| Field | Meaning |
|---|---|
| `me_number` | id |

# Typical uses
* Prescriber matching

# Pitfalls
* Licence restrictions

# Vendors / sources
AMA (via licensees)

