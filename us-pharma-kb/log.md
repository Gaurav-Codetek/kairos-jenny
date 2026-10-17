# Log

## 2026-10-03
* **Separated** industry knowledge from one client's warehouse. Concepts outside `warehouse/` no longer name client tables, columns, pipelines, profile results or the Kairos context layer: removed `feeds` relations into `warehouse/`, `warehouse` tags and Kairos citations; generalised ICS 867, SNR, IDN, HCO hierarchy, NDC, Veeva VID, WAC, market basket, the IV-drug data flow and the data-quality rules.
* **Moved** the 867 ↔ Komodo join (client table and column names) to `warehouse/joins/`.

## 2026-10-02
* **Added** dataset-type domain expansion: ICS 867, 3PL vs wholesaler 867, EDI 857 note, DDD, SNR, Xponent/PlanTrak, NPA, LAAD, FIA, LRx, Dx/Hx, Komodo Healthcare Map, Komodo claims extracts, Komodo claims-by-provider, open vs closed claims, CMS PUFs, reference, promotion, access, RWD and GTN datasets.
* **Added** `warehouse/` concepts mapping ICS Sales Warehouse tables (via Kairos, synced 2026-10-01) to dataset types.
* **Created** initial bundle: actors, regulation, identifiers, prescriptions, claims, distribution EDI, pricing/GTN, commercial operations, market access, service providers, KPIs, data flows and canonical data model.
