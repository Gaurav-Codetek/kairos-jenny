---
type: Dataset Type
title: ePA Transaction Data
description: Electronic prior authorisation requests and outcomes.
tags:
- dataset
- access
generated:
  by: claude-opus-5.5/us-pharma-kb-builder
  at: '2026-10-02T00:00:00Z'
dataset_category: access
grain: PA request
primary_key:
- pa_id
join_keys:
- npi
refresh_cadence: daily
projection: partial
measures: approval rates, turnaround
phi_status: de-identified
---
# Definition
Electronic prior authorisation requests and outcomes.

# Grain & keys
* **Grain:** PA request
* **Primary key:** `pa_id`
* **Join keys:** `npi` → /identifiers/provider/npi.md
* **Refresh:** daily
* **Projection:** partial
* **Measures:** approval rates, turnaround
* **PHI status:** de-identified

# Schema
Typical fields (vendor layouts differ; confirm against the data dictionary):

| Field | Meaning |
|---|---|
| `outcome` | approved/denied |

# Typical uses
* Access friction

# Pitfalls
* Coverage limited to ePA volume

# Vendors / sources
CoverMyMeds, Surescripts

