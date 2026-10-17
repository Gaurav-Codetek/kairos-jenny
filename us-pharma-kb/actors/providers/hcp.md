---
type: Actor Class
title: Healthcare Professional (HCP)
description: Individual prescriber or clinician (physician, NP, PA, etc.).
tags:
- provider
generated:
  by: claude-opus-5.5/us-pharma-kb-builder
  at: '2026-10-02T00:00:00Z'
relations:
- predicate: identified_by
  target: /identifiers/provider/npi.md
- predicate: prescribes
  target: /prescriptions/prescription.md
- predicate: implements
  target: /data-model/entities/hcp.md
---
# Definition
Individual prescriber or clinician (physician, NP, PA, etc.).

# Relationships
* **identified_by** → [National Provider Identifier (NPI)](/identifiers/provider/npi.md)
* **prescribes** → [Prescription](/prescriptions/prescription.md)
* **implements** → [HCP](/data-model/entities/hcp.md)

