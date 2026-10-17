---
type: Dataset Type
title: Calendar / Time Dimension
description: Canonical calendar with week-ending, month, quarter, trimester and rolling-window flags aligned to vendor data weeks.
tags:
- dataset
- reference
generated:
  by: claude-opus-5.5/us-pharma-kb-builder
  at: '2026-10-02T00:00:00Z'
dataset_category: reference
grain: calendar date
primary_key:
- calendar_date
join_keys:
- calendar_date
refresh_cadence: static
projection: n/a
measures: n/a
phi_status: none
---
# Definition
Canonical calendar with week-ending, month, quarter, trimester and rolling-window flags aligned to vendor data weeks.

# Grain & keys
* **Grain:** calendar date
* **Primary key:** `calendar_date`
* **Join keys:** `calendar_date` → fact dates
* **Refresh:** static
* **Projection:** n/a
* **Measures:** n/a
* **PHI status:** none

# Schema
Typical fields (vendor layouts differ; confirm against the data dictionary):

| Field | Meaning |
|---|---|
| `week_ending, month, quarter` | periods |

# Typical uses
* Aligning IQVIA weeks (Friday ending) with invoice dates

# Pitfalls
* Vendors use different week-ending days

# Vendors / sources
internal

