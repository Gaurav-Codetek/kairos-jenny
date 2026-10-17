---
type: Dataset Type
title: Open Pharmacy (Rx) Claims
description: De-identified NCPDP claims captured from pharmacies and switches regardless of payer; broad but not enrollment-complete.
tags:
- dataset
- patient-claims
generated:
  by: claude-opus-5.5/us-pharma-kb-builder
  at: '2026-10-02T00:00:00Z'
sources:
- id: iqvia-data
  resource: https://www.iqvia.com/insights/the-iqvia-institute/available-iqvia-data
  title: 'IQVIA Institute: Available IQVIA Data'
resource: https://www.iqvia.com/insights/the-iqvia-institute/available-iqvia-data
dataset_category: patient-claims
grain: claim transaction (fill) × patient token
primary_key:
- claim_id
join_keys:
- patient_token
- npi
- ndc11
- bin_pcn_group
refresh_cadence: daily–weekly
projection: unprojected panel
measures: fills, days supply, quantity, patient pay, claim status
phi_status: de-identified PHI
relations:
- predicate: derived_from
  target: /claims/pharmacy/pharmacy-claim-flow.md
---
# Definition
De-identified NCPDP claims captured from pharmacies and switches regardless of payer; broad but not enrollment-complete.[^iqvia-data]

# Grain & keys
* **Grain:** claim transaction (fill) × patient token
* **Primary key:** `claim_id`
* **Join keys:** `patient_token` → /identifiers/patient/patient-token.md, `npi` → /identifiers/provider/npi.md, `ndc11` → /identifiers/product/ndc.md, `bin_pcn_group` → /identifiers/payer/bin-pcn-group.md
* **Refresh:** daily–weekly
* **Projection:** unprojected panel
* **Measures:** fills, days supply, quantity, patient pay, claim status
* **PHI status:** de-identified PHI

# Schema
Typical fields (vendor layouts differ; confirm against the data dictionary):

| Field | Meaning |
|---|---|
| `fill_date, written_date` | dates |
| `ndc11, quantity, days_supply` | product/qty |
| `prescriber npi, pharmacy id` | providers |
| `bin/pcn/group, plan_id` | payer |
| `claim_status, reject_code` | lifecycle |
| `patient_pay, copay_card_flag` | cost |

# Typical uses
* Patient starts, persistence, switching
* Payer mix and out-of-pocket

# Pitfalls
* Deduplicate rebills/reversals
* Coverage gaps → apparent discontinuation

# Vendors / sources
IQVIA LRx, Symphony, Komodo, HealthVerity

# Relationships
* **derived_from** → [Pharmacy Claim Flow](/claims/pharmacy/pharmacy-claim-flow.md)

[^iqvia-data]: [IQVIA Institute: Available IQVIA Data](https://www.iqvia.com/insights/the-iqvia-institute/available-iqvia-data)
