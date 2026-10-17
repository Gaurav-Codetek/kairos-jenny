---
type: Identifier
title: De-identified Patient Token
description: Hashed identifier derived from PII (name, DOB, sex, zip) that links one patient across de-identified datasets without exposing identity.
tags:
- identifier
generated:
  by: claude-opus-5.5/us-pharma-kb-builder
  at: '2026-10-02T00:00:00Z'
sources:
- id: hhs-deid
  resource: https://www.hhs.gov/hipaa/for-professionals/privacy/special-topics/de-identification/index.html
  title: 'HHS: HIPAA de-identification guidance'
resource: https://www.hhs.gov/hipaa/for-professionals/privacy/special-topics/de-identification/index.html
identifier_format: vendor hash
issuer: Datavant / HealthVerity / vendor
relations:
- predicate: restricted_by
  target: /regulation/privacy/hipaa-deidentification.md
- predicate: identifies
  target: /data-model/entities/patient.md
---
# Definition
Hashed identifier derived from PII (name, DOB, sex, zip) that links one patient across de-identified datasets without exposing identity.[^hhs-deid]

Each source gets a site-specific token; linkage requires transforming to a common token under an expert determination. `PATIENT_ID` in LAAD/Komodo is such a pseudonymous ID.

# Relationships
* **restricted_by** → [HIPAA De-identification](/regulation/privacy/hipaa-deidentification.md)
* **identifies** → [Patient](/data-model/entities/patient.md)

[^hhs-deid]: [HHS: HIPAA de-identification guidance](https://www.hhs.gov/hipaa/for-professionals/privacy/special-topics/de-identification/index.html)
