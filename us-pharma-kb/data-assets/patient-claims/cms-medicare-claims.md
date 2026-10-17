---
type: Dataset Type
title: CMS Medicare FFS Claims (ResDAC / VRDC)
description: Research-identifiable Medicare Parts A/B/D claims available under CMS data use agreements.
tags:
- dataset
- patient-claims
generated:
  by: claude-opus-5.5/us-pharma-kb-builder
  at: '2026-10-02T00:00:00Z'
dataset_category: patient-claims
grain: claim line × beneficiary
primary_key:
- clm_id
- line_num
join_keys:
- npi
refresh_cadence: annual/quarterly
projection: census of FFS Medicare
measures: utilisation, payments
phi_status: identifiable PHI under DUA
---
# Definition
Research-identifiable Medicare Parts A/B/D claims available under CMS data use agreements.

# Grain & keys
* **Grain:** claim line × beneficiary
* **Primary key:** `clm_id, line_num`
* **Join keys:** `npi` → /identifiers/provider/npi.md
* **Refresh:** annual/quarterly
* **Projection:** census of FFS Medicare
* **Measures:** utilisation, payments
* **PHI status:** identifiable PHI under DUA

# Schema
Typical fields (vendor layouts differ; confirm against the data dictionary):

| Field | Meaning |
|---|---|
| `bene_id` | beneficiary |

# Typical uses
* Medicare-specific research

# Pitfalls
* Strict DUA, typically 1-2 year lag

# Vendors / sources
CMS

