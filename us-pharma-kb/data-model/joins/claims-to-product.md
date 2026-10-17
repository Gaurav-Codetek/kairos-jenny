---
type: Join Path
title: Claims → Product
description: Normalise NDC to 11 digits → drug mapping/product master → NDC-9 roll-up; for medical lines use HCPCS → NDC crosswalk with unit conversion.
tags:
- join
generated:
  by: claude-opus-5.5/us-pharma-kb-builder
  at: '2026-10-02T00:00:00Z'
relations:
- predicate: joins_to
  target: /data-assets/reference/drug-mapping.md
- predicate: joins_to
  target: /reference-data/ndc-hcpcs-crosswalk.md
---
# Definition
Normalise NDC to 11 digits → drug mapping/product master → NDC-9 roll-up; for medical lines use HCPCS → NDC crosswalk with unit conversion.

# Relationships
* **joins_to** → [Claims Drug Mapping (NDC → Product/Market)](/data-assets/reference/drug-mapping.md)
* **joins_to** → [NDC–HCPCS Crosswalk](/reference-data/ndc-hcpcs-crosswalk.md)

