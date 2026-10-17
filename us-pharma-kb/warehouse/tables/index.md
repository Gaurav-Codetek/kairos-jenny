# Tables

Table-level concepts with Kairos trust level.

# Concepts

* [nexora_poc_catalog.bronze.comm_table_log](/warehouse/tables/bronze-comm-table-log.md) - One row per source file processed by ICS ingestion.
* [nexora_poc_catalog.bronze.raw_ics_867](/warehouse/tables/bronze-raw-ics-867.md) - Raw landing of ICS 867 EDI/sales files.
* [nexora_poc_catalog.bronze.raw_snr_sales](/warehouse/tables/bronze-raw-snr-sales.md) - SNR market × product weekly sales with 340B flag, WAC $, AWP and units.
* [nexora_poc_catalog.bronze.raw_veeva_calls](/warehouse/tables/bronze-raw-veeva-calls.md) - Raw Veeva CRM calls/RTE with HCP/HCO/system VIDs, segments, deciles and KOL flags for Monoferric and Cosela.
* [nexora_poc_catalog.bronze.raw_xponent](/warehouse/tables/bronze-raw-xponent.md) - Raw IQVIA Xponent delivery (prescriber × product group × plan, wide weekly measures).
* [nexora_poc_catalog.bronze.stg_ics_867](/warehouse/tables/bronze-stg-ics-867.md) - Typed, de-duplicated ICS 867 staging rows from the raw_to_stg task.
* [nexora_poc_catalog.gold.bi_account_sales](/warehouse/tables/gold-bi-account-sales.md) - Gold BI mart rolling fct_ics_867 up to organisation/product.
* [nexora_poc_catalog.gold.pharm_cosm_komodo_monoferric_fact_claims_by_provider_20260616](/warehouse/tables/gold-komodo-monoferric-claims-by-provider.md) - Komodo claims for Monoferric (IV iron) aggregated by HCP with affiliated org/system, rolling windows and hemodialysis split.
* [nexora_poc_catalog.gold.rx_mx_claims](/warehouse/tables/gold-rx-mx-claims.md) - Uploaded patient-level Rx + Mx claims table in IQVIA LAAD layout (claim status, reject codes, copay card, NBRx, Dx/Px codes).
* [nexora_poc_catalog.logs.bronze_layer_logs](/warehouse/tables/logs-bronze-layer.md) - Run/audit events for bronze ingestion.
* [nexora_poc_catalog.logs.gold_layer_logs](/warehouse/tables/logs-gold-layer.md) - Run-level audit rows for the gold BI refresh.
* [nexora_poc_catalog.gold.pharm_cosm_sales_all_fact_daily_orders_20260616](/warehouse/tables/pharm-cosm-sales-all-fact-daily-orders.md) - Daily order-level sales fact (shares CONTRACT_ID / INVOICE_ID / NDC_QUALIFIER with fct_ics_867).
* [intelliegencedatacatalog.ddd_sales.raw_ddd](/warehouse/tables/raw-ddd.md) - Raw IQVIA DDD delivery in wide format (one column per week, Sep 2024 – Jan 2026).
* [nexora_poc_catalog.bronze.raw_iqvia_claims_drug_mapping](/warehouse/tables/raw-iqvia-claims-drug-mapping.md) - NDC11/USC → product attributes lookup for claims.
* [nexora_poc_catalog.bronze.raw_market_basket_treatments](/warehouse/tables/raw-market-basket-treatments.md) - Market basket definition of competing treatments.
* [nexora_poc_catalog.bronze.raw_npi_hco_mapping](/warehouse/tables/raw-npi-hco-mapping.md) - NPI → HCO affiliation mapping.
* [nexora_poc_catalog.bronze.raw_npi_info](/warehouse/tables/raw-npi-info.md) - NPI reference extract.
* [nexora_poc_catalog.bronze.raw_onekey](/warehouse/tables/raw-onekey.md) - IQVIA OneKey reference extract.
* [nexora_poc_catalog.silver.curr_ztt](/warehouse/tables/silver-curr-ztt.md) - Current zip → territory/team snapshot.
* [nexora_poc_catalog.silver.dim_hco](/warehouse/tables/silver-dim-hco.md) - Curated HCO master dimension keyed by ORG_VID.
* [nexora_poc_catalog.silver.fct_ics_867](/warehouse/tables/silver-fct-ics-867.md) - Curated ICS 867 invoice-line fact enriched with HCO/system VIDs, customer data and two territory alignments.
* [nexora_poc_catalog.silver.fct_time](/warehouse/tables/silver-fct-time.md) - Canonical calendar dimension.
* [nexora_poc_catalog.silver.network_all_dim_alignment](/warehouse/tables/silver-network-all-dim-alignment.md) - Account (VID) territory/region/national alignment.
