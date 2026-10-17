---
type: Dataset Type
title: IQVIA LRx (Longitudinal Prescription Claims)
description: Patient-level dispensed Rx claims from pharmacies, payers, software providers and clearinghouses (~4B claims/yr since 2006).
tags:
- dataset
- patient-claims
generated:
  by: claude-opus-5.5/us-pharma-kb-builder
  at: '2026-10-02T00:00:00Z'
sources:
- id: iqvia-data
  resource: https://www.iqvia.com/insights/the-iqvia-institute/available-iqvia-data
  title: 'IQVIA Institute: Available IQVIA Data'
resource: https://www.iqvia.com/insights/the-iqvia-institute/available-iqvia-data
dataset_category: patient-claims
grain: dispensed fill × patient
primary_key:
- claim_id
join_keys:
- patient_id
- ndc
refresh_cadence: weekly
projection: unprojected panel
measures: dispensed fills
phi_status: de-identified PHI
---
# Definition
Patient-level dispensed Rx claims from pharmacies, payers, software providers and clearinghouses (~4B claims/yr since 2006).[^iqvia-data]

# Grain & keys
* **Grain:** dispensed fill × patient
* **Primary key:** `claim_id`
* **Join keys:** `patient_id` → /identifiers/patient/patient-token.md, `ndc` → /identifiers/product/ndc.md
* **Refresh:** weekly
* **Projection:** unprojected panel
* **Measures:** dispensed fills
* **PHI status:** de-identified PHI

# Schema
Typical fields (vendor layouts differ; confirm against the data dictionary):

| Field | Meaning |
|---|---|
| `patient_id` | token |
| `ndc, days_supply` | fill |

# Typical uses
* Persistence, switching

# Pitfalls
* Coverage ~92% retail / 82% mail / 74% LTC

# Vendors / sources
IQVIA

[^iqvia-data]: [IQVIA Institute: Available IQVIA Data](https://www.iqvia.com/insights/the-iqvia-institute/available-iqvia-data)
