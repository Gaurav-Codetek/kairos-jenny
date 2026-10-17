---
type: Dataset Type
title: HCP–HCO Affiliation
description: Many-to-many links between HCPs and the organisations/systems where they practise, with role and primary flag.
tags:
- dataset
- reference
generated:
  by: claude-opus-5.5/us-pharma-kb-builder
  at: '2026-10-02T00:00:00Z'
dataset_category: reference
grain: HCP × HCO
primary_key:
- hcp_id
- hco_id
join_keys:
- hcp_id
- hco_id
refresh_cadence: monthly
projection: curated
measures: n/a
phi_status: business
---
# Definition
Many-to-many links between HCPs and the organisations/systems where they practise, with role and primary flag.

# Grain & keys
* **Grain:** HCP × HCO
* **Primary key:** `hcp_id, hco_id`
* **Join keys:** `hcp_id` → /data-model/entities/hcp.md, `hco_id` → /data-model/entities/hco.md
* **Refresh:** monthly
* **Projection:** curated
* **Measures:** n/a
* **PHI status:** business

# Schema
Typical fields (vendor layouts differ; confirm against the data dictionary):

| Field | Meaning |
|---|---|
| `primary_flag` | primary affiliation |
| `source, confidence` | evidence |

# Typical uses
* Roll HCP Rx/claims to accounts

# Pitfalls
* Pick one primary to avoid double counting

# Vendors / sources
OneKey, Veeva, Komodo/claims-derived, NPI→HCO mapping

# Relationships

