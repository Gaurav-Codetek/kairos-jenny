---
type: Dataset Type
title: SNR Sales Feed (Market × Product, with 340B Flag)
description: Weekly/monthly market- and product-level sales feed (WAC $, AWP, volume/pack/extended units) with a 340B transaction flag.
tags:
- dataset
- sales-distribution
generated:
  by: claude-opus-5.5/us-pharma-kb-builder
  at: '2026-10-02T00:00:00Z'
dataset_category: sales-distribution
grain: market × product × relationship (REL_ID) × week
primary_key:
- MARKET_ID
- PRODUCT_ID
- REL_ID
- WEEK_ENDING_DATE
join_keys:
- PRODUCT_ID
- MARKET_ID
refresh_cadence: weekly
projection: unconfirmed
measures: WAC dollars, AWP, volume/pack/extended units
phi_status: none
---
# Definition
Weekly/monthly market- and product-level sales feed (WAC $, AWP, volume/pack/extended units) with a 340B transaction flag.

# Grain & keys
* **Grain:** market × product × relationship (REL_ID) × week
* **Primary key:** `MARKET_ID, PRODUCT_ID, REL_ID, WEEK_ENDING_DATE`
* **Join keys:** `PRODUCT_ID` → product master, `MARKET_ID` → /reference-data/market-basket.md
* **Refresh:** weekly
* **Projection:** unconfirmed
* **Measures:** WAC dollars, AWP, volume/pack/extended units
* **PHI status:** none

# Schema
Typical fields (vendor layouts differ; confirm against the data dictionary):

| Field | Meaning |
|---|---|
| `MARKET_ID/NAME, PRODUCT_ID/NAME` | market & product |
| `REL_ID` | relationship/outlet key (meaning unconfirmed) |
| `340B_TRANSACTION_FLAG` | 340B sale indicator |
| `WAC_DOLLARS, AWP, NORMALISED_AWP` | price/value |
| `VOLUME_UNITS, PACK_UNITS, EXTENDED_UNITS` | units |
| `WEEK_ENDING_DATE, MONTH_ENDING_DATE` | period |

# Typical uses
* Market share by $ and units
* 340B share of volume

# Pitfalls
* The 'SNR' name and REL_ID semantics vary by source — confirm with the data owner before relying on them

# Vendors / sources
vendor not stated in metadata

# Relationships

