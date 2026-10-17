---
type: Identifier
title: HCPCS Level II (J-codes)
description: CMS codes for physician-administered drugs on medical claims; billing units differ from NDC units.
tags:
- identifier
generated:
  by: claude-opus-5.5/us-pharma-kb-builder
  at: '2026-10-02T00:00:00Z'
identifier_format: 1 letter + 4 digits
issuer: CMS
relations:
- predicate: joins_to
  target: /identifiers/product/ndc.md
- predicate: used_in
  target: /claims/medical/x12-837p.md
---
# Definition
CMS codes for physician-administered drugs on medical claims; billing units differ from NDC units.

# Relationships
* **joins_to** → [National Drug Code (NDC)](/identifiers/product/ndc.md)
* **used_in** → [X12 837P (Professional)](/claims/medical/x12-837p.md)

