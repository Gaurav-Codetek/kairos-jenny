---
type: Dataset Type
title: Komodo Claims Extracts (Mx / Rx)
description: Brand- or market-specific patient-level medical and pharmacy claims extracts delivered from the Healthcare Map.
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
resource: https://www.komodohealth.com/product/healthcare-map/
dataset_category: patient-claims
grain: claim line × patient token
primary_key:
- claim_id
- line_number
join_keys:
- patient_token
- npi
- hcpcs/ndc
refresh_cadence: weekly or monthly
projection: unprojected
measures: claims, patients, volume
phi_status: de-identified PHI
relations:
- predicate: derived_from
  target: /data-assets/patient-claims/komodo-healthcare-map.md
- predicate: feeds
  target: /data-assets/provider-aggregates/komodo-claims-by-provider.md
---
# Definition
Brand- or market-specific patient-level medical and pharmacy claims extracts delivered from the Healthcare Map.[^komodo-map]

# Grain & keys
* **Grain:** claim line × patient token
* **Primary key:** `claim_id, line_number`
* **Join keys:** `patient_token` → /identifiers/patient/patient-token.md, `npi` → /identifiers/provider/npi.md, `hcpcs/ndc` → /identifiers/product/hcpcs.md
* **Refresh:** weekly or monthly
* **Projection:** unprojected
* **Measures:** claims, patients, volume
* **PHI status:** de-identified PHI

# Schema
Typical fields (vendor layouts differ; confirm against the data dictionary):

| Field | Meaning |
|---|---|
| `service date` | date |
| `hcpcs/ndc` | drug |
| `rendering/billing npi` | providers |
| `dx codes` | indication |
| `payer channel` | payer |

# Typical uses
* IV/infused-drug administration counts by site of care
* Hemodialysis vs non-hemodialysis segmentation (e.g. IV iron)

# Pitfalls
* Extract scope is defined by the licence (market basket, dates)

# Vendors / sources
Komodo Health

# Relationships
* **derived_from** → [Komodo Healthcare Map](/data-assets/patient-claims/komodo-healthcare-map.md)
* **feeds** → [Komodo Claims by Provider (HCP × Affiliation Aggregate)](/data-assets/provider-aggregates/komodo-claims-by-provider.md)

[^komodo-map]: [Komodo Health: Healthcare Map](https://www.komodohealth.com/product/healthcare-map/)
