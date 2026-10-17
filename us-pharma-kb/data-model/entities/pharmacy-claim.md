---
type: Entity
title: Pharmacy Claim
description: NCPDP transaction / final fill.
tags:
- data-model
generated:
  by: claude-opus-5.5/us-pharma-kb-builder
  at: '2026-10-02T00:00:00Z'
relations:
- predicate: adjudicated_by
  target: /data-model/entities/pbm.md
- predicate: identified_by
  target: /identifiers/payer/bin-pcn-group.md
---
# Definition
NCPDP transaction / final fill.

# Identifiers
pharmacy + Rx# + fill# + DOS; CLAIM_ID

# Relationships
* **adjudicated_by** → [PBM](/data-model/entities/pbm.md)
* **identified_by** → [BIN / PCN / Group](/identifiers/payer/bin-pcn-group.md)

