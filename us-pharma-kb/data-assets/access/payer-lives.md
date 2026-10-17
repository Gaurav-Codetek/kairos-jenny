---
type: Dataset Type
title: Payer & Covered Lives
description: Enrollment counts by plan, PBM, channel and geography.
tags:
- dataset
- access
generated:
  by: claude-opus-5.5/us-pharma-kb-builder
  at: '2026-10-02T00:00:00Z'
sources:
- id: komodo-kpi
  resource: https://www.komodohealth.com/press/komodo-health-introduces-the-first-integrated-patient-insurance-dataset-to-enhance-patient-level-insights-for-life-sciences/
  title: Komodo Patient Insurance press release
resource: https://www.komodohealth.com/press/komodo-health-introduces-the-first-integrated-patient-insurance-dataset-to-enhance-patient-level-insights-for-life-sciences/
dataset_category: access
grain: plan × geography × period
primary_key:
- plan_id
- geo
- period
join_keys:
- plan_id
refresh_cadence: quarterly
projection: census/estimated
measures: covered lives
phi_status: none
---
# Definition
Enrollment counts by plan, PBM, channel and geography.[^komodo-kpi]

# Grain & keys
* **Grain:** plan × geography × period
* **Primary key:** `plan_id, geo, period`
* **Join keys:** `plan_id` → /identifiers/payer/plan-id.md
* **Refresh:** quarterly
* **Projection:** census/estimated
* **Measures:** covered lives
* **PHI status:** none

# Schema
Typical fields (vendor layouts differ; confirm against the data dictionary):

| Field | Meaning |
|---|---|
| `lives` | members |

# Typical uses
* Account prioritisation

# Pitfalls
* Estimates vary by vendor

# Vendors / sources
MMIT, Komodo Patient Insurance

[^komodo-kpi]: [Komodo Patient Insurance press release](https://www.komodohealth.com/press/komodo-health-introduces-the-first-integrated-patient-insurance-dataset-to-enhance-patient-level-insights-for-life-sciences/)
