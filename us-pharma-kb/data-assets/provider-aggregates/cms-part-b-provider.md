---
type: Dataset Type
title: CMS Medicare Physician & Other Practitioners PUF
description: Public Part B services and payments by NPI and HCPCS (includes J-codes).
tags:
- dataset
- provider-aggregates
generated:
  by: claude-opus-5.5/us-pharma-kb-builder
  at: '2026-10-02T00:00:00Z'
dataset_category: provider-aggregates
grain: NPI × HCPCS × place of service × year
primary_key:
- npi
- hcpcs
- pos
- year
join_keys:
- npi
- hcpcs
refresh_cadence: annual
projection: census of FFS Part B
measures: services, beneficiaries, payments
phi_status: public; suppressed small cells
---
# Definition
Public Part B services and payments by NPI and HCPCS (includes J-codes).

# Grain & keys
* **Grain:** NPI × HCPCS × place of service × year
* **Primary key:** `npi, hcpcs, pos, year`
* **Join keys:** `npi` → /identifiers/provider/npi.md, `hcpcs` → /identifiers/product/hcpcs.md
* **Refresh:** annual
* **Projection:** census of FFS Part B
* **Measures:** services, beneficiaries, payments
* **PHI status:** public; suppressed small cells

# Schema
Typical fields (vendor layouts differ; confirm against the data dictionary):

| Field | Meaning |
|---|---|
| `tot_srvcs, avg_mdcr_pymt_amt` | measures |

# Typical uses
* Physician-administered drug benchmarking

# Pitfalls
* FFS only (no MA)

# Vendors / sources
CMS

