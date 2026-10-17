---
type: Guide
title: Which Dataset Answers Which Question
description: Question-to-dataset routing guide for analysts and agents.
tags:
- dataset
- guide
generated:
  by: claude-opus-5.5/us-pharma-kb-builder
  at: '2026-10-02T00:00:00Z'
relations:
- predicate: related_to
  target: /data-assets/dataset-taxonomy.md
---
# Definition
Question-to-dataset routing guide for analysts and agents.

| Question | Primary dataset | Secondary |
|---|---|---|
| How much did we ship / sell to each account? | 3PL or wholesaler 867 (e.g. ICS 867) | ex-factory, DDD |
| Account-level sales for a physician-administered / IV drug | 867 + DDD (outlet) | Komodo/LAAD medical claims |
| Prescriber-level Rx and market share | Xponent | LAAD (unprojected) |
| National weekly brand trend | NPA | SNR / ex-factory |
| New-to-brand, switching, persistence, line of therapy | LAAD / Komodo patient claims | Symphony IDV |
| Why are claims rejected / abandoned? | LAAD / FIA lifecycle | hub data, ePA |
| Which HCPs treat the patients, incl. procedures? | Komodo or LAAD medical (Mx) claims | CMS Part B PUF |
| Payer coverage & PA policy | MMIT / formulary data | Komodo Patient Insurance |
| Rep activity and its effect | Veeva CRM calls + Xponent/867 | Open Payments |
| Chargeback & contract compliance | 844/849 chargebacks + 867 | contracts data |
| Gross-to-net accruals | contracts, chargebacks, rebate invoices, Medicaid invoices | 867 channel mix |

# Relationships
* **related_to** → [Dataset Type Taxonomy](/data-assets/dataset-taxonomy.md)

