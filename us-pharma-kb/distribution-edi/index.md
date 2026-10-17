# Distribution & EDI

Supply-chain transactions that produce sales, inventory and chargeback data.

# Concepts

* [EDI 810 Invoice](/distribution-edi/edi-810.md) - Invoice for shipped product (ex-factory sale).
* [EDI 844 / 849 Chargeback Claim & Response](/distribution-edi/edi-844-849.md) - Wholesaler claim for the difference between WAC and a contract price, and the manufacturer response.
* [EDI 845 Price Authorization](/distribution-edi/edi-845.md) - Contract/membership eligibility sent to wholesalers.
* [EDI 850 / 855 Purchase Order & Acknowledgment](/distribution-edi/edi-850-855.md) - Wholesaler order to manufacturer/3PL and its acknowledgment.
* [EDI 852 Product Activity Data](/distribution-edi/edi-852.md) - Distribution-centre inventory, receipts and sales by product.
* [EDI 856 Advance Ship Notice](/distribution-edi/edi-856.md) - Shipment notice; carries DSCSA transaction information with serialised EPCIS data.
* [EDI 857 Shipment and Billing Notice](/distribution-edi/edi-857.md) - Combined shipment + invoice transaction (an 856 and 810 in one); occasionally used by 3PLs. If a feed is labelled '857' but carries resale lines, it is usually an 867.
* [EDI 867 Product Transfer & Resale Report](/distribution-edi/edi-867.md) - Wholesaler/3PL report of product sold or transferred to downstream customers, including returns.
* [EDI 940 / 945 Warehouse Shipping Order & Advice](/distribution-edi/edi-940-945.md) - Manufacturer instruction to 3PL and 3PL confirmation.
* [EPCIS / DSCSA Traceability](/distribution-edi/epcis-dscsa.md) - GS1 EPCIS events for serialised package-level tracing required by DSCSA.
* [Product & Trade Data Flow](/distribution-edi/product-trade-flow.md) - Manufacturer → 3PL → wholesaler / specialty distributor → pharmacy or provider, and the EDI each hop generates.
