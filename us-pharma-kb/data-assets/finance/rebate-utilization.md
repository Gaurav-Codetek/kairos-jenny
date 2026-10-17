---
type: Dataset Type
title: Rebate Utilisation Invoices
description: PBM/plan invoices listing claim-level or aggregated utilisation subject to rebates.
tags:
- dataset
- finance
generated:
  by: claude-opus-5.5/us-pharma-kb-builder
  at: '2026-10-02T00:00:00Z'
dataset_category: finance
grain: plan × NDC × quarter
primary_key:
- invoice_id
- ndc
- quarter
join_keys:
- plan
- ndc
refresh_cadence: quarterly
projection: census
measures: rebate $
phi_status: de-identified
relations:
- predicate: measures
  target: /pricing-gtn/commercial-rebate.md
---
# Definition
PBM/plan invoices listing claim-level or aggregated utilisation subject to rebates.

# Grain & keys
* **Grain:** plan × NDC × quarter
* **Primary key:** `invoice_id, ndc, quarter`
* **Join keys:** `plan` → /identifiers/payer/plan-id.md, `ndc` → /identifiers/product/ndc.md
* **Refresh:** quarterly
* **Projection:** census
* **Measures:** rebate $
* **PHI status:** de-identified

# Schema
Typical fields (vendor layouts differ; confirm against the data dictionary):

| Field | Meaning |
|---|---|
| `units, rebate_rate` | $ |

# Typical uses
* Rebate validation vs LAAD/claims

# Pitfalls
* Duplicate-discount checks against 340B and Medicaid

# Vendors / sources
PBMs, rebate GPOs

# Relationships
* **measures** → [Commercial / PBM Rebate](/pricing-gtn/commercial-rebate.md)

