# Join Paths

Recommended joins between datasets.

# Concepts

* [867 → HCO → System](/data-model/joins/867-to-hco.md) - Ship-to DEA/HIN/custom key → Veeva custom-key crosswalk → ORG_VID → SYS_VID; then account/zip alignment.
* [Pharmacy Claim → Plan → Formulary](/data-model/joins/claims-to-plan.md) - BIN+PCN+Group or PLAN_ID → plan master → formulary status at date of service.
* [Claims → Product](/data-model/joins/claims-to-product.md) - Normalise NDC to 11 digits → drug mapping/product master → NDC-9 roll-up; for medical lines use HCPCS → NDC crosswalk with unit conversion.
* [CRM Calls → Rx / Claims Volume](/data-model/joins/crm-to-rx.md) - HCP_VID (or NPI_VOD) joins calls to Xponent and Komodo-by-provider; analyse with a lagged response window.
* [Patient Linkage Across Sources](/data-model/joins/patient-linkage.md) - Token-to-token linkage across LAAD, Komodo, EHR, lab, hub/SP — only under expert determination and licence.
* [Xponent → HCP → Territory](/data-model/joins/xponent-to-hcp.md) - Map IMS_PRESCRIBER_ID/NPI_ID to the master HCP, then HCP zip → ZTT territory.
