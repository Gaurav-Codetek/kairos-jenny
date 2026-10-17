---
type: Dataset Type
title: IQVIA Dx / Hx (Professional & Institutional Claims)
description: Unadjudicated office (Dx) and hospital (Hx) medical claims (~2B per year).
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
grain: claim line
primary_key:
- claim_id
- line
join_keys:
- npi
refresh_cadence: weekly
projection: unprojected
measures: procedures/diagnoses
phi_status: de-identified PHI
---
# Definition
Unadjudicated office (Dx) and hospital (Hx) medical claims (~2B per year).[^iqvia-data]

# Grain & keys
* **Grain:** claim line
* **Primary key:** `claim_id, line`
* **Join keys:** `npi` → /identifiers/provider/npi.md
* **Refresh:** weekly
* **Projection:** unprojected
* **Measures:** procedures/diagnoses
* **PHI status:** de-identified PHI

# Schema
Typical fields (vendor layouts differ; confirm against the data dictionary):

| Field | Meaning |
|---|---|
| `icd10, cpt/hcpcs` | codes |

# Typical uses
* Medical-benefit drug analytics

# Pitfalls
* Pre-adjudication

# Vendors / sources
IQVIA

[^iqvia-data]: [IQVIA Institute: Available IQVIA Data](https://www.iqvia.com/insights/the-iqvia-institute/available-iqvia-data)
