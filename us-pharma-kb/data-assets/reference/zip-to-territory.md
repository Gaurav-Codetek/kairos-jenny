---
type: Dataset Type
title: Zip-to-Territory (ZTT) Alignment
description: Effective-dated mapping of 5-digit zip → territory → region → nation, plus account-level overrides.
tags:
- dataset
- reference
generated:
  by: claude-opus-5.5/us-pharma-kb-builder
  at: '2026-10-02T00:00:00Z'
dataset_category: reference
grain: zip × team × effective period
primary_key:
- zip
- team
- effective_date
join_keys:
- zip
- territory_id
refresh_cadence: per realignment (often quarterly/annual)
projection: n/a
measures: n/a
phi_status: none
---
# Definition
Effective-dated mapping of 5-digit zip → territory → region → nation, plus account-level overrides.

# Grain & keys
* **Grain:** zip × team × effective period
* **Primary key:** `zip, team, effective_date`
* **Join keys:** `zip` → account/HCP address zip, `territory_id` → /data-model/entities/territory.md
* **Refresh:** per realignment (often quarterly/annual)
* **Projection:** n/a
* **Measures:** n/a
* **PHI status:** none

# Schema
Typical fields (vendor layouts differ; confirm against the data dictionary):

| Field | Meaning |
|---|---|
| `zip, territory_id/name, region_id/name, team` | alignment |

# Typical uses
* Crediting sales to territories
* IC

# Pitfalls
* Use the alignment valid on the transaction date

# Vendors / sources
internal sales ops

# Relationships

