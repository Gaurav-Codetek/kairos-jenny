---
type: Vendor
title: IQVIA
description: Largest provider of pharma data (Xponent, NPA, DDD, LAAD, OneKey), analytics, CRO and CSO services.
tags:
- vendor
generated:
  by: claude-opus-5.5/us-pharma-kb-builder
  at: '2026-10-02T00:00:00Z'
stale_after: '2027-04-01T00:00:00Z'
sources:
- id: iqvia-data
  resource: https://www.iqvia.com/insights/the-iqvia-institute/available-iqvia-data
  title: 'IQVIA Institute: Available IQVIA Data'
resource: https://www.iqvia.com/insights/the-iqvia-institute/available-iqvia-data
relations:
- predicate: provides
  target: /data-assets/rx-audit/iqvia-xponent.md
- predicate: provides
  target: /data-assets/patient-claims/iqvia-laad.md
- predicate: provides
  target: /data-assets/sales-distribution/iqvia-ddd.md
- predicate: is_a
  target: /service-providers/categories/commercial-data-provider.md
---
# Definition
Largest provider of pharma data (Xponent, NPA, DDD, LAAD, OneKey), analytics, CRO and CSO services.[^iqvia-data]

# Relationships
* **provides** → [IQVIA Xponent (Prescriber-Level Rx)](/data-assets/rx-audit/iqvia-xponent.md)
* **provides** → [IQVIA LAAD (Longitudinal Access & Adjudication Data)](/data-assets/patient-claims/iqvia-laad.md)
* **provides** → [IQVIA DDD (Outlet-Level Sales)](/data-assets/sales-distribution/iqvia-ddd.md)
* **is_a** → [Commercial Data Provider](/service-providers/categories/commercial-data-provider.md)

[^iqvia-data]: [IQVIA Institute: Available IQVIA Data](https://www.iqvia.com/insights/the-iqvia-institute/available-iqvia-data)
