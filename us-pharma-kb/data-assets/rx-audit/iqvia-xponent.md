---
type: Dataset Type
title: IQVIA Xponent (Prescriber-Level Rx)
description: Projected weekly dispensed prescriptions by prescriber and product across retail, mail and LTC.
tags:
- dataset
- rx-audit
generated:
  by: claude-opus-5.5/us-pharma-kb-builder
  at: '2026-10-02T00:00:00Z'
sources:
- id: iqvia-xponent
  resource: https://www.iqvia.com/-/media/iqvia/pdfs/us/fact-sheet/2022/iqvia-xponent-fact-sheet-2024.pdf
  title: IQVIA Xponent fact sheet
- id: iqvia-data
  resource: https://www.iqvia.com/insights/the-iqvia-institute/available-iqvia-data
  title: 'IQVIA Institute: Available IQVIA Data'
resource: https://www.iqvia.com/-/media/iqvia/pdfs/us/fact-sheet/2022/iqvia-xponent-fact-sheet-2024.pdf
dataset_category: rx-audit
grain: prescriber × product group × payer plan × week
primary_key:
- IMS_PRESCRIBER_ID
- PRODUCT_GROUP_ID
- PAYER_PLAN_ID
- DATA_DATE
join_keys:
- NPI_ID
- ME_NUMBER
- IMS_PRESCRIBER_ID
- PRODUCT_GROUP_ID
- PAYER_PLAN_ID
refresh_cadence: weekly
projection: sample-projected
measures: TRx, NRx, units (by SALES_CATEGORY)
phi_status: prescriber-identifiable (no patient PHI); AMA PDRP applies
relations:
- predicate: provided_by
  target: /service-providers/vendors/iqvia.md
- predicate: measures
  target: /prescriptions/metrics/trx.md
- predicate: restricted_by
  target: /regulation/state-law/ama-pdrp.md
---
# Definition
Projected weekly dispensed prescriptions by prescriber and product across retail, mail and LTC.[^iqvia-xponent][^iqvia-data]

# Grain & keys
* **Grain:** prescriber × product group × payer plan × week
* **Primary key:** `IMS_PRESCRIBER_ID, PRODUCT_GROUP_ID, PAYER_PLAN_ID, DATA_DATE`
* **Join keys:** `NPI_ID` → /identifiers/provider/npi.md, `ME_NUMBER` → /identifiers/provider/ama-me-number.md, `IMS_PRESCRIBER_ID` → /identifiers/provider/ims-prescriber-id.md, `PRODUCT_GROUP_ID` → /identifiers/product/cmf.md, `PAYER_PLAN_ID` → /identifiers/payer/plan-id.md
* **Refresh:** weekly
* **Projection:** sample-projected
* **Measures:** TRx, NRx, units (by SALES_CATEGORY)
* **PHI status:** prescriber-identifiable (no patient PHI); AMA PDRP applies

# Schema
Typical fields (vendor layouts differ; confirm against the data dictionary):

| Field | Meaning |
|---|---|
| `CLIENT_NUMBER, REPORT_NUMBER` | delivery |
| `IMS_PRESCRIBER_ID, NPI_ID, ME_NUMBER` | prescriber |
| `SPECIALTY_CODE, PROFESSION_CODE` | specialty |
| `PAYER_PLAN_ID` | plan (PlanTrak) |
| `PRODUCT_GROUP_ID` | product |
| `SALES_CATEGORY` | measure (NRx/TRx/units) |
| `<week columns>` | often delivered wide |

# Typical uses
* HCP targeting & deciling
* Territory performance and IC
* Promotion response

# Pitfalls
* Projected — not additive to claims
* Payer-split version = Xponent PlanTrak

# Vendors / sources
IQVIA

# Relationships
* **provided_by** → [IQVIA](/service-providers/vendors/iqvia.md)
* **measures** → [TRx (Total Prescriptions)](/prescriptions/metrics/trx.md)
* **restricted_by** → [AMA Physician Data Restriction Program](/regulation/state-law/ama-pdrp.md)

[^iqvia-xponent]: [IQVIA Xponent fact sheet](https://www.iqvia.com/-/media/iqvia/pdfs/us/fact-sheet/2022/iqvia-xponent-fact-sheet-2024.pdf)
[^iqvia-data]: [IQVIA Institute: Available IQVIA Data](https://www.iqvia.com/insights/the-iqvia-institute/available-iqvia-data)
