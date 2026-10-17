---
type: Dataset Type
title: Wholesaler / Specialty Distributor 867 (Sell-Through)
description: Downstream resale lines from a wholesaler or specialty distributor to each ship-to account (hospital, clinic, pharmacy), including returns.
tags:
- dataset
- sales-distribution
generated:
  by: claude-opus-5.5/us-pharma-kb-builder
  at: '2026-10-02T00:00:00Z'
sources:
- id: edi-867
  resource: https://www.partnerlinq.com/edi-transaction/edi-867-product-transfer-and-resale-report-x12
  title: EDI 867 Product Transfer and Resale Report
resource: https://www.partnerlinq.com/edi-transaction/edi-867-product-transfer-and-resale-report-x12
dataset_category: sales-distribution
grain: invoice line × ship-to account × NDC × date
primary_key:
- distributor_id
- invoice_id
- invoice_line
join_keys:
- ship_to_dea
- ship_to_hin
- ndc11
- contract_id
refresh_cadence: daily or weekly
projection: census for participating distributors
measures: sell-through units, gross $ at WAC or contract price
phi_status: none (B2B; addresses are business data)
relations:
- predicate: derived_from
  target: /distribution-edi/edi-867.md
- predicate: provided_by
  target: /actors/distribution/full-line-wholesaler.md
---
# Definition
Downstream resale lines from a wholesaler or specialty distributor to each ship-to account (hospital, clinic, pharmacy), including returns.[^edi-867]

# Grain & keys
* **Grain:** invoice line × ship-to account × NDC × date
* **Primary key:** `distributor_id, invoice_id, invoice_line`
* **Join keys:** `ship_to_dea` → /identifiers/provider/dea-number.md, `ship_to_hin` → /identifiers/provider/hin.md, `ndc11` → /identifiers/product/ndc.md, `contract_id` → /data-assets/finance/contracts-data.md
* **Refresh:** daily or weekly
* **Projection:** census for participating distributors
* **Measures:** sell-through units, gross $ at WAC or contract price
* **PHI status:** none (B2B; addresses are business data)

# Schema
Typical fields (vendor layouts differ; confirm against the data dictionary):

| Field | Meaning |
|---|---|
| `transfer_type` | sale / return / transfer |
| `ship_to name/address/DEA/HIN` | account |
| `ndc + qualifier` | product |
| `qty` | units |
| `unit_price / amount` | $ |
| `contract_id` | pricing contract |

# Typical uses
* Account-level sales for IC and targeting
* Chargeback validation
* Channel mix for GTN

# Pitfalls
* Same sale can appear in wholesaler and 3PL 867 — deduplicate by source
* Returns arrive as negative or separate lines
* Account matching via DEA/HIN is many-to-one; master to HCO before rolling up

# Vendors / sources
McKesson, Cencora, Cardinal Health, specialty distributors, aggregators: IntegriChain, Model N

# Relationships
* **derived_from** → [EDI 867 Product Transfer & Resale Report](/distribution-edi/edi-867.md)
* **provided_by** → [Full-Line Wholesaler](/actors/distribution/full-line-wholesaler.md)

[^edi-867]: [EDI 867 Product Transfer and Resale Report](https://www.partnerlinq.com/edi-transaction/edi-867-product-transfer-and-resale-report-x12)
