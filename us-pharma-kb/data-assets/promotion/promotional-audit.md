---
type: Dataset Type
title: Promotional Audit (Competitive)
description: Panel-based estimates of competitor details, samples and spend.
tags:
- dataset
- promotion
generated:
  by: claude-opus-5.5/us-pharma-kb-builder
  at: '2026-10-02T00:00:00Z'
dataset_category: promotion
grain: brand × channel × month
primary_key:
- brand
- channel
- month
join_keys:
- brand
refresh_cadence: monthly
projection: projected panel
measures: share of voice
phi_status: none
---
# Definition
Panel-based estimates of competitor details, samples and spend.

# Grain & keys
* **Grain:** brand × channel × month
* **Primary key:** `brand, channel, month`
* **Join keys:** `brand` → product master
* **Refresh:** monthly
* **Projection:** projected panel
* **Measures:** share of voice
* **PHI status:** none

# Schema
Typical fields (vendor layouts differ; confirm against the data dictionary):

| Field | Meaning |
|---|---|
| `details` | estimated calls |

# Typical uses
* Share of voice

# Pitfalls
* Projected estimates

# Vendors / sources
IQVIA ChannelDynamics

