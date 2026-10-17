---
type: Dataset Type
title: Komodo Claims by Provider (HCP × Affiliation Aggregate)
description: Komodo claims aggregated to HCP with affiliated organisation and system, rolling time windows (C3M/C6M/C12M), total vs non-hemodialysis volume and claims.
tags:
- dataset
- provider-aggregates
- komodo
generated:
  by: claude-opus-5.5/us-pharma-kb-builder
  at: '2026-10-02T00:00:00Z'
sources:
- id: komodo-map
  resource: https://www.komodohealth.com/product/healthcare-map/
  title: 'Komodo Health: Healthcare Map'
resource: https://www.komodohealth.com/product/healthcare-map/
dataset_category: provider-aggregates
grain: HCP × affiliated org × affiliated system × period
primary_key:
- HCP_VID
- AFFILIATED_ORG_VID
- AFFILIATED_SYSTEM_VID
- YEARMONTH
join_keys:
- HCP_VID
- AFFILIATED_ORG_VID
- AFFILIATED_SYSTEM_VID
- PROVIDER_ZIP
refresh_cadence: monthly
projection: unprojected
measures: TOTAL_VOLUME, NON_HEMODIALYSIS_VOLUME, TOTAL_CLAIMS, NON_HEMODIALYSIS_CLAIMS
phi_status: no patient PHI; PDRP flag applies
relations:
- predicate: derived_from
  target: /data-assets/patient-claims/komodo-claims.md
- predicate: joins_to
  target: /data-assets/promotion/crm-calls.md
---
# Definition
Komodo claims aggregated to HCP with affiliated organisation and system, rolling time windows (C3M/C6M/C12M), total vs non-hemodialysis volume and claims.[^komodo-map]

# Grain & keys
* **Grain:** HCP × affiliated org × affiliated system × period
* **Primary key:** `HCP_VID, AFFILIATED_ORG_VID, AFFILIATED_SYSTEM_VID, YEARMONTH`
* **Join keys:** `HCP_VID` → /identifiers/provider/veeva-vid.md, `AFFILIATED_ORG_VID` → /data-model/entities/hco.md, `AFFILIATED_SYSTEM_VID` → /actors/providers/idn.md, `PROVIDER_ZIP` → /data-assets/reference/zip-to-territory.md
* **Refresh:** monthly
* **Projection:** unprojected
* **Measures:** TOTAL_VOLUME, NON_HEMODIALYSIS_VOLUME, TOTAL_CLAIMS, NON_HEMODIALYSIS_CLAIMS
* **PHI status:** no patient PHI; PDRP flag applies

# Schema
Typical fields (vendor layouts differ; confirm against the data dictionary):

| Field | Meaning |
|---|---|
| `HCP_VID, PROVIDER_* (name, address, degree, specialty 1/2, status)` | HCP profile |
| `PROVIDER_PDRP_OPT_OUT_FLAG` | AMA PDRP |
| `YEARMONTH, QUARTER, TRIMESTER, YEAR, C3M/C6M/C12M_TIMEFRAME` | time windows |
| `AFFILIATED_ORG_* / AFFILIATED_SYSTEM_*` | affiliation |
| `BRANDS` | products in scope |
| `TOTAL_* / NON_HEMODIALYSIS_*` | measures |
| `DATA_PERIOD` | delivery period |

# Typical uses
* HCP targeting for IV/infused brands (e.g. IV iron)
* Joining claims volume to CRM calls on HCP_VID

# Pitfalls
* Rolling-window flags overlap — filter one timeframe
* ZIP stored as DOUBLE (leading zeros lost)
* Grain key uniqueness not yet verified

# Vendors / sources
Komodo Health (aggregated by client/agency)

# Relationships
* **derived_from** → [Komodo Claims Extracts (Mx / Rx)](/data-assets/patient-claims/komodo-claims.md)
* **joins_to** → [CRM Call Activity (Veeva)](/data-assets/promotion/crm-calls.md)

[^komodo-map]: [Komodo Health: Healthcare Map](https://www.komodohealth.com/product/healthcare-map/)
