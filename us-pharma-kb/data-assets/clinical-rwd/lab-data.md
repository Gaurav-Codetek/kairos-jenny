---
type: Dataset Type
title: Lab Results Data
description: De-identified lab results with LOINC codes and values.
tags:
- dataset
- clinical-rwd
generated:
  by: claude-opus-5.5/us-pharma-kb-builder
  at: '2026-10-02T00:00:00Z'
dataset_category: clinical-rwd
grain: record × patient token
primary_key:
- record_id
join_keys:
- patient_token
refresh_cadence: monthly
projection: unprojected
measures: clinical values
phi_status: de-identified PHI
---
# Definition
De-identified lab results with LOINC codes and values.

# Grain & keys
* **Grain:** record × patient token
* **Primary key:** `record_id`
* **Join keys:** `patient_token` → /identifiers/patient/patient-token.md
* **Refresh:** monthly
* **Projection:** unprojected
* **Measures:** clinical values
* **PHI status:** de-identified PHI

# Schema
Typical fields (vendor layouts differ; confirm against the data dictionary):

| Field | Meaning |
|---|---|
| `patient_token` | linkage |

# Typical uses
* RWE, patient finding

# Pitfalls
* Linkage only under expert determination

# Vendors / sources
Quest, Labcorp, aggregators

