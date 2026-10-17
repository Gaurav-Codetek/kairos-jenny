---
type: Dataset Type
title: Veeva OpenData / Network
description: Veeva HCP/HCO reference data and MDM hub issuing VIDs, custom keys and hierarchies.
tags:
- dataset
- reference
generated:
  by: claude-opus-5.5/us-pharma-kb-builder
  at: '2026-10-02T00:00:00Z'
dataset_category: reference
grain: HCP / HCO / system
primary_key:
- vid
join_keys:
- vid
- npi
- dea/hin
refresh_cadence: daily–weekly
projection: census (curated)
measures: n/a
phi_status: business contact data
---
# Definition
Veeva HCP/HCO reference data and MDM hub issuing VIDs, custom keys and hierarchies.

# Grain & keys
* **Grain:** HCP / HCO / system
* **Primary key:** `vid`
* **Join keys:** `vid` → /identifiers/provider/veeva-vid.md, `npi` → /identifiers/provider/npi.md, `dea/hin` → /identifiers/provider/dea-number.md
* **Refresh:** daily–weekly
* **Projection:** census (curated)
* **Measures:** n/a
* **PHI status:** business contact data

# Schema
Typical fields (vendor layouts differ; confirm against the data dictionary):

| Field | Meaning |
|---|---|
| `vid` | master id |
| `custom_key_value` | source-system key crosswalk |
| `parent_hco_vid` | hierarchy |

# Typical uses
* Mastering 867 ship-tos and CRM accounts

# Pitfalls
* Custom keys must be maintained per source

# Vendors / sources
Veeva

# Relationships

