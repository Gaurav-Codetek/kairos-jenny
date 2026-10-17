---
type: Data Flow
title: Physician-Administered (IV) Drug Flow
description: Manufacturer → 3PL/specialty distributor → clinic/hospital (867) → administration → 837 medical claim (J-code) → Komodo/LAAD Mx claims.
tags:
- flow
- specialty
generated:
  by: claude-opus-5.5/us-pharma-kb-builder
  at: '2026-10-02T00:00:00Z'
relations:
- predicate: generates_data
  target: /data-assets/sales-distribution/ics-867.md
- predicate: generates_data
  target: /data-assets/patient-claims/komodo-claims.md
- predicate: related_to
  target: /claims/medical/buy-and-bill.md
---
# Definition
Manufacturer → 3PL/specialty distributor → clinic/hospital (867) → administration → 837 medical claim (J-code) → Komodo/LAAD Mx claims.

For infused products (e.g. IV iron) the sales signal (3PL 867 to the infusion site) and the demand signal (medical claims at the administering HCP/HCO) live in different datasets. Link them at the **HCO/system** level via master IDs: the mastered organisation/system ID on the 867 ship-to ↔ the claims provider's affiliated organisation/system ID (cast numeric IDs to strings first).

# Relationships
* **generates_data** → [ICS 867 (Cencora ICS 3PL Sales Feed)](/data-assets/sales-distribution/ics-867.md)
* **generates_data** → [Komodo Claims Extracts (Mx / Rx)](/data-assets/patient-claims/komodo-claims.md)
* **related_to** → [Buy-and-Bill](/claims/medical/buy-and-bill.md)

