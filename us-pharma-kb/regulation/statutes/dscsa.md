---
type: Law
title: Drug Supply Chain Security Act
description: 2013 law requiring package-level serialisation and interoperable electronic tracing between trading partners.
tags:
- law
generated:
  by: claude-opus-5.5/us-pharma-kb-builder
  at: '2026-10-02T00:00:00Z'
stale_after: '2026-11-27T00:00:00Z'
sources:
- id: dscsa-exempt
  resource: https://nabp.pharmacy/news/blog/fdas-dscsa-exemption-for-connected-trading-partners/
  title: 'NABP: DSCSA exemptions'
resource: https://nabp.pharmacy/news/blog/fdas-dscsa-exemption-for-connected-trading-partners/
citation: FD&C Act §581-585
enforced_by: /actors/regulators/fda.md
relations:
- predicate: enforced_by
  target: /actors/regulators/fda.md
- predicate: related_to
  target: /distribution-edi/epcis-dscsa.md
---
# Definition
2013 law requiring package-level serialisation and interoperable electronic tracing between trading partners.[^dscsa-exempt]

Enhanced requirements now apply to manufacturers, wholesalers and large dispensers; small dispensers (≤25 FTE pharmacists/techs) are exempt until **27 Nov 2026**. Transaction information travels as EPCIS events alongside EDI 856.

# Relationships
* **enforced_by** → [FDA](/actors/regulators/fda.md)
* **related_to** → [EPCIS / DSCSA Traceability](/distribution-edi/epcis-dscsa.md)

[^dscsa-exempt]: [NABP: DSCSA exemptions](https://nabp.pharmacy/news/blog/fdas-dscsa-exemption-for-connected-trading-partners/)
