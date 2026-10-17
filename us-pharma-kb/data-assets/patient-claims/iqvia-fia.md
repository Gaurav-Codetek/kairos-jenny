---
type: Dataset Type
title: IQVIA FIA (Formulary Impact Analyzer / Lifecycle Claims)
description: Paid, rejected and reversed claims captured at the point of sale to measure payer friction.
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
grain: claim transaction
primary_key:
- claim_id
join_keys:
- plan_id
refresh_cadence: weekly
projection: unprojected
measures: approval/rejection/reversal volumes
phi_status: de-identified PHI
---
# Definition
Paid, rejected and reversed claims captured at the point of sale to measure payer friction.[^iqvia-data]

# Grain & keys
* **Grain:** claim transaction
* **Primary key:** `claim_id`
* **Join keys:** `plan_id` → /identifiers/payer/plan-id.md
* **Refresh:** weekly
* **Projection:** unprojected
* **Measures:** approval/rejection/reversal volumes
* **PHI status:** de-identified PHI

# Schema
Typical fields (vendor layouts differ; confirm against the data dictionary):

| Field | Meaning |
|---|---|
| `claim_status, reject_code` | lifecycle |

# Typical uses
* Rejection & abandonment analysis

# Pitfalls
* Coverage built up from 2013

# Vendors / sources
IQVIA

[^iqvia-data]: [IQVIA Institute: Available IQVIA Data](https://www.iqvia.com/insights/the-iqvia-institute/available-iqvia-data)
