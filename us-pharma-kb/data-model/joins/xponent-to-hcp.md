---
type: Join Path
title: Xponent → HCP → Territory
description: Map IMS_PRESCRIBER_ID/NPI_ID to the master HCP, then HCP zip → ZTT territory.
tags:
- join
generated:
  by: claude-opus-5.5/us-pharma-kb-builder
  at: '2026-10-02T00:00:00Z'
relations:
- predicate: joins_to
  target: /data-assets/rx-audit/iqvia-xponent.md
- predicate: joins_to
  target: /data-model/entities/hcp.md
- predicate: joins_to
  target: /data-assets/reference/zip-to-territory.md
---
# Definition
Map IMS_PRESCRIBER_ID/NPI_ID to the master HCP, then HCP zip → ZTT territory.

# Relationships
* **joins_to** → [IQVIA Xponent (Prescriber-Level Rx)](/data-assets/rx-audit/iqvia-xponent.md)
* **joins_to** → [HCP](/data-model/entities/hcp.md)
* **joins_to** → [Zip-to-Territory (ZTT) Alignment](/data-assets/reference/zip-to-territory.md)

