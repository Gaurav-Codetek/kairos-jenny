---
type: Entity
title: Shipment / Sale Line
description: 867 or ex-factory line.
tags:
- data-model
generated:
  by: claude-opus-5.5/us-pharma-kb-builder
  at: '2026-10-02T00:00:00Z'
relations:
- predicate: ships_to
  target: /data-model/entities/hco.md
---
# Definition
867 or ex-factory line.

# Identifiers
INVOICE_ID + INVOICE_ITEM + source + ship-to

# Relationships
* **ships_to** → [HCO](/data-model/entities/hco.md)

