# Pharmacy Claims

NCPDP D.0 claims adjudicated by PBMs.

# Concepts

* [Pharmacy Claim Status & Reject Codes](/claims/pharmacy/claim-status.md) - Paid, rejected, reversed and captured states with NCPDP reject codes; LAAD carries `CLAIM_STATUS` and `REJECT_CODE`.
* [Copay Card Secondary Claim](/claims/pharmacy/copay-card-claim.md) - Manufacturer copay assistance processed as a secondary NCPDP claim on its own BIN/PCN; flagged as `COPAY_CARD_FLAG` in LAAD.
* [NCPDP Telecommunication D.0](/claims/pharmacy/ncpdp-telecom-d0.md) - HIPAA-named standard for real-time pharmacy claims (E1 eligibility, B1 bill, B2 reverse, B3 rebill).
* [Pharmacy Claim Flow](/claims/pharmacy/pharmacy-claim-flow.md) - Pharmacy → switch → PBM real-time adjudication → response → (optional COB/copay secondary) → reversal if not picked up → PBM invoices plan and manufacturer.
