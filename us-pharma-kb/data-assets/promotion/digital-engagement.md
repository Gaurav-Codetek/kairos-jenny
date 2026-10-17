---
type: Dataset Type
title: Digital & Omnichannel Engagement
description: HCP email opens, web/portal visits, webinars and programmatic media exposure.
tags:
- dataset
- promotion
generated:
  by: claude-opus-5.5/us-pharma-kb-builder
  at: '2026-10-02T00:00:00Z'
dataset_category: promotion
grain: event × HCP
primary_key:
- event_id
join_keys:
- npi
refresh_cadence: daily
projection: census for owned channels
measures: touches
phi_status: HCP business data
---
# Definition
HCP email opens, web/portal visits, webinars and programmatic media exposure.

# Grain & keys
* **Grain:** event × HCP
* **Primary key:** `event_id`
* **Join keys:** `npi` → /identifiers/provider/npi.md
* **Refresh:** daily
* **Projection:** census for owned channels
* **Measures:** touches
* **PHI status:** HCP business data

# Schema
Typical fields (vendor layouts differ; confirm against the data dictionary):

| Field | Meaning |
|---|---|
| `channel, event_type` | touch |

# Typical uses
* Omnichannel attribution

# Pitfalls
* Identity matching to NPI is probabilistic

# Vendors / sources
agencies, Veeva, IQVIA, DMD

