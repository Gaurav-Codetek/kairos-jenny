---
type: Data Flow
title: Product & Trade Data Flow
description: Manufacturer → 3PL → wholesaler / specialty distributor → pharmacy or provider, and the EDI each hop generates.
tags:
- supply-chain
- flow
generated:
  by: claude-opus-5.5/us-pharma-kb-builder
  at: '2026-10-02T00:00:00Z'
relations:
- predicate: generates_data
  target: /data-assets/sales-distribution/ex-factory-sales.md
- predicate: generates_data
  target: /data-assets/sales-distribution/edi-867-wholesaler.md
- predicate: generates_data
  target: /data-assets/sales-distribution/ics-867.md
- predicate: generates_data
  target: /data-assets/sales-distribution/iqvia-ddd.md
---
# Definition
Manufacturer → 3PL → wholesaler / specialty distributor → pharmacy or provider, and the EDI each hop generates.

1. Manufacturer ERP books ex-factory sales (850/855/856/810) to wholesalers; 3PL executes via 940/945.
2. Wholesalers/3PLs report resale to downstream accounts (867), inventory (852), and claim chargebacks (844 → 849).
3. Aggregators normalise feeds; IQVIA DDD projects outlet-level sales.
4. Dispensing then generates claims; contract prices become chargebacks or rebates.

# Relationships
* **generates_data** → [Ex-Factory Sales (Sell-In)](/data-assets/sales-distribution/ex-factory-sales.md)
* **generates_data** → [Wholesaler / Specialty Distributor 867 (Sell-Through)](/data-assets/sales-distribution/edi-867-wholesaler.md)
* **generates_data** → [ICS 867 (Cencora ICS 3PL Sales Feed)](/data-assets/sales-distribution/ics-867.md)
* **generates_data** → [IQVIA DDD (Outlet-Level Sales)](/data-assets/sales-distribution/iqvia-ddd.md)

