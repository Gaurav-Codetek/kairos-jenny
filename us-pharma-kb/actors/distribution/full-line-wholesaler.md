---
type: Actor Class
title: Full-Line Wholesaler
description: Buys from manufacturers at WAC and supplies pharmacies, hospitals and clinics; the Big Three are McKesson, Cencora and Cardinal Health.
tags:
- distribution
- wholesaler
generated:
  by: claude-opus-5.5/us-pharma-kb-builder
  at: '2026-10-02T00:00:00Z'
relations:
- predicate: generates_data
  target: /data-assets/sales-distribution/edi-867-wholesaler.md
- predicate: generates_data
  target: /data-assets/sales-distribution/edi-852-inventory.md
- predicate: generates_data
  target: /data-assets/finance/edi-844-849-chargebacks.md
---
# Definition
Buys from manufacturers at WAC and supplies pharmacies, hospitals and clinics; the Big Three are McKesson, Cencora and Cardinal Health.

# Relationships
* **generates_data** → [Wholesaler / Specialty Distributor 867 (Sell-Through)](/data-assets/sales-distribution/edi-867-wholesaler.md)
* **generates_data** → [852 Inventory / Product Activity](/data-assets/sales-distribution/edi-852-inventory.md)
* **generates_data** → [Chargeback Data (844/849)](/data-assets/finance/edi-844-849-chargebacks.md)

