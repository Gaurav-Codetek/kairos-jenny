---
type: Dataset Type
title: Government Pricing Calculations
description: Monthly/quarterly AMP, BP, ASP, 340B ceiling and FSS calculations from all eligible transactions.
tags:
- dataset
- finance
generated:
  by: claude-opus-5.5/us-pharma-kb-builder
  at: '2026-10-02T00:00:00Z'
dataset_category: finance
grain: NDC9 × period × price type
primary_key:
- ndc9
- period
- price_type
join_keys:
- ndc9
refresh_cadence: monthly/quarterly
projection: n/a
measures: statutory prices
phi_status: none
---
# Definition
Monthly/quarterly AMP, BP, ASP, 340B ceiling and FSS calculations from all eligible transactions.

# Grain & keys
* **Grain:** NDC9 × period × price type
* **Primary key:** `ndc9, period, price_type`
* **Join keys:** `ndc9` → /identifiers/product/ndc.md
* **Refresh:** monthly/quarterly
* **Projection:** n/a
* **Measures:** statutory prices
* **PHI status:** none

# Schema
Typical fields (vendor layouts differ; confirm against the data dictionary):

| Field | Meaning |
|---|---|
| `amp, bp, asp` | prices |

# Typical uses
* Statutory reporting

# Pitfalls
* Restatement windows

# Vendors / sources
Model N, IntegriChain, internal

