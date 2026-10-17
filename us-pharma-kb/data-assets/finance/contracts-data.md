---
type: Dataset Type
title: Contracts & Customer Eligibility
description: Contract terms, tiers, price lists and eligible-member rosters (GPO, IDN, PBM, 340B).
tags:
- dataset
- finance
generated:
  by: claude-opus-5.5/us-pharma-kb-builder
  at: '2026-10-02T00:00:00Z'
dataset_category: finance
grain: contract × tier × product × period
primary_key:
- contract_id
- tier
- ndc
- start_date
join_keys:
- contract_id
- hin/dea/340b_id
refresh_cadence: on change
projection: census
measures: contract price
phi_status: none
---
# Definition
Contract terms, tiers, price lists and eligible-member rosters (GPO, IDN, PBM, 340B).

# Grain & keys
* **Grain:** contract × tier × product × period
* **Primary key:** `contract_id, tier, ndc, start_date`
* **Join keys:** `contract_id` → 867 CONTRACT_ID, `hin/dea/340b_id` → /identifiers/provider/hin.md
* **Refresh:** on change
* **Projection:** census
* **Measures:** contract price
* **PHI status:** none

# Schema
Typical fields (vendor layouts differ; confirm against the data dictionary):

| Field | Meaning |
|---|---|
| `contract_price` | $ |
| `eligible members` | roster |

# Typical uses
* Chargeback validation
* GTN

# Pitfalls
* Effective dating essential

# Vendors / sources
Model N, IntegriChain, Revitas

