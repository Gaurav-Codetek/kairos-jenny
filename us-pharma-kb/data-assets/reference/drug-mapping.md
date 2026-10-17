---
type: Dataset Type
title: Claims Drug Mapping (NDC → Product/Market)
description: Lookup mapping NDC11/USC to product, molecule, form, strength and market (e.g. IQVIA claims drug mapping).
tags:
- dataset
- reference
generated:
  by: claude-opus-5.5/us-pharma-kb-builder
  at: '2026-10-02T00:00:00Z'
dataset_category: reference
grain: NDC11
primary_key:
- NDC11
join_keys:
- NDC11
- USC_CODE
refresh_cadence: with each delivery
projection: n/a
measures: n/a
phi_status: none
---
# Definition
Lookup mapping NDC11/USC to product, molecule, form, strength and market (e.g. IQVIA claims drug mapping).

# Grain & keys
* **Grain:** NDC11
* **Primary key:** `NDC11`
* **Join keys:** `NDC11` → /identifiers/product/ndc.md, `USC_CODE` → /identifiers/product/usc.md
* **Refresh:** with each delivery
* **Projection:** n/a
* **Measures:** n/a
* **PHI status:** none

# Schema
Typical fields (vendor layouts differ; confirm against the data dictionary):

| Field | Meaning |
|---|---|
| `PRODUCT_NAME, MOLECULE_NAME, BRAND_GENERIC_FLAG, PRODUCT_FORM, PRODUCT_STRENGTH, PACKAGE_QUANTITY, MANUFACTURER` | attributes |

# Typical uses
* Classify claims into brands/markets

# Pitfalls
* Keep historical NDCs

# Vendors / sources
IQVIA, internal product master

# Relationships

