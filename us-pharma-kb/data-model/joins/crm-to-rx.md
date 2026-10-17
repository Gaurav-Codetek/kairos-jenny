---
type: Join Path
title: CRM Calls → Rx / Claims Volume
description: HCP_VID (or NPI_VOD) joins calls to Xponent and Komodo-by-provider; analyse with a lagged response window.
tags:
- join
generated:
  by: claude-opus-5.5/us-pharma-kb-builder
  at: '2026-10-02T00:00:00Z'
relations:
- predicate: joins_to
  target: /data-assets/promotion/crm-calls.md
- predicate: joins_to
  target: /data-assets/provider-aggregates/komodo-claims-by-provider.md
---
# Definition
HCP_VID (or NPI_VOD) joins calls to Xponent and Komodo-by-provider; analyse with a lagged response window.

# Relationships
* **joins_to** → [CRM Call Activity (Veeva)](/data-assets/promotion/crm-calls.md)
* **joins_to** → [Komodo Claims by Provider (HCP × Affiliation Aggregate)](/data-assets/provider-aggregates/komodo-claims-by-provider.md)

