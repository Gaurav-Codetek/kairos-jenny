---
type: Dataset Type
title: Symphony Health (ICON) Integrated Dataverse
description: Patient-level Rx and medical claims linked by token across open and closed sources.
tags:
- dataset
- patient-claims
generated:
  by: claude-opus-5.5/us-pharma-kb-builder
  at: '2026-10-02T00:00:00Z'
dataset_category: patient-claims
grain: claim × patient token
primary_key:
- claim_id
join_keys:
- patient_token
refresh_cadence: weekly
projection: unprojected
measures: claims
phi_status: de-identified PHI
---
# Definition
Patient-level Rx and medical claims linked by token across open and closed sources.

# Grain & keys
* **Grain:** claim × patient token
* **Primary key:** `claim_id`
* **Join keys:** `patient_token` → /identifiers/patient/patient-token.md
* **Refresh:** weekly
* **Projection:** unprojected
* **Measures:** claims
* **PHI status:** de-identified PHI

# Schema
Typical fields (vendor layouts differ; confirm against the data dictionary):

| Field | Meaning |
|---|---|
| `patient token` | linkage |

# Typical uses
* Patient journey

# Pitfalls
* Do not union with IQVIA/Komodo patients without cross-vendor token linkage

# Vendors / sources
Symphony Health (ICON)

