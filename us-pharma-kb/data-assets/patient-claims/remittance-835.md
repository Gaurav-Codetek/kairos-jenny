---
type: Dataset Type
title: Remittance (835) Data
description: 'Payment outcomes for medical claims from 835 files: paid amounts, denials and adjustment reasons.'
tags:
- dataset
- patient-claims
generated:
  by: claude-opus-5.5/us-pharma-kb-builder
  at: '2026-10-02T00:00:00Z'
dataset_category: patient-claims
grain: claim/line payment
primary_key:
- claim_control_number
- line
join_keys:
- claim_id
refresh_cadence: weekly
projection: unprojected
measures: paid/denied amounts
phi_status: de-identified PHI
relations:
- predicate: derived_from
  target: /claims/medical/x12-835.md
---
# Definition
Payment outcomes for medical claims from 835 files: paid amounts, denials and adjustment reasons.

# Grain & keys
* **Grain:** claim/line payment
* **Primary key:** `claim_control_number, line`
* **Join keys:** `claim_id` → /data-assets/patient-claims/medical-claims-open.md
* **Refresh:** weekly
* **Projection:** unprojected
* **Measures:** paid/denied amounts
* **PHI status:** de-identified PHI

# Schema
Typical fields (vendor layouts differ; confirm against the data dictionary):

| Field | Meaning |
|---|---|
| `carc/rarc` | adjustment reasons |
| `paid_amount` | payment |

# Typical uses
* Medical-benefit denial analysis

# Pitfalls
* Join to 837 via control numbers

# Vendors / sources
IQVIA, clearinghouses

# Relationships
* **derived_from** → [X12 835 Remittance](/claims/medical/x12-835.md)

