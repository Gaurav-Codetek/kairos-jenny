---
type: Dataset Type
title: Copay Program Data
description: Claims paid by the manufacturer copay programme via its BIN/PCN.
tags:
- dataset
- access
generated:
  by: claude-opus-5.5/us-pharma-kb-builder
  at: '2026-10-02T00:00:00Z'
dataset_category: access
grain: claim × card
primary_key:
- claim_id
join_keys:
- bin_pcn
- ndc
refresh_cadence: weekly
projection: census
measures: redemptions, $ paid
phi_status: de-identified
relations:
- predicate: related_to
  target: /claims/pharmacy/copay-card-claim.md
---
# Definition
Claims paid by the manufacturer copay programme via its BIN/PCN.

# Grain & keys
* **Grain:** claim × card
* **Primary key:** `claim_id`
* **Join keys:** `bin_pcn` → /identifiers/payer/bin-pcn-group.md, `ndc` → /identifiers/product/ndc.md
* **Refresh:** weekly
* **Projection:** census
* **Measures:** redemptions, $ paid
* **PHI status:** de-identified

# Schema
Typical fields (vendor layouts differ; confirm against the data dictionary):

| Field | Meaning |
|---|---|
| `benefit_amount` | $ |

# Typical uses
* Copay spend & accumulator detection

# Pitfalls
* Commercial only

# Vendors / sources
ConnectiveRx, TrialCard (Mercalis), PSKW

# Relationships
* **related_to** → [Copay Card Secondary Claim](/claims/pharmacy/copay-card-claim.md)

