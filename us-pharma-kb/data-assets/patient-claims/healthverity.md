---
type: Dataset Type
title: HealthVerity Marketplace Data
description: Tokenised, licensable claims, EHR, lab and consumer data that can be linked across suppliers.
tags:
- dataset
- patient-claims
generated:
  by: claude-opus-5.5/us-pharma-kb-builder
  at: '2026-10-02T00:00:00Z'
dataset_category: patient-claims
grain: record × HealthVerity token
primary_key:
- record_id
join_keys:
- hvid
refresh_cadence: varies
projection: unprojected
measures: varies
phi_status: de-identified PHI
---
# Definition
Tokenised, licensable claims, EHR, lab and consumer data that can be linked across suppliers.

# Grain & keys
* **Grain:** record × HealthVerity token
* **Primary key:** `record_id`
* **Join keys:** `hvid` → /identifiers/patient/patient-token.md
* **Refresh:** varies
* **Projection:** unprojected
* **Measures:** varies
* **PHI status:** de-identified PHI

# Schema
Typical fields (vendor layouts differ; confirm against the data dictionary):

| Field | Meaning |
|---|---|
| `hvid` | token |

# Typical uses
* Custom linked cohorts

# Pitfalls
* Licence per source

# Vendors / sources
HealthVerity

