---
type: Data Flow
title: Medical Claim Flow
description: Provider → 837P/837I → clearinghouse → payer adjudication → 835 remittance; 270/271 eligibility, 276/277 status, 278 PA.
tags:
- claims
- medical
generated:
  by: claude-opus-5.5/us-pharma-kb-builder
  at: '2026-10-02T00:00:00Z'
relations:
- predicate: uses_standard
  target: /claims/medical/x12-837p.md
- predicate: uses_standard
  target: /claims/medical/x12-837i.md
- predicate: uses_standard
  target: /claims/medical/x12-835.md
- predicate: generates_data
  target: /data-assets/patient-claims/medical-claims-open.md
---
# Definition
Provider → 837P/837I → clearinghouse → payer adjudication → 835 remittance; 270/271 eligibility, 276/277 status, 278 PA.

# Relationships
* **uses_standard** → [X12 837P (Professional)](/claims/medical/x12-837p.md)
* **uses_standard** → [X12 837I (Institutional)](/claims/medical/x12-837i.md)
* **uses_standard** → [X12 835 Remittance](/claims/medical/x12-835.md)
* **generates_data** → [Open Medical (Mx/Dx) Claims](/data-assets/patient-claims/medical-claims-open.md)

