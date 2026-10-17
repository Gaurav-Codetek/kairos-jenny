---
type: Data Flow
title: Pharmacy Claim Flow
description: Pharmacy → switch → PBM real-time adjudication → response → (optional COB/copay secondary) → reversal if not picked up → PBM invoices plan and manufacturer.
tags:
- claims
- pharmacy
generated:
  by: claude-opus-5.5/us-pharma-kb-builder
  at: '2026-10-02T00:00:00Z'
sources:
- id: ncpdp-d0
  resource: https://member.ncpdp.org/Member/media/pdf/VersionDQuestions.pdf
  title: NCPDP Telecommunication vD.0 Q&A
resource: https://member.ncpdp.org/Member/media/pdf/VersionDQuestions.pdf
relations:
- predicate: uses_standard
  target: /claims/pharmacy/ncpdp-telecom-d0.md
- predicate: adjudicated_by
  target: /actors/pbms/pbm.md
- predicate: generates_data
  target: /data-assets/patient-claims/pharmacy-claims-open.md
- predicate: generates_data
  target: /data-assets/patient-claims/iqvia-laad.md
---
# Definition
Pharmacy → switch → PBM real-time adjudication → response → (optional COB/copay secondary) → reversal if not picked up → PBM invoices plan and manufacturer.[^ncpdp-d0]

# Steps
1. Pharmacy builds a B1 billing request with BIN/PCN/Group, cardholder, NDC (407-D7), quantity (442-E7), days supply (405-D5), prescriber (411-DB).
2. A switch (Change Healthcare/Optum, RelayHealth) routes on BIN/PCN and may de-identify and sell a copy (source of open Rx claims).
3. PBM checks eligibility, formulary, DUR, prices; responds paid or rejected (511-FB reject codes).
4. Copay card or other coverage billed as a secondary claim.
5. Unclaimed fills reversed (B2) — lifecycle data (FIA/LAAD) keeps paid, rejected and reversed states.

# Relationships
* **uses_standard** → [NCPDP Telecommunication D.0](/claims/pharmacy/ncpdp-telecom-d0.md)
* **adjudicated_by** → [Pharmacy Benefit Manager (PBM)](/actors/pbms/pbm.md)
* **generates_data** → [Open Pharmacy (Rx) Claims](/data-assets/patient-claims/pharmacy-claims-open.md)
* **generates_data** → [IQVIA LAAD (Longitudinal Access & Adjudication Data)](/data-assets/patient-claims/iqvia-laad.md)

[^ncpdp-d0]: [NCPDP Telecommunication vD.0 Q&A](https://member.ncpdp.org/Member/media/pdf/VersionDQuestions.pdf)
