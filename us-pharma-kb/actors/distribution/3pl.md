---
type: Actor Class
title: Third-Party Logistics Provider (3PL)
description: Warehouses manufacturer-owned inventory and ships orders to wholesalers and direct accounts; often also runs order-to-cash and sends 867 sales data.
tags:
- distribution
- 3pl
generated:
  by: claude-opus-5.5/us-pharma-kb-builder
  at: '2026-10-02T00:00:00Z'
sources:
- id: cencora-3pl
  resource: https://www.cencora.com/our-capabilities/logistics-and-warehousing/third-party-logistics
  title: Cencora third-party logistics (ICS)
- id: cencora-title
  resource: https://www.cencora.com/solutions/title-model-solutions
  title: Cencora/ICS Title Model
resource: https://www.cencora.com/our-capabilities/logistics-and-warehousing/third-party-logistics
relations:
- predicate: regulated_by
  target: /regulation/statutes/dscsa.md
- predicate: generates_data
  target: /data-assets/sales-distribution/edi-867-3pl.md
---
# Definition
Warehouses manufacturer-owned inventory and ships orders to wholesalers and direct accounts; often also runs order-to-cash and sends 867 sales data.[^cencora-3pl][^cencora-title]

Under the traditional 3PL model the manufacturer keeps title; under a *title model* the 3PL (e.g. ICS) takes title, which lets a manufacturer launch before holding every state distribution licence. 3PLs transact via EDI 940/945 with the manufacturer and 850/855/856/810 with customers.

# Relationships
* **regulated_by** → [Drug Supply Chain Security Act](/regulation/statutes/dscsa.md)
* **generates_data** → [3PL 867 (Direct Sales Through a 3PL)](/data-assets/sales-distribution/edi-867-3pl.md)

[^cencora-3pl]: [Cencora third-party logistics (ICS)](https://www.cencora.com/our-capabilities/logistics-and-warehousing/third-party-logistics)
[^cencora-title]: [Cencora/ICS Title Model](https://www.cencora.com/solutions/title-model-solutions)
