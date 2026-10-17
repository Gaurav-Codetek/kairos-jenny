---
type: Dataset Type
title: IQVIA NPA (National Prescription Audit)
description: Projected national dispensed prescriptions (TRx/NRx) by product and channel.
tags:
- dataset
- rx-audit
generated:
  by: claude-opus-5.5/us-pharma-kb-builder
  at: '2026-10-02T00:00:00Z'
sources:
- id: iqvia-data
  resource: https://www.iqvia.com/insights/the-iqvia-institute/available-iqvia-data
  title: 'IQVIA Institute: Available IQVIA Data'
resource: https://www.iqvia.com/insights/the-iqvia-institute/available-iqvia-data
dataset_category: rx-audit
grain: product × channel × week/month
primary_key:
- product
- channel
- week
join_keys:
- product
refresh_cadence: weekly
projection: sample-projected (~93% retail coverage)
measures: TRx, NRx, units
phi_status: none
relations:
- predicate: measures
  target: /prescriptions/metrics/trx.md
---
# Definition
Projected national dispensed prescriptions (TRx/NRx) by product and channel.[^iqvia-data]

# Grain & keys
* **Grain:** product × channel × week/month
* **Primary key:** `product, channel, week`
* **Join keys:** `product` → /identifiers/product/cmf.md
* **Refresh:** weekly
* **Projection:** sample-projected (~93% retail coverage)
* **Measures:** TRx, NRx, units
* **PHI status:** none

# Schema
Typical fields (vendor layouts differ; confirm against the data dictionary):

| Field | Meaning |
|---|---|
| `trx, nrx` | Rx counts |
| `units` | extended units |
| `channel` | retail/mail/LTC |

# Typical uses
* National brand trends
* Market share

# Pitfalls
* Projected; excludes most physician-administered drugs

# Vendors / sources
IQVIA

# Relationships
* **measures** → [TRx (Total Prescriptions)](/prescriptions/metrics/trx.md)

[^iqvia-data]: [IQVIA Institute: Available IQVIA Data](https://www.iqvia.com/insights/the-iqvia-institute/available-iqvia-data)
