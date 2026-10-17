---
type: Policy
title: Data Quality Rules
description: Standard normalisation and validation rules for pharma commercial data.
tags:
- data-quality
generated:
  by: claude-opus-5.5/us-pharma-kb-builder
  at: '2026-10-02T00:00:00Z'
relations:
- predicate: related_to
  target: /identifiers/product/ndc.md
- predicate: related_to
  target: /identifiers/provider/npi.md
---
# Definition
Standard normalisation and validation rules for pharma commercial data.

* **NDC:** strip dashes, left-pad the segment to HIPAA 11-digit 5-4-2; derive `ndc9` (first 9) for package-agnostic product.
* **NPI:** 10 digits with a Luhn check digit (prefix 80840); reject invalid NPIs.
* **Zip:** store as 5-char string with leading zeros (numeric storage drops leading zeros — cast to string and pad).
* **Pharmacy claims:** keep the last adjudicated version per (pharmacy, Rx#, fill#, date of service); drop reversed fills when counting dispensed Rx.
* **Medical claims:** collapse original/adjustment/void versions to the final claim; count at line level for drugs.
* **867:** net sales = sold − returned; check grain uniqueness on invoice + line + ship-to + source before aggregating.
* **Wide weekly files** (e.g. DDD with one column per week) must be unpivoted to long format before joins.

# Relationships
* **related_to** → [National Drug Code (NDC)](/identifiers/product/ndc.md)
* **related_to** → [National Provider Identifier (NPI)](/identifiers/provider/npi.md)

