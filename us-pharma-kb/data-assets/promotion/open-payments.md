---
type: Dataset Type
title: CMS Open Payments
description: Public record of manufacturer and GPO transfers of value to physicians, NPPs and teaching hospitals.
tags:
- dataset
- promotion
generated:
  by: claude-opus-5.5/us-pharma-kb-builder
  at: '2026-10-02T00:00:00Z'
sources:
- id: cms-open-payments
  resource: https://www.cms.gov/priorities/key-initiatives/open-payments/data
  title: CMS Open Payments data
resource: https://www.cms.gov/priorities/key-initiatives/open-payments/data
dataset_category: promotion
grain: payment record × recipient
primary_key:
- record_id
join_keys:
- npi
refresh_cadence: annual (June) + January refresh
projection: census
measures: payment $ by nature
phi_status: public
relations:
- predicate: established_by
  target: /regulation/fraud-abuse/sunshine-act.md
---
# Definition
Public record of manufacturer and GPO transfers of value to physicians, NPPs and teaching hospitals.[^cms-open-payments]

# Grain & keys
* **Grain:** payment record × recipient
* **Primary key:** `record_id`
* **Join keys:** `npi` → /identifiers/provider/npi.md
* **Refresh:** annual (June) + January refresh
* **Projection:** census
* **Measures:** payment $ by nature
* **PHI status:** public

# Schema
Typical fields (vendor layouts differ; confirm against the data dictionary):

| Field | Meaning |
|---|---|
| `nature_of_payment` | category |
| `amount` | $ |

# Typical uses
* Competitive intelligence on KOL engagement

# Pitfalls
* Published with ~18-month lag

# Vendors / sources
CMS

# Relationships
* **established_by** → [Physician Payments Sunshine Act (Open Payments)](/regulation/fraud-abuse/sunshine-act.md)

[^cms-open-payments]: [CMS Open Payments data](https://www.cms.gov/priorities/key-initiatives/open-payments/data)
