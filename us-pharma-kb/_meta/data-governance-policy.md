---
type: Policy
title: Data Governance & Licensing Rules for Agents
description: 'Rules an agent must follow when combining US pharma commercial datasets: PHI, licences, AMA PDRP, projection.'
tags:
- governance
- phi
- licensing
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
  target: /regulation/privacy/hipaa-deidentification.md
- predicate: related_to
  target: /regulation/state-law/ama-pdrp.md
---
# Definition
Rules an agent must follow when combining US pharma commercial datasets: PHI, licences, AMA PDRP, projection.[^hhs-deid]

* **Never re-identify.** Patient-level data (claims, APLD, hub/SP feeds) is de-identified under HIPAA expert determination; linking to new sources needs a fresh determination.
* **Respect licence scope.** Vendor licences (IQVIA, Komodo, Symphony) restrict use by brand, market basket and purpose; check before joining datasets from two vendors.
* **AMA PDRP.** Prescribers who opted out must not have prescriber-level data shown to reps (see `PROVIDER_PDRP_OPT_OUT_FLAG`).
* **Do not add across measure families.** Projected TRx, shipped units (867/DDD) and adjudicated claims count different things.
* **Small-cell suppression.** Do not publish counts under 11 patients from claims data.
* **Off-label/OPDP.** AI-generated promotional content must stay on-label and go through MLR review.

# Relationships
* **related_to** → [HIPAA De-identification](/regulation/privacy/hipaa-deidentification.md)
* **related_to** → [AMA Physician Data Restriction Program](/regulation/state-law/ama-pdrp.md)

[^hhs-deid]: [HHS: HIPAA de-identification guidance](https://www.hhs.gov/hipaa/for-professionals/privacy/special-topics/de-identification/index.html)
