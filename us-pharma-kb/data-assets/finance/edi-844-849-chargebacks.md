---
type: Dataset Type
title: Chargeback Data (844/849)
description: Wholesaler chargeback claims and manufacturer responses per resale line.
tags:
- dataset
- finance
generated:
  by: claude-opus-5.5/us-pharma-kb-builder
  at: '2026-10-02T00:00:00Z'
sources:
- id: edi-844
  resource: https://relasoft.net/edi-844-chargeback-what-is-it/
  title: EDI 844 chargebacks explained
- id: cencora-ics-data
  resource: https://www.cencora.com/resources/human-health/connecting-the-data-dots
  title: 'Cencora/ICS: Connecting the data dots'
resource: https://relasoft.net/edi-844-chargeback-what-is-it/
dataset_category: finance
grain: chargeback line × contract
primary_key:
- cb_id
- line
join_keys:
- contract_id
- ship_to
- ndc
refresh_cadence: daily
projection: census
measures: chargeback $
phi_status: none
relations:
- predicate: derived_from
  target: /distribution-edi/edi-844-849.md
- predicate: measures
  target: /pricing-gtn/chargeback.md
---
# Definition
Wholesaler chargeback claims and manufacturer responses per resale line.[^edi-844][^cencora-ics-data]

# Grain & keys
* **Grain:** chargeback line × contract
* **Primary key:** `cb_id, line`
* **Join keys:** `contract_id` → /data-assets/finance/contracts-data.md, `ship_to` → /identifiers/provider/hin.md, `ndc` → /identifiers/product/ndc.md
* **Refresh:** daily
* **Projection:** census
* **Measures:** chargeback $
* **PHI status:** none

# Schema
Typical fields (vendor layouts differ; confirm against the data dictionary):

| Field | Meaning |
|---|---|
| `wac, contract_price, chargeback_amount` | $ |

# Typical uses
* Accruals, contract compliance

# Pitfalls
* Match to 867 lines to detect duplicates/invalid claims

# Vendors / sources
wholesalers via EDI

# Relationships
* **derived_from** → [EDI 844 / 849 Chargeback Claim & Response](/distribution-edi/edi-844-849.md)
* **measures** → [Chargeback](/pricing-gtn/chargeback.md)

[^edi-844]: [EDI 844 chargebacks explained](https://relasoft.net/edi-844-chargeback-what-is-it/)
[^cencora-ics-data]: [Cencora/ICS: Connecting the data dots](https://www.cencora.com/resources/human-health/connecting-the-data-dots)
