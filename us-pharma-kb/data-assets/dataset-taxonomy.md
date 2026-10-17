---
type: Taxonomy
title: Dataset Type Taxonomy
description: 'How US pharma commercial datasets are classified: what they measure, at what grain, and whether they are projected or census.'
tags:
- dataset
- taxonomy
generated:
  by: claude-opus-5.5/us-pharma-kb-builder
  at: '2026-10-02T00:00:00Z'
relations:
- predicate: defines
  target: /data-assets/dataset-selection-guide.md
---
# Definition
How US pharma commercial datasets are classified: what they measure, at what grain, and whether they are projected or census.

| Family | Measures | Typical grain | Projected? | Examples |
|---|---|---|---|---|
| Sales & distribution | product **shipped/sold** to accounts | invoice line or outlet × week | census (867) / projected (DDD) | ex-factory, ICS 867, wholesaler 867, 852, DDD, SNR |
| Prescription audit | **dispensed Rx demand** | prescriber × product × week | sample-projected | NPA, Xponent, PlanTrak |
| Patient-level claims | **patient events** (fills, procedures, diagnoses, rejects) | claim / claim line × patient token | unprojected panel | LAAD, LRx, Dx/Hx, Komodo, Symphony IDV |
| Provider aggregates | claims volume by provider | HCP/HCO × period | unprojected | Komodo by provider, CMS PUFs |
| Reference/master | who/what/where | entity | n/a | OneKey, Veeva OpenData, NPPES, ZTT |
| Promotion | **field & digital activity** | call/email × HCP | census | Veeva calls, RTE, samples |
| Access | coverage, hub/SP status | plan × product; patient case × event | census | MMIT, hub, SP, copay |
| Clinical RWD | clinical facts | encounter/result × token | panel | EHR, lab |
| Finance/GTN | **price & discount** | contract line, chargeback line, rebate invoice | census | 844/849, rebate utilisation, Medicaid invoices |

**Rule:** never add numbers across families — 867 units, projected TRx and claim counts measure different events.

# Relationships
* **defines** → [Which Dataset Answers Which Question](/data-assets/dataset-selection-guide.md)

