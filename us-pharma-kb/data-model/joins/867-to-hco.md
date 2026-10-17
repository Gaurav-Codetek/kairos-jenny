---
type: Join Path
title: 867 → HCO → System
description: Ship-to DEA/HIN/custom key → Veeva custom-key crosswalk → ORG_VID → SYS_VID; then account/zip alignment.
tags:
- join
generated:
  by: claude-opus-5.5/us-pharma-kb-builder
  at: '2026-10-02T00:00:00Z'
relations:
- predicate: joins_to
  target: /data-assets/sales-distribution/ics-867.md
- predicate: joins_to
  target: /data-assets/reference/veeva-opendata.md
- predicate: joins_to
  target: /data-assets/reference/account-alignment.md
---
# Definition
Ship-to DEA/HIN/custom key → Veeva custom-key crosswalk → ORG_VID → SYS_VID; then account/zip alignment.

# Relationships
* **joins_to** → [ICS 867 (Cencora ICS 3PL Sales Feed)](/data-assets/sales-distribution/ics-867.md)
* **joins_to** → [Veeva OpenData / Network](/data-assets/reference/veeva-opendata.md)
* **joins_to** → [Account / Network Alignment](/data-assets/reference/account-alignment.md)

