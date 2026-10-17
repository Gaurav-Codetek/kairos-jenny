---
type: Dataset Type
title: IQVIA MIDAS
description: Global audited pharmaceutical sales across countries, used for global market sizing.
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
grain: country × product × month
primary_key:
- country
- product
- month
join_keys:
- product
refresh_cadence: monthly
projection: projected
measures: sales $ and units
phi_status: none
---
# Definition
Global audited pharmaceutical sales across countries, used for global market sizing.[^iqvia-data]

# Grain & keys
* **Grain:** country × product × month
* **Primary key:** `country, product, month`
* **Join keys:** `product` → /identifiers/product/atc.md
* **Refresh:** monthly
* **Projection:** projected
* **Measures:** sales $ and units
* **PHI status:** none

# Schema
Typical fields (vendor layouts differ; confirm against the data dictionary):

| Field | Meaning |
|---|---|
| `country` | market |
| `atc` | class |

# Typical uses
* Global forecasting

# Pitfalls
* US detail is coarser than NSP

# Vendors / sources
IQVIA

[^iqvia-data]: [IQVIA Institute: Available IQVIA Data](https://www.iqvia.com/insights/the-iqvia-institute/available-iqvia-data)
