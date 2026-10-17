---
type: Dataset Type
title: CRM Call Activity (Veeva)
description: 'Rep and MSL interactions recorded in CRM: calls, approved emails (RTE), meetings, products discussed and samples.'
tags:
- dataset
- promotion
generated:
  by: claude-opus-5.5/us-pharma-kb-builder
  at: '2026-10-02T00:00:00Z'
dataset_category: promotion
grain: call (or call detail) × HCP/HCO × product × date
primary_key:
- CRM_CALL2_VOD_ID
- CALL2_VAE_GROUP_ID
join_keys:
- HCP_VID
- HCO_VID / SYSTEM_VID
- NPI_VOD
- TERRITORY_VOD
- CRM_USER_ID
refresh_cadence: daily
projection: census
measures: calls, emails, call credit, reach/frequency
phi_status: HCP business data; rep personal data
relations:
- predicate: generates_data
  target: /data-model/entities/call.md
---
# Definition
Rep and MSL interactions recorded in CRM: calls, approved emails (RTE), meetings, products discussed and samples.

# Grain & keys
* **Grain:** call (or call detail) × HCP/HCO × product × date
* **Primary key:** `CRM_CALL2_VOD_ID, CALL2_VAE_GROUP_ID`
* **Join keys:** `HCP_VID` → /identifiers/provider/veeva-vid.md, `HCO_VID / SYSTEM_VID` → /identifiers/provider/veeva-vid.md, `NPI_VOD` → /identifiers/provider/npi.md, `TERRITORY_VOD` → /data-model/entities/territory.md, `CRM_USER_ID` → /data-model/entities/rep.md
* **Refresh:** daily
* **Projection:** census
* **Measures:** calls, emails, call credit, reach/frequency
* **PHI status:** HCP business data; rep personal data

# Schema
Typical fields (vendor layouts differ; confirm against the data dictionary):

| Field | Meaning |
|---|---|
| `CRM_CALL2_VOD_ID, PARENT_CALL_VOD, IS_PARENT_CALL_VOD` | call hierarchy (parent/child attendees) |
| `CALL_DATE_VOD, CALL_TYPE, CALL_CHANNEL_VOD` | when/how |
| `CALL_RTE, EMAIL_TEMPLATE_NAME` | approved email |
| `PMC_PRODUCT, PRODUCTS` | products detailed |
| `HCP/HCO segments, deciles, KOL flags, priority categories` | targeting attributes |
| `ACTIVITY_CREDIT_HCP/HCO, CALL_CREDIT` | crediting |
| `TERRITORY_VOD, REGION_VOD` | alignment |

# Typical uses
* Reach & frequency vs call plan
* Promotion response modelling
* IC activity metrics

# Pitfalls
* Parent vs child calls double-count if not filtered
* Product-level detail rows multiply call counts

# Vendors / sources
Veeva CRM / Vault CRM, Salesforce Life Sciences Cloud, IQVIA OCE

# Relationships
* **generates_data** → [Call](/data-model/entities/call.md)

