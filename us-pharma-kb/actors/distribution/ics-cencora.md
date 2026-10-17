---
type: Vendor
title: ICS (Integrated Commercialization Solutions, Cencora)
description: Cencora's North American 3PL brand; ships manufacturer product and delivers ICS 867 sales/returns data and analytics.
tags:
- 3pl
- cencora
- ics
generated:
  by: claude-opus-5.5/us-pharma-kb-builder
  at: '2026-10-02T00:00:00Z'
sources:
- id: cencora-3pl
  resource: https://www.cencora.com/our-capabilities/logistics-and-warehousing/third-party-logistics
  title: Cencora third-party logistics (ICS)
- id: cencora-ics-data
  resource: https://www.cencora.com/resources/human-health/connecting-the-data-dots
  title: 'Cencora/ICS: Connecting the data dots'
- id: cencora-title
  resource: https://www.cencora.com/solutions/title-model-solutions
  title: Cencora/ICS Title Model
resource: https://www.cencora.com/our-capabilities/logistics-and-warehousing/third-party-logistics
relations:
- predicate: is_a
  target: /actors/distribution/3pl.md
- predicate: generates_data
  target: /data-assets/sales-distribution/ics-867.md
- predicate: part_of
  target: /actors/distribution/full-line-wholesaler.md
---
# Definition
Cencora's North American 3PL brand; ships manufacturer product and delivers ICS 867 sales/returns data and analytics.[^cencora-3pl][^cencora-ics-data][^cencora-title]

ICS (formerly an AmerisourceBergen business, now part of Cencora) provides 3PL, title-model distribution and order-to-cash services. It has offered analytics to manufacturers for more than 20 years, including connecting chargeback data to 867 data. Manufacturers that use ICS as their 3PL receive the *ICS 867* feed from it.

# Relationships
* **is_a** → [Third-Party Logistics Provider (3PL)](/actors/distribution/3pl.md)
* **generates_data** → [ICS 867 (Cencora ICS 3PL Sales Feed)](/data-assets/sales-distribution/ics-867.md)
* **part_of** → [Full-Line Wholesaler](/actors/distribution/full-line-wholesaler.md)

[^cencora-3pl]: [Cencora third-party logistics (ICS)](https://www.cencora.com/our-capabilities/logistics-and-warehousing/third-party-logistics)
[^cencora-ics-data]: [Cencora/ICS: Connecting the data dots](https://www.cencora.com/resources/human-health/connecting-the-data-dots)
[^cencora-title]: [Cencora/ICS Title Model](https://www.cencora.com/solutions/title-model-solutions)
