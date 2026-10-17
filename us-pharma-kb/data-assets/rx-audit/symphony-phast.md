---
type: Dataset Type
title: Symphony Health (ICON) PHAST Prescription
description: Projected prescriber- and national-level Rx from Symphony's integrated dataverse.
tags:
- dataset
- rx-audit
generated:
  by: claude-opus-5.5/us-pharma-kb-builder
  at: '2026-10-02T00:00:00Z'
dataset_category: rx-audit
grain: prescriber × product × week
primary_key:
- prescriber_npi
- product
- week
join_keys:
- npi
- ndc
refresh_cadence: weekly
projection: projected
measures: TRx/NRx
phi_status: prescriber-identifiable
---
# Definition
Projected prescriber- and national-level Rx from Symphony's integrated dataverse.

# Grain & keys
* **Grain:** prescriber × product × week
* **Primary key:** `prescriber_npi, product, week`
* **Join keys:** `npi` → /identifiers/provider/npi.md, `ndc` → /identifiers/product/ndc.md
* **Refresh:** weekly
* **Projection:** projected
* **Measures:** TRx/NRx
* **PHI status:** prescriber-identifiable

# Schema
Typical fields (vendor layouts differ; confirm against the data dictionary):

| Field | Meaning |
|---|---|
| `npi` | prescriber |
| `trx, nrx` | Rx |

# Typical uses
* Alternative to Xponent

# Pitfalls
* Different projection method than IQVIA — do not mix vendors in one trend

# Vendors / sources
Symphony Health (ICON)

