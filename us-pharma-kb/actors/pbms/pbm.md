---
type: Actor Class
title: Pharmacy Benefit Manager (PBM)
description: Adjudicates pharmacy claims, builds formularies, contracts pharmacy networks and negotiates manufacturer rebates for plan sponsors.
tags:
- pbm
generated:
  by: claude-opus-5.5/us-pharma-kb-builder
  at: '2026-10-02T00:00:00Z'
sources:
- id: pbm-share
  resource: https://americanpharmacynews.com/analysis-three-pbms-account-for-80-of-u-s-market-share
  title: Three PBMs account for 80% of claims (2026)
resource: https://americanpharmacynews.com/analysis-three-pbms-account-for-80-of-u-s-market-share
relations:
- predicate: adjudicated_by
  target: /claims/pharmacy/pharmacy-claim-flow.md
- predicate: contracts_with
  target: /actors/manufacturers/brand-manufacturer.md
- predicate: identified_by
  target: /identifiers/payer/bin-pcn-group.md
---
# Definition
Adjudicates pharmacy claims, builds formularies, contracts pharmacy networks and negotiates manufacturer rebates for plan sponsors.[^pbm-share]

Three PBMs (Express Scripts 31%, CVS Caremark 26%, Optum Rx 23%) processed about 80% of 2025 equivalent prescription claims.

# Relationships
* **adjudicated_by** → [Pharmacy Claim Flow](/claims/pharmacy/pharmacy-claim-flow.md)
* **contracts_with** → [Brand Manufacturer](/actors/manufacturers/brand-manufacturer.md)
* **identified_by** → [BIN / PCN / Group](/identifiers/payer/bin-pcn-group.md)

[^pbm-share]: [Three PBMs account for 80% of claims (2026)](https://americanpharmacynews.com/analysis-three-pbms-account-for-80-of-u-s-market-share)
