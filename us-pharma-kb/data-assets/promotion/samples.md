---
type: Dataset Type
title: Sample Transactions
description: PDMA-regulated sample disbursements with lot numbers and signatures.
tags:
- dataset
- promotion
generated:
  by: claude-opus-5.5/us-pharma-kb-builder
  at: '2026-10-02T00:00:00Z'
dataset_category: promotion
grain: transaction × lot × HCP
primary_key:
- sample_txn_id
- lot
join_keys:
- hcp
- ndc
refresh_cadence: daily
projection: census
measures: units sampled
phi_status: HCP business data
relations:
- predicate: regulated_by
  target: /regulation/statutes/pdma.md
---
# Definition
PDMA-regulated sample disbursements with lot numbers and signatures.

# Grain & keys
* **Grain:** transaction × lot × HCP
* **Primary key:** `sample_txn_id, lot`
* **Join keys:** `hcp` → /data-model/entities/hcp.md, `ndc` → /identifiers/product/ndc.md
* **Refresh:** daily
* **Projection:** census
* **Measures:** units sampled
* **PHI status:** HCP business data

# Schema
Typical fields (vendor layouts differ; confirm against the data dictionary):

| Field | Meaning |
|---|---|
| `lot_number, quantity, signature` | accountability |

# Typical uses
* Sample reconciliation
* Sampling ROI

# Pitfalls
* Must reconcile to inventory

# Vendors / sources
CRM

# Relationships
* **regulated_by** → [Prescription Drug Marketing Act](/regulation/statutes/pdma.md)

