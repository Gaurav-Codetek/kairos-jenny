# Data Flows

End-to-end flows showing where each dataset is captured.

# Concepts

* [Physician-Administered (IV) Drug Flow](/data-flows/iv-drug-to-medical-claim.md) - Manufacturer → 3PL/specialty distributor → clinic/hospital (867) → administration → 837 medical claim (J-code) → Komodo/LAAD Mx claims.
* [Medical Claim Data Flow](/data-flows/medical-claim.md) - Provider → clearinghouse → payer → 835; captured as open claims (clearinghouse) and closed claims (payer).
* [Money Flow](/data-flows/money-flow.md) - Wholesaler pays WAC; PBM reimburses pharmacy; plan pays PBM; manufacturer pays chargebacks, rebates, Medicaid/Part D discounts and copay.
* [Product, Trade & Chargeback Flow](/data-flows/product-and-trade.md) - Ex-factory → 3PL → wholesaler → account with 867/852/844 data and contract pricing.
* [Prescription to Pharmacy Claim (hop by hop)](/data-flows/rx-to-pharmacy-claim.md) - From the HCP's order to PBM rebate invoices, with the dataset captured at each hop.
