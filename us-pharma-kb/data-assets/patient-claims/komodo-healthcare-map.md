---
type: Dataset Type
title: Komodo Healthcare Map
description: Komodo Health's linked, de-identified patient-journey dataset combining open and closed medical, pharmacy, lab and EHR data for 330M+ US patients.
tags:
- dataset
- patient-claims
generated:
  by: claude-opus-5.5/us-pharma-kb-builder
  at: '2026-10-02T00:00:00Z'
sources:
- id: komodo-map
  resource: https://www.komodohealth.com/product/healthcare-map/
  title: 'Komodo Health: Healthcare Map'
- id: komodo-method
  resource: https://www.komodohealth.com/reports-methodology/
  title: 'Komodo Health: standard methodology'
- id: komodo-dbx
  resource: https://marketplace.databricks.com/details/c904d4ae-6af0-41da-b6c7-1443c0aa0317/Komodo-Health_Healthcare-Map-via-Delta-Sharing
  title: Komodo Healthcare Map via Delta Sharing (Databricks Marketplace)
resource: https://www.komodohealth.com/product/healthcare-map/
dataset_category: patient-claims
grain: encounter / claim line × Komodo patient token
primary_key:
- encounter_id
join_keys:
- patient_token
- npi
- ndc/hcpcs
refresh_cadence: open sources daily–weekly; closed ≈ 1-month lag
projection: unprojected (open + closed)
measures: encounters, procedures, diagnoses, fills
phi_status: de-identified PHI
relations:
- predicate: provided_by
  target: /service-providers/vendors/komodo-health.md
---
# Definition
Komodo Health's linked, de-identified patient-journey dataset combining open and closed medical, pharmacy, lab and EHR data for 330M+ US patients.[^komodo-map][^komodo-method][^komodo-dbx]

# Grain & keys
* **Grain:** encounter / claim line × Komodo patient token
* **Primary key:** `encounter_id`
* **Join keys:** `patient_token` → /identifiers/patient/patient-token.md, `npi` → /identifiers/provider/npi.md, `ndc/hcpcs` → /identifiers/product/ndc.md
* **Refresh:** open sources daily–weekly; closed ≈ 1-month lag
* **Projection:** unprojected (open + closed)
* **Measures:** encounters, procedures, diagnoses, fills
* **PHI status:** de-identified PHI

# Schema
Typical fields (vendor layouts differ; confirm against the data dictionary):

| Field | Meaning |
|---|---|
| `patient token` | linked patient |
| `encounter` | one billable patient–provider encounter (duplicates consolidated) |
| `dx/px/ndc` | clinical codes |
| `payer channel` | insurance |

# Typical uses
* Patient finding & journey
* HCP/HCO treatment volume for targeting
* RWE/HEOR

# Pitfalls
* Uninsured patients and Kaiser California are not covered
* Closed lives (~160M/yr) are the subset to use for longitudinal denominators

# Vendors / sources
Komodo Health (also via Databricks Delta Sharing)

# Relationships
* **provided_by** → [Komodo Health](/service-providers/vendors/komodo-health.md)

[^komodo-map]: [Komodo Health: Healthcare Map](https://www.komodohealth.com/product/healthcare-map/)
[^komodo-method]: [Komodo Health: standard methodology](https://www.komodohealth.com/reports-methodology/)
[^komodo-dbx]: [Komodo Healthcare Map via Delta Sharing (Databricks Marketplace)](https://marketplace.databricks.com/details/c904d4ae-6af0-41da-b6c7-1443c0aa0317/Komodo-Health_Healthcare-Map-via-Delta-Sharing)
