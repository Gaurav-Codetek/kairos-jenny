---
type: Identifier
title: BIN / PCN / Group
description: 'Pharmacy-benefit routing triplet: BIN (processor), PCN (plan/line of business), Group (employer/benefit).'
tags:
- identifier
generated:
  by: claude-opus-5.5/us-pharma-kb-builder
  at: '2026-10-02T00:00:00Z'
sources:
- id: ncpdp-d0
  resource: https://member.ncpdp.org/Member/media/pdf/VersionDQuestions.pdf
  title: NCPDP Telecommunication vD.0 Q&A
resource: https://member.ncpdp.org/Member/media/pdf/VersionDQuestions.pdf
identifier_format: BIN 6 digits; PCN/Group up to 10/15 chars
issuer: Processors/PBMs
relations:
- predicate: used_in
  target: /claims/pharmacy/ncpdp-telecom-d0.md
- predicate: identifies
  target: /data-model/entities/payer-plan.md
---
# Definition
Pharmacy-benefit routing triplet: BIN (processor), PCN (plan/line of business), Group (employer/benefit).[^ncpdp-d0]

Used to infer channel: commercial vs Medicare Part D vs Medicaid vs copay card (secondary).

# Relationships
* **used_in** → [NCPDP Telecommunication D.0](/claims/pharmacy/ncpdp-telecom-d0.md)
* **identifies** → [Payer / Plan](/data-model/entities/payer-plan.md)

[^ncpdp-d0]: [NCPDP Telecommunication vD.0 Q&A](https://member.ncpdp.org/Member/media/pdf/VersionDQuestions.pdf)
