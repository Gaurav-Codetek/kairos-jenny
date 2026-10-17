---
type: Transaction Standard
title: NCPDP Telecommunication D.0
description: HIPAA-named standard for real-time pharmacy claims (E1 eligibility, B1 bill, B2 reverse, B3 rebill).
tags:
- standard
- claims
generated:
  by: claude-opus-5.5/us-pharma-kb-builder
  at: '2026-10-02T00:00:00Z'
sources:
- id: ncpdp-d0
  resource: https://member.ncpdp.org/Member/media/pdf/VersionDQuestions.pdf
  title: NCPDP Telecommunication vD.0 Q&A
resource: https://member.ncpdp.org/Member/media/pdf/VersionDQuestions.pdf
relations:
- predicate: maintained_by
  target: /actors/standards/ncpdp.md
---
# Definition
HIPAA-named standard for real-time pharmacy claims (E1 eligibility, B1 bill, B2 reverse, B3 rebill).[^ncpdp-d0]

# Key fields
| Field | Meaning |
|---|---|
| 101-A1 BIN, 104-A4 PCN, 301-C1 Group | routing / benefit |
| 302-C2 Cardholder ID | member |
| 402-D2 Rx number, 403-D3 fill number | prescription identity |
| 405-D5 Days supply, 442-E7 Quantity | quantity |
| 407-D7 Product ID (NDC when 436-E1=03) | product |
| 408-D8 DAW | dispense-as-written |
| 411-DB Prescriber ID (NPI) | prescriber |
| 505-F5 Patient pay, 509-F9 Total paid | money |
| 511-FB Reject code | e.g. 70 not covered, 75 PA required, 76 plan limits |

# Relationships
* **maintained_by** → [NCPDP](/actors/standards/ncpdp.md)

[^ncpdp-d0]: [NCPDP Telecommunication vD.0 Q&A](https://member.ncpdp.org/Member/media/pdf/VersionDQuestions.pdf)
