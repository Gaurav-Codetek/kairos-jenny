---
type: Dataset Type
title: CMS Medicare Part D Prescribers PUF
description: Public Medicare Part D claims and costs by prescriber NPI and drug.
tags:
- dataset
- provider-aggregates
generated:
  by: claude-opus-5.5/us-pharma-kb-builder
  at: '2026-10-02T00:00:00Z'
dataset_category: provider-aggregates
grain: NPI × drug × year
primary_key:
- npi
- drug_name
- year
join_keys:
- npi
refresh_cadence: annual (~2-year lag)
projection: census of Part D
measures: claims, 30-day fills, cost
phi_status: public; cells <11 suppressed
---
# Definition
Public Medicare Part D claims and costs by prescriber NPI and drug.

# Grain & keys
* **Grain:** NPI × drug × year
* **Primary key:** `npi, drug_name, year`
* **Join keys:** `npi` → /identifiers/provider/npi.md
* **Refresh:** annual (~2-year lag)
* **Projection:** census of Part D
* **Measures:** claims, 30-day fills, cost
* **PHI status:** public; cells <11 suppressed

# Schema
Typical fields (vendor layouts differ; confirm against the data dictionary):

| Field | Meaning |
|---|---|
| `tot_clms, tot_30day_fills, tot_drug_cst` | measures |

# Typical uses
* Free benchmark for Medicare prescribing

# Pitfalls
* Brand/generic names, not NDC

# Vendors / sources
CMS

