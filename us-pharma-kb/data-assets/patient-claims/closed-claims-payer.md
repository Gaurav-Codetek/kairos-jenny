---
type: Dataset Type
title: Closed (Payer-Adjudicated) Claims
description: Medical and pharmacy claims from health plans for enrolled members, with eligibility files — complete for each member's enrolled period.
tags:
- dataset
- patient-claims
generated:
  by: claude-opus-5.5/us-pharma-kb-builder
  at: '2026-10-02T00:00:00Z'
sources:
- id: komodo-method
  resource: https://www.komodohealth.com/reports-methodology/
  title: 'Komodo Health: standard methodology'
resource: https://www.komodohealth.com/reports-methodology/
dataset_category: patient-claims
grain: claim line × member token with enrollment spans
primary_key:
- claim_id
- line
join_keys:
- patient_token
refresh_cadence: monthly (≈1-month lag)
projection: unprojected, enrollment-complete
measures: paid amounts, utilisation, enrollment
phi_status: de-identified PHI
relations:
- predicate: related_to
  target: /claims/open-vs-closed.md
---
# Definition
Medical and pharmacy claims from health plans for enrolled members, with eligibility files — complete for each member's enrolled period.[^komodo-method]

# Grain & keys
* **Grain:** claim line × member token with enrollment spans
* **Primary key:** `claim_id, line`
* **Join keys:** `patient_token` → /identifiers/patient/patient-token.md
* **Refresh:** monthly (≈1-month lag)
* **Projection:** unprojected, enrollment-complete
* **Measures:** paid amounts, utilisation, enrollment
* **PHI status:** de-identified PHI

# Schema
Typical fields (vendor layouts differ; confirm against the data dictionary):

| Field | Meaning |
|---|---|
| `enrollment start/end` | denominator |
| `allowed/paid amounts` | cost |

# Typical uses
* Incidence, persistence, cost-of-care, HEOR

# Pitfalls
* Smaller and payer-skewed vs open data

# Vendors / sources
IQVIA PharMetrics Plus, Optum Clinformatics, Merative MarketScan, Komodo closed lives

# Relationships
* **related_to** → [Open vs Closed Claims](/claims/open-vs-closed.md)

[^komodo-method]: [Komodo Health: standard methodology](https://www.komodohealth.com/reports-methodology/)
