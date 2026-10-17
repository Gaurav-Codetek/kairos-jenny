---
type: Dataset Type
title: Specialty Pharmacy Data Feed
description: Status and dispense records from network SPs (referral received, PA pending, shipped, discontinued).
tags:
- dataset
- access
generated:
  by: claude-opus-5.5/us-pharma-kb-builder
  at: '2026-10-02T00:00:00Z'
dataset_category: access
grain: patient × status event / dispense
primary_key:
- sp_id
- sp_patient_id
- event_ts
join_keys:
- patient_token
- npi
- ndc
refresh_cadence: daily
projection: census for network SPs
measures: referrals, shipments, discontinuations
phi_status: PHI or pseudonymised
relations:
- predicate: provided_by
  target: /actors/pharmacies/specialty-pharmacy.md
---
# Definition
Status and dispense records from network SPs (referral received, PA pending, shipped, discontinued).

# Grain & keys
* **Grain:** patient × status event / dispense
* **Primary key:** `sp_id, sp_patient_id, event_ts`
* **Join keys:** `patient_token` → /identifiers/patient/patient-token.md, `npi` → /identifiers/provider/npi.md, `ndc` → /identifiers/product/ndc.md
* **Refresh:** daily
* **Projection:** census for network SPs
* **Measures:** referrals, shipments, discontinuations
* **PHI status:** PHI or pseudonymised

# Schema
Typical fields (vendor layouts differ; confirm against the data dictionary):

| Field | Meaning |
|---|---|
| `status_code` | NCPDP/HUB status |
| `ship_date, qty` | dispense |

# Typical uses
* Specialty demand
* Patient adherence

# Pitfalls
* Status codes vary by SP — normalise

# Vendors / sources
SPs via aggregators (IntegriChain, Model N)

# Relationships
* **provided_by** → [Specialty Pharmacy (SP)](/actors/pharmacies/specialty-pharmacy.md)

