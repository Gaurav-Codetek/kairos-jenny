---
type: Dataset Type
title: Ex-Factory Sales (Sell-In)
description: Manufacturer's own invoices to wholesalers/3PL customers — the revenue record before any downstream resale.
tags:
- dataset
- sales-distribution
generated:
  by: claude-opus-5.5/us-pharma-kb-builder
  at: '2026-10-02T00:00:00Z'
dataset_category: sales-distribution
grain: order/invoice line × customer DC × NDC × date
primary_key:
- invoice_id
- invoice_line
join_keys:
- ndc11
- customer_dc
refresh_cadence: daily
projection: census
measures: shipments (sell-in) units and gross $
phi_status: none (B2B)
relations:
- predicate: derived_from
  target: /distribution-edi/edi-810.md
- predicate: related_to
  target: /data-assets/sales-distribution/edi-852-inventory.md
---
# Definition
Manufacturer's own invoices to wholesalers/3PL customers — the revenue record before any downstream resale.

# Grain & keys
* **Grain:** order/invoice line × customer DC × NDC × date
* **Primary key:** `invoice_id, invoice_line`
* **Join keys:** `ndc11` → /identifiers/product/ndc.md, `customer_dc` → wholesaler DC master
* **Refresh:** daily
* **Projection:** census
* **Measures:** shipments (sell-in) units and gross $
* **PHI status:** none (B2B)

# Schema
Typical fields (vendor layouts differ; confirm against the data dictionary):

| Field | Meaning |
|---|---|
| `invoice_date` | date of sale |
| `sold_to / ship_to` | wholesaler DC |
| `ndc` | package |
| `qty` | units/packs |
| `wac_amount` | gross $ |

# Typical uses
* Revenue recognition and inventory-in-channel (sell-in minus sell-through)
* Forecast reconciliation

# Pitfalls
* Wholesaler buying patterns (end of quarter) distort demand
* Not account-level — use 867 for downstream customers

# Vendors / sources
manufacturer ERP (SAP/Oracle), 3PL order-to-cash

# Relationships
* **derived_from** → [EDI 810 Invoice](/distribution-edi/edi-810.md)
* **related_to** → [852 Inventory / Product Activity](/data-assets/sales-distribution/edi-852-inventory.md)

