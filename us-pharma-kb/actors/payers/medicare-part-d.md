---
type: Program
title: Medicare Part D
description: Outpatient drug benefit for Medicare beneficiaries delivered by private PDP/MA-PD plans.
tags:
- payer
- medicare
generated:
  by: claude-opus-5.5/us-pharma-kb-builder
  at: '2026-10-02T00:00:00Z'
stale_after: '2027-01-01T00:00:00Z'
sources:
- id: kff-partd
  resource: https://www.kff.org/medicare/a-current-snapshot-of-the-medicare-part-d-prescription-drug-benefit/
  title: 'KFF: Part D snapshot'
- id: cms-partd-2026
  resource: https://www.cms.gov/newsroom/fact-sheets/final-cy-2026-part-d-redesign-program-instructions
  title: 'CMS: CY2026 Part D redesign'
resource: https://www.kff.org/medicare/a-current-snapshot-of-the-medicare-part-d-prescription-drug-benefit/
relations:
- predicate: regulated_by
  target: /actors/regulators/cms.md
- predicate: related_to
  target: /regulation/statutes/ira.md
---
# Definition
Outpatient drug benefit for Medicare beneficiaries delivered by private PDP/MA-PD plans.[^kff-partd][^cms-partd-2026]

2026: $615 deductible, $2,100 out-of-pocket cap; manufacturers pay 10% in the initial phase and 20% in catastrophic under the Manufacturer Discount Program.

# Relationships
* **regulated_by** → [CMS](/actors/regulators/cms.md)
* **related_to** → [Inflation Reduction Act (drug provisions)](/regulation/statutes/ira.md)

[^kff-partd]: [KFF: Part D snapshot](https://www.kff.org/medicare/a-current-snapshot-of-the-medicare-part-d-prescription-drug-benefit/)
[^cms-partd-2026]: [CMS: CY2026 Part D redesign](https://www.cms.gov/newsroom/fact-sheets/final-cy-2026-part-d-redesign-program-instructions)
