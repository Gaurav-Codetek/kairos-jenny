---
type: Dataset Type
title: Speaker Program Data
description: Events, speakers, attendees and honoraria for promotional speaker programmes.
tags:
- dataset
- promotion
generated:
  by: claude-opus-5.5/us-pharma-kb-builder
  at: '2026-10-02T00:00:00Z'
dataset_category: promotion
grain: event × attendee
primary_key:
- event_id
- attendee_id
join_keys:
- npi
refresh_cadence: daily
projection: census
measures: events, attendance, spend
phi_status: HCP business data
relations:
- predicate: feeds
  target: /data-assets/promotion/open-payments.md
---
# Definition
Events, speakers, attendees and honoraria for promotional speaker programmes.

# Grain & keys
* **Grain:** event × attendee
* **Primary key:** `event_id, attendee_id`
* **Join keys:** `npi` → /identifiers/provider/npi.md
* **Refresh:** daily
* **Projection:** census
* **Measures:** events, attendance, spend
* **PHI status:** HCP business data

# Schema
Typical fields (vendor layouts differ; confirm against the data dictionary):

| Field | Meaning |
|---|---|
| `honorarium` | spend |

# Typical uses
* Compliance monitoring
* Open Payments reporting

# Pitfalls
* OIG 2020 Special Fraud Alert scrutiny

# Vendors / sources
speaker bureau vendors

# Relationships
* **feeds** → [CMS Open Payments](/data-assets/promotion/open-payments.md)

