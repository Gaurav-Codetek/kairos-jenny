---
type: Dataset Type
title: Hub / Patient Services Data
description: 'Case records from manufacturer hubs: enrolments, benefit verification, PA support, financial assistance, SP triage.'
tags:
- dataset
- access
generated:
  by: claude-opus-5.5/us-pharma-kb-builder
  at: '2026-10-02T00:00:00Z'
dataset_category: access
grain: patient case × status event
primary_key:
- case_id
- event_ts
join_keys:
- hub_patient_id
- npi
refresh_cadence: daily
projection: census for enrolled patients
measures: time-to-therapy, case outcomes
phi_status: identifiable PHI with patient consent
relations:
- predicate: related_to
  target: /market-access/hub-services.md
---
# Definition
Case records from manufacturer hubs: enrolments, benefit verification, PA support, financial assistance, SP triage.

# Grain & keys
* **Grain:** patient case × status event
* **Primary key:** `case_id, event_ts`
* **Join keys:** `hub_patient_id` → /identifiers/patient/patient-token.md, `npi` → /identifiers/provider/npi.md
* **Refresh:** daily
* **Projection:** census for enrolled patients
* **Measures:** time-to-therapy, case outcomes
* **PHI status:** identifiable PHI with patient consent

# Schema
Typical fields (vendor layouts differ; confirm against the data dictionary):

| Field | Meaning |
|---|---|
| `case_status, status_reason` | funnel |
| `bv_result, pa_outcome` | access |

# Typical uses
* Time to therapy
* Hub funnel

# Pitfalls
* PHI — firewall from sales

# Vendors / sources
EVERSANA, AssistRx, Lash Group, CareMetx

# Relationships
* **related_to** → [Hub Services](/market-access/hub-services.md)

