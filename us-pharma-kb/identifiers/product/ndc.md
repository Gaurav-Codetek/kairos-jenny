---
type: Identifier
title: National Drug Code (NDC)
description: FDA three-segment product identifier (labeler-product-package) for US drugs.
tags:
- identifier
generated:
  by: claude-opus-5.5/us-pharma-kb-builder
  at: '2026-10-02T00:00:00Z'
sources:
- id: fda-ndc
  resource: https://www.fda.gov/drugs/drug-approvals-and-databases/national-drug-code-directory
  title: FDA National Drug Code Directory
resource: https://www.fda.gov/drugs/drug-approvals-and-databases/national-drug-code-directory
identifier_format: 10-digit 4-4-2 | 5-3-2 | 5-4-1; HIPAA billing 11-digit 5-4-2
issuer: FDA (labeler code) + labeler
relations:
- predicate: assigned_by
  target: /actors/regulators/fda.md
- predicate: identifies
  target: /data-model/entities/product.md
- predicate: superseded_by
  target: /identifiers/product/ndc-12.md
- predicate: used_in
  target: /claims/pharmacy/ncpdp-telecom-d0.md
---
# Definition
FDA three-segment product identifier (labeler-product-package) for US drugs.[^fda-ndc]

* Claims use the 11-digit 5-4-2 form (zero-padded, no dashes). Common column names: `NDC11`, `NDC_CODE` (with an `NDC_QUALIFIER` in EDI feeds).
* `ndc9` (labeler+product) is the package-agnostic product key used to roll up packs.
* An 11-digit NDC cannot be reliably converted back to 10 digits without the FDA listing.

# Relationships
* **assigned_by** → [FDA](/actors/regulators/fda.md)
* **identifies** → [Product](/data-model/entities/product.md)
* **superseded_by** → [NDC-12 (6-4-2)](/identifiers/product/ndc-12.md)
* **used_in** → [NCPDP Telecommunication D.0](/claims/pharmacy/ncpdp-telecom-d0.md)

[^fda-ndc]: [FDA National Drug Code Directory](https://www.fda.gov/drugs/drug-approvals-and-databases/national-drug-code-directory)
