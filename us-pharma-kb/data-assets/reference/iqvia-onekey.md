---
type: Dataset Type
title: IQVIA OneKey
description: Validated HCP/HCO reference data with affiliations, specialties and contact details.
tags:
- dataset
- reference
generated:
  by: claude-opus-5.5/us-pharma-kb-builder
  at: '2026-10-02T00:00:00Z'
dataset_category: reference
grain: HCP or HCO record
primary_key:
- onekey_id
join_keys:
- onekey_id
- npi
refresh_cadence: monthly
projection: census (curated)
measures: n/a
phi_status: business contact data
---
# Definition
Validated HCP/HCO reference data with affiliations, specialties and contact details.

# Grain & keys
* **Grain:** HCP or HCO record
* **Primary key:** `onekey_id`
* **Join keys:** `onekey_id` → /identifiers/provider/onekey-id.md, `npi` → /identifiers/provider/npi.md
* **Refresh:** monthly
* **Projection:** census (curated)
* **Measures:** n/a
* **PHI status:** business contact data

# Schema
Typical fields (vendor layouts differ; confirm against the data dictionary):

| Field | Meaning |
|---|---|
| `onekey_id` | id |
| `affiliations` | HCP–HCO links |

# Typical uses
* Customer master
* Affiliations

# Pitfalls
* Licensed — usage restrictions

# Vendors / sources
IQVIA

