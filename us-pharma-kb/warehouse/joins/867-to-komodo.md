---
type: Join Path
title: 867 Sales ↔ Komodo Claims (IV drugs)
description: 'Join at HCO/system level: fct_ics_867.ORG_VID/SYS_VID = AFFILIATED_ORG_VID/AFFILIATED_SYSTEM_VID (cast DOUBLE VIDs to string first) to compare purchases vs administrations.'
tags:
- join
generated:
  by: claude-opus-5.5/us-pharma-kb-builder
  at: '2026-10-02T00:00:00Z'
relations:
- predicate: joins_to
  target: /data-assets/sales-distribution/ics-867.md
- predicate: joins_to
  target: /data-assets/provider-aggregates/komodo-claims-by-provider.md
---
# Definition
Join at HCO/system level: fct_ics_867.ORG_VID/SYS_VID = AFFILIATED_ORG_VID/AFFILIATED_SYSTEM_VID (cast DOUBLE VIDs to string first) to compare purchases vs administrations.

# Relationships
* **joins_to** → [ICS 867 (Cencora ICS 3PL Sales Feed)](/data-assets/sales-distribution/ics-867.md)
* **joins_to** → [Komodo Claims by Provider (HCP × Affiliation Aggregate)](/data-assets/provider-aggregates/komodo-claims-by-provider.md)

