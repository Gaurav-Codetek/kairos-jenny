---
type: Identifier
title: National Provider Identifier (NPI)
description: CMS-issued 10-digit ID; Type 1 = individual HCP, Type 2 = organisation.
tags:
- identifier
generated:
  by: claude-opus-5.5/us-pharma-kb-builder
  at: '2026-10-02T00:00:00Z'
sources:
- id: nppes
  resource: https://npiregistry.cms.hhs.gov/
  title: CMS NPPES NPI Registry
resource: https://npiregistry.cms.hhs.gov/
identifier_format: 10 digits, Luhn check
issuer: CMS NPPES
relations:
- predicate: identifies
  target: /data-model/entities/hcp.md
- predicate: identifies
  target: /data-model/entities/hco.md
- predicate: generates_data
  target: /data-assets/reference/nppes.md
---
# Definition
CMS-issued 10-digit ID; Type 1 = individual HCP, Type 2 = organisation.[^nppes]

# Relationships
* **identifies** → [HCP](/data-model/entities/hcp.md)
* **identifies** → [HCO](/data-model/entities/hco.md)
* **generates_data** → [NPPES NPI File](/data-assets/reference/nppes.md)

[^nppes]: [CMS NPPES NPI Registry](https://npiregistry.cms.hhs.gov/)
