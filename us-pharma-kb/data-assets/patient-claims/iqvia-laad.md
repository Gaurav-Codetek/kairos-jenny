---
type: Dataset Type
title: IQVIA LAAD (Longitudinal Access & Adjudication Data)
description: Patient-level dataset combining IQVIA Rx, lifecycle (paid/rejected/reversed), medical and remittance claims; includes copay card, source-of-business and new-to-brand flags.
tags:
- dataset
- patient-claims
generated:
  by: claude-opus-5.5/us-pharma-kb-builder
  at: '2026-10-02T00:00:00Z'
sources:
- id: iqvia-laad
  resource: https://www.iqvia.com/-/media/iqvia/pdfs/library/fact-sheets/iqvia-longitudinal-access-and-adjudication-data-fact-sheet-2023.pdf
  title: IQVIA LAAD fact sheet
- id: iqvia-laad-plus
  resource: https://www.iqvia.com/locations/united-states/solutions/life-sciences/information-solutions/laad-plus
  title: IQVIA LAAD Plus
resource: https://www.iqvia.com/-/media/iqvia/pdfs/library/fact-sheets/iqvia-longitudinal-access-and-adjudication-data-fact-sheet-2023.pdf
dataset_category: patient-claims
grain: claim transaction × patient (Rx) / claim line (Mx)
primary_key:
- CLAIM_ID
- SEQUENCE_NUMBER
join_keys:
- PATIENT_ID
- PROVIDER_ID / NPI_NUMBER
- NDC11
- PLAN_ID
- USC_CODE / CMF10
refresh_cadence: weekly / monthly
projection: unprojected panel
measures: paid/rejected/reversed claims, copay, OOP, NBRx, source of business
phi_status: de-identified PHI
relations:
- predicate: provided_by
  target: /service-providers/vendors/iqvia.md
- predicate: derived_from
  target: /data-assets/patient-claims/iqvia-lrx.md
- predicate: derived_from
  target: /data-assets/patient-claims/iqvia-fia.md
---
# Definition
Patient-level dataset combining IQVIA Rx, lifecycle (paid/rejected/reversed), medical and remittance claims; includes copay card, source-of-business and new-to-brand flags.[^iqvia-laad][^iqvia-laad-plus]

# Grain & keys
* **Grain:** claim transaction × patient (Rx) / claim line (Mx)
* **Primary key:** `CLAIM_ID, SEQUENCE_NUMBER`
* **Join keys:** `PATIENT_ID` → /identifiers/patient/patient-token.md, `PROVIDER_ID / NPI_NUMBER` → /identifiers/provider/npi.md, `NDC11` → /identifiers/product/ndc.md, `PLAN_ID` → /identifiers/payer/plan-id.md, `USC_CODE / CMF10` → /identifiers/product/usc.md
* **Refresh:** weekly / monthly
* **Projection:** unprojected panel
* **Measures:** paid/rejected/reversed claims, copay, OOP, NBRx, source of business
* **PHI status:** de-identified PHI

# Schema
Typical fields (vendor layouts differ; confirm against the data dictionary):

| Field | Meaning |
|---|---|
| `CLAIM_ID, INITIAL_CLAIM_ID, SEQUENCE_NUMBER` | claim lineage across rejection → approval |
| `CLAIM_TYPE, CLAIM_STATUS, REJECT_CODE` | lifecycle |
| `FILL_DATE, WRITTEN_DATE, DAYS_SUPPLY, QUANTITY, REFILL_CODE` | fill |
| `PLAN_ID, SECONDARY_PLAN_ID, CHANNEL` | payer |
| `PATIENT_COPAY, PATIENT_OPC, BUY_DOWN, COPAY_CARD_FLAG` | patient cost & assistance |
| `NEW_TO_BRAND_YN, SOURCE_OF_BUSINESS` | dynamics |
| `DIAGNOSIS_CODE_1-8, PROCEDURE_CODE, MODIFIER_CODE_1-4, PLACE_OF_SERVICE_CODE` | medical (Mx) lines |
| `REFERRING/BILLING/FACILITY_PROVIDER_ID` | Mx providers |

# Typical uses
* Access analytics: approval/rejection/abandonment rates
* Copay-card penetration
* NBRx and switching
* Patient journey

# Pitfalls
* Count paid final claims for utilisation; keep rejected claims only for access KPIs
* Rx and Mx rows share one table with different populated columns (DATA_SOURCE/Flag)

# Vendors / sources
IQVIA

# Relationships
* **provided_by** → [IQVIA](/service-providers/vendors/iqvia.md)
* **derived_from** → [IQVIA LRx (Longitudinal Prescription Claims)](/data-assets/patient-claims/iqvia-lrx.md)
* **derived_from** → [IQVIA FIA (Formulary Impact Analyzer / Lifecycle Claims)](/data-assets/patient-claims/iqvia-fia.md)

[^iqvia-laad]: [IQVIA LAAD fact sheet](https://www.iqvia.com/-/media/iqvia/pdfs/library/fact-sheets/iqvia-longitudinal-access-and-adjudication-data-fact-sheet-2023.pdf)
[^iqvia-laad-plus]: [IQVIA LAAD Plus](https://www.iqvia.com/locations/united-states/solutions/life-sciences/information-solutions/laad-plus)
