---
type: Actor Class
title: Brand Manufacturer
description: Company holding an NDA/BLA that markets branded drugs, sets WAC, contracts with PBMs/GPOs and funds patient programmes.
tags:
- manufacturer
generated:
  by: claude-opus-5.5/us-pharma-kb-builder
  at: '2026-10-02T00:00:00Z'
relations:
- predicate: regulated_by
  target: /actors/regulators/fda.md
- predicate: submits_to
  target: /actors/regulators/cms.md
- predicate: contracts_with
  target: /actors/pbms/pbm.md
- predicate: generates_data
  target: /data-assets/sales-distribution/ex-factory-sales.md
---
# Definition
Company holding an NDA/BLA that markets branded drugs, sets WAC, contracts with PBMs/GPOs and funds patient programmes.

The commercial organisation (sales, marketing, market access, trade, GTN) is the main consumer of the datasets in this bundle.

# Relationships
* **regulated_by** → [FDA](/actors/regulators/fda.md)
* **submits_to** → [CMS](/actors/regulators/cms.md)
* **contracts_with** → [Pharmacy Benefit Manager (PBM)](/actors/pbms/pbm.md)
* **generates_data** → [Ex-Factory Sales (Sell-In)](/data-assets/sales-distribution/ex-factory-sales.md)

