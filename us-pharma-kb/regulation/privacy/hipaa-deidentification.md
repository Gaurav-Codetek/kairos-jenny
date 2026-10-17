---
type: Regulation
title: HIPAA De-identification
description: PHI is de-identified by Safe Harbor (remove 18 identifiers) or Expert Determination (very small re-identification risk); the basis for tokenised claims data.
tags:
- privacy
- phi
generated:
  by: claude-opus-5.5/us-pharma-kb-builder
  at: '2026-10-02T00:00:00Z'
sources:
- id: hhs-deid
  resource: https://www.hhs.gov/hipaa/for-professionals/privacy/special-topics/de-identification/index.html
  title: 'HHS: HIPAA de-identification guidance'
resource: https://www.hhs.gov/hipaa/for-professionals/privacy/special-topics/de-identification/index.html
relations:
- predicate: related_to
  target: /identifiers/patient/patient-token.md
---
# Definition
PHI is de-identified by Safe Harbor (remove 18 identifiers) or Expert Determination (very small re-identification risk); the basis for tokenised claims data.[^hhs-deid]

# Relationships
* **related_to** → [De-identified Patient Token](/identifiers/patient/patient-token.md)

[^hhs-deid]: [HHS: HIPAA de-identification guidance](https://www.hhs.gov/hipaa/for-professionals/privacy/special-topics/de-identification/index.html)
