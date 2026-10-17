---
type: Data Flow
title: Prescription to Pharmacy Claim (hop by hop)
description: From the HCP's order to PBM rebate invoices, with the dataset captured at each hop.
tags:
- flow
generated:
  by: claude-opus-5.5/us-pharma-kb-builder
  at: '2026-10-02T00:00:00Z'
relations:
- predicate: related_to
  target: /claims/pharmacy/pharmacy-claim-flow.md
- predicate: generates_data
  target: /data-assets/rx-audit/iqvia-xponent.md
- predicate: generates_data
  target: /data-assets/patient-claims/iqvia-laad.md
---
# Definition
From the HCP's order to PBM rebate invoices, with the dataset captured at each hop.

| Hop | System | Standard | Captured as |
|---|---|---|---|
| 1 | HCP writes Rx in EHR | — | EHR data |
| 2 | Formulary / RTPB / med history | NCPDP F&B, RTPB | Surescripts |
| 3 | NewRx to pharmacy | NCPDP SCRIPT | network logs |
| 4 | Pharmacy claim via switch | NCPDP D.0 | open Rx claims (LRx, Komodo, Symphony) |
| 5 | PBM adjudication | D.0 response | closed claims; lifecycle (FIA/LAAD) |
| 6 | ePA if rejected (75) | NCPDP ePA | ePA data, hub data |
| 7 | Copay card secondary | D.0 COB | copay programme data |
| 8 | Pick-up or reversal | D.0 B2 | abandonment |
| 9 | Projection | — | Xponent, NPA |
| 10 | Rebate invoice | — | rebate utilisation |

# Relationships
* **related_to** → [Pharmacy Claim Flow](/claims/pharmacy/pharmacy-claim-flow.md)
* **generates_data** → [IQVIA Xponent (Prescriber-Level Rx)](/data-assets/rx-audit/iqvia-xponent.md)
* **generates_data** → [IQVIA LAAD (Longitudinal Access & Adjudication Data)](/data-assets/patient-claims/iqvia-laad.md)

