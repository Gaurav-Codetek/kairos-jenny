---
type: Dataset Type
title: Formulary & Policy Data
description: Plan-level coverage, tier, PA/step-therapy policy and covered lives by product.
tags:
- dataset
- access
generated:
  by: claude-opus-5.5/us-pharma-kb-builder
  at: '2026-10-02T00:00:00Z'
dataset_category: access
grain: plan × product × effective date
primary_key:
- plan_id
- product
- effective_date
join_keys:
- plan_id
- bin_pcn_group
refresh_cadence: monthly
projection: census
measures: coverage status, lives
phi_status: none
---
# Definition
Plan-level coverage, tier, PA/step-therapy policy and covered lives by product.

# Grain & keys
* **Grain:** plan × product × effective date
* **Primary key:** `plan_id, product, effective_date`
* **Join keys:** `plan_id` → /identifiers/payer/plan-id.md, `bin_pcn_group` → /identifiers/payer/bin-pcn-group.md
* **Refresh:** monthly
* **Projection:** census
* **Measures:** coverage status, lives
* **PHI status:** none

# Schema
Typical fields (vendor layouts differ; confirm against the data dictionary):

| Field | Meaning |
|---|---|
| `tier, pa_required, step_therapy` | policy |
| `lives` | enrollment |

# Typical uses
* Access maps for reps
* Pull-through

# Pitfalls
* Plan IDs differ by vendor — crosswalk needed

# Vendors / sources
MMIT, Fingertip Formulary, Managed Markets Insight & Technology

