---
type: Dataset Type
title: NPPES NPI File
description: CMS registry of all NPIs with names, addresses, taxonomy codes and entity type.
tags:
- dataset
- reference
generated:
  by: claude-opus-5.5/us-pharma-kb-builder
  at: '2026-10-02T00:00:00Z'
sources:
- id: nppes
  resource: https://npiregistry.cms.hhs.gov/
  title: CMS NPPES NPI Registry
resource: https://npiregistry.cms.hhs.gov/
dataset_category: reference
grain: NPI
primary_key:
- npi
join_keys:
- npi
refresh_cadence: weekly/monthly
projection: census
measures: n/a
phi_status: public
---
# Definition
CMS registry of all NPIs with names, addresses, taxonomy codes and entity type.[^nppes]

# Grain & keys
* **Grain:** NPI
* **Primary key:** `npi`
* **Join keys:** `npi` → /identifiers/provider/npi.md
* **Refresh:** weekly/monthly
* **Projection:** census
* **Measures:** n/a
* **PHI status:** public

# Schema
Typical fields (vendor layouts differ; confirm against the data dictionary):

| Field | Meaning |
|---|---|
| `npi, entity_type` | id |
| `taxonomy_1..15` | specialties |
| `practice address` | location |

# Typical uses
* HCP/HCO master seed
* NPI validation

# Pitfalls
* Addresses self-reported and often stale

# Vendors / sources
CMS

# Relationships

[^nppes]: [CMS NPPES NPI Registry](https://npiregistry.cms.hhs.gov/)
