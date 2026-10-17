---
type: Dataset Type
title: Open Medical (Mx/Dx) Claims
description: De-identified 837 professional/institutional claims from clearinghouses and practice-management systems.
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
grain: claim line × patient token
primary_key:
- claim_id
- line_number
join_keys:
- patient_token
- rendering/billing npi
- hcpcs/ndc
refresh_cadence: weekly
projection: unprojected panel
measures: procedures, diagnoses, administrations, charges
phi_status: de-identified PHI
relations:
- predicate: derived_from
  target: /claims/medical/medical-claim-flow.md
---
# Definition
De-identified 837 professional/institutional claims from clearinghouses and practice-management systems.[^iqvia-data]

# Grain & keys
* **Grain:** claim line × patient token
* **Primary key:** `claim_id, line_number`
* **Join keys:** `patient_token` → /identifiers/patient/patient-token.md, `rendering/billing npi` → /identifiers/provider/npi.md, `hcpcs/ndc` → /identifiers/product/hcpcs.md
* **Refresh:** weekly
* **Projection:** unprojected panel
* **Measures:** procedures, diagnoses, administrations, charges
* **PHI status:** de-identified PHI

# Schema
Typical fields (vendor layouts differ; confirm against the data dictionary):

| Field | Meaning |
|---|---|
| `service_date` | date |
| `icd10 dx1-12` | diagnoses |
| `cpt/hcpcs, modifiers, units` | procedure/drug |
| `place_of_service, facility_type` | setting |
| `rendering/referring/billing/facility npi` | providers |

# Typical uses
* Physician-administered drug utilisation (J-codes)
* Diagnosis-based patient finding
* Referral networks

# Pitfalls
* Unadjudicated (pre-payment) — charges ≠ paid
* J-code units ≠ NDC units

# Vendors / sources
IQVIA Dx/Hx, Komodo, Symphony

# Relationships
* **derived_from** → [Medical Claim Flow](/claims/medical/medical-claim-flow.md)

[^iqvia-data]: [IQVIA Institute: Available IQVIA Data](https://www.iqvia.com/insights/the-iqvia-institute/available-iqvia-data)
