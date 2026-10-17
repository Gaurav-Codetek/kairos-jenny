---
type: Dataset Type
title: Account / Network Alignment
description: Account-level (VID-based) territory assignment that can override zip alignment for key accounts.
tags:
- dataset
- reference
generated:
  by: claude-opus-5.5/us-pharma-kb-builder
  at: '2026-10-02T00:00:00Z'
dataset_category: reference
grain: VID × territory × period
primary_key:
- vid
- territory_id
join_keys:
- vid
refresh_cadence: per realignment
projection: n/a
measures: n/a
phi_status: none
---
# Definition
Account-level (VID-based) territory assignment that can override zip alignment for key accounts.

# Grain & keys
* **Grain:** VID × territory × period
* **Primary key:** `vid, territory_id`
* **Join keys:** `vid` → /identifiers/provider/veeva-vid.md
* **Refresh:** per realignment
* **Projection:** n/a
* **Measures:** n/a
* **PHI status:** none

# Schema
Typical fields (vendor layouts differ; confirm against the data dictionary):

| Field | Meaning |
|---|---|
| `ALIGN_TERRITORY_ID / REGION / NATIONAL` | hierarchy |

# Typical uses
* Key-account crediting

# Pitfalls
* Conflicts with ZTT must be resolved by rule

# Vendors / sources
internal

# Relationships

