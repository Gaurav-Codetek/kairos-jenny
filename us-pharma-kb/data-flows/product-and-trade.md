---
type: Data Flow
title: Product, Trade & Chargeback Flow
description: Ex-factory → 3PL → wholesaler → account with 867/852/844 data and contract pricing.
tags:
- flow
generated:
  by: claude-opus-5.5/us-pharma-kb-builder
  at: '2026-10-02T00:00:00Z'
relations:
- predicate: related_to
  target: /distribution-edi/product-trade-flow.md
- predicate: generates_data
  target: /data-assets/finance/edi-844-849-chargebacks.md
---
# Definition
Ex-factory → 3PL → wholesaler → account with 867/852/844 data and contract pricing.

# Relationships
* **related_to** → [Product & Trade Data Flow](/distribution-edi/product-trade-flow.md)
* **generates_data** → [Chargeback Data (844/849)](/data-assets/finance/edi-844-849-chargebacks.md)

