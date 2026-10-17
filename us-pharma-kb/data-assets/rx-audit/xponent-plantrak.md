---
type: Dataset Type
title: IQVIA Xponent PlanTrak
description: Prescriber-level Rx split by payer plan to measure access and pull-through.
tags:
- dataset
- rx-audit
generated:
  by: claude-opus-5.5/us-pharma-kb-builder
  at: '2026-10-02T00:00:00Z'
dataset_category: rx-audit
grain: prescriber × product × plan × week
primary_key:
- prescriber_id
- product
- plan_id
- week
join_keys:
- plan_id
refresh_cadence: weekly
projection: sample-projected
measures: TRx/NRx by plan
phi_status: prescriber-identifiable
relations:
- predicate: is_a
  target: /data-assets/rx-audit/iqvia-xponent.md
---
# Definition
Prescriber-level Rx split by payer plan to measure access and pull-through.

# Grain & keys
* **Grain:** prescriber × product × plan × week
* **Primary key:** `prescriber_id, product, plan_id, week`
* **Join keys:** `plan_id` → /identifiers/payer/plan-id.md
* **Refresh:** weekly
* **Projection:** sample-projected
* **Measures:** TRx/NRx by plan
* **PHI status:** prescriber-identifiable

# Schema
Typical fields (vendor layouts differ; confirm against the data dictionary):

| Field | Meaning |
|---|---|
| `plan_id` | payer plan |
| `model_type` | commercial/Part D/Medicaid |

# Typical uses
* Payer pull-through
* Formulary win impact

# Pitfalls
* Plan mapping changes over time

# Vendors / sources
IQVIA

# Relationships
* **is_a** → [IQVIA Xponent (Prescriber-Level Rx)](/data-assets/rx-audit/iqvia-xponent.md)

