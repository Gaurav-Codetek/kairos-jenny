---
type: Dataset Type
title: 3PL 867 (Direct Sales Through a 3PL)
description: 867-format sales and returns from a manufacturer's 3PL, covering orders the 3PL ships directly to wholesalers, specialty distributors or end accounts.
tags:
- dataset
- sales-distribution
generated:
  by: claude-opus-5.5/us-pharma-kb-builder
  at: '2026-10-02T00:00:00Z'
sources:
- id: cencora-3pl
  resource: https://www.cencora.com/our-capabilities/logistics-and-warehousing/third-party-logistics
  title: Cencora third-party logistics (ICS)
resource: https://www.cencora.com/our-capabilities/logistics-and-warehousing/third-party-logistics
dataset_category: sales-distribution
grain: invoice line × customer × NDC × date
primary_key:
- invoice_id
- invoice_item
- ship_to
join_keys:
- cust_dea
- cust_hin
- ndc
refresh_cadence: daily
projection: census
measures: direct sales units and $
phi_status: none (B2B)
relations:
- predicate: derived_from
  target: /distribution-edi/edi-867.md
- predicate: provided_by
  target: /actors/distribution/3pl.md
---
# Definition
867-format sales and returns from a manufacturer's 3PL, covering orders the 3PL ships directly to wholesalers, specialty distributors or end accounts.[^cencora-3pl]

# Grain & keys
* **Grain:** invoice line × customer × NDC × date
* **Primary key:** `invoice_id, invoice_item, ship_to`
* **Join keys:** `cust_dea` → /identifiers/provider/dea-number.md, `cust_hin` → /identifiers/provider/hin.md, `ndc` → /identifiers/product/ndc.md
* **Refresh:** daily
* **Projection:** census
* **Measures:** direct sales units and $
* **PHI status:** none (B2B)

# Schema
Typical fields (vendor layouts differ; confirm against the data dictionary):

| Field | Meaning |
|---|---|
| `invoice_id / invoice_item` | line |
| `customer name/address/DEA/HIN` | buyer |
| `ndc` | product |
| `quantity_sold / quantity_returned` | units |
| `wac / amount` | $ |
| `contract_id` | contract |

# Typical uses
* Primary sales source for small/specialty manufacturers selling direct to hospitals and clinics

# Pitfalls
* For many specialty products the 3PL 867 is the only account-level sales source

# Vendors / sources
ICS (Cencora), UPS Healthcare, other 3PLs

# Relationships
* **derived_from** → [EDI 867 Product Transfer & Resale Report](/distribution-edi/edi-867.md)
* **provided_by** → [Third-Party Logistics Provider (3PL)](/actors/distribution/3pl.md)

[^cencora-3pl]: [Cencora third-party logistics (ICS)](https://www.cencora.com/our-capabilities/logistics-and-warehousing/third-party-logistics)
