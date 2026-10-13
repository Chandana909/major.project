# Standard Operating Procedure (SOP): Procurement & Vendor Auditing

**Version:** 2.5  
**Effective Date:** 2025-04-01  
**Document Owner:** Internal Audit (synthetic policy written for AuditIQ-Bench)

## 1. Introduction
This SOP defines the exceptions that must be raised when a vendor invoice is audited against its Purchase Order (PO), Goods Receipt Note (GRN), vendor master record and approval log. Each numbered rule defines exactly one exception and its severity. A finding must cite the number of the rule it relies on. Amounts are in INR and exclude tax.

## 2. Invoice, Purchase Order and Goods Receipt
### 2.1 Three-Way Match
- **Rule 2.1.1 (HIGH), amount match.** The invoice amount must equal the PO amount. A difference of up to 1% of the PO amount is tolerated. A larger difference, in either direction, is an exception.
- **Rule 2.1.2 (HIGH), quantity match.** The quantity billed on the invoice must not exceed the received quantity recorded on the GRN.
- **Rule 2.1.3 (HIGH), missing reference.** Every invoice must reference a PO and a GRN that exist in the records. An invoice with no PO reference, with no GRN reference, or with a reference that matches no record is an exception.
- **Rule 2.1.4 (HIGH), receipt remarks.** The remarks on a GRN are part of the receipt. If the remarks record that part of the delivery was rejected, damaged beyond use, returned or not delivered, the accepted quantity is reduced by that part. An invoice that bills more than the accepted quantity is an exception, even when the received-quantity field equals the billed quantity. Remarks that confirm that the full quantity was accepted are not an exception.
- **Rule 2.1.5 (MEDIUM), description match.** The goods or services described on the invoice must be those ordered on the PO. Different wording for the same goods or services is acceptable. A description of different goods or services is an exception.

### 2.2 Duplicate Invoices
Of two matching invoices, the earlier one is the original. The later one is the duplicate and carries the exception. Duplicates are routed to the Fraud Investigation team.
- **Rule 2.2.1 (CRITICAL), exact duplicate.** An invoice whose invoice number has already been used by an earlier invoice from the same vendor is an exception.
- **Rule 2.2.2 (CRITICAL), near duplicate.** An invoice that bills the same PO and GRN for the same amount as an earlier invoice from the same vendor, under an invoice number that is a re-keyed form of the earlier number (for example changed case, separators or leading zeros, an added suffix, or transposed or substituted characters), is an exception. Consecutive invoice numbers for separate POs and separate deliveries are not duplicates, even when the amounts are equal.

## 3. GST Compliance
### 3.1 GST Identification Number (GSTIN)
- **Rule 3.1.1 (MEDIUM), format.** The GSTIN on the invoice must be exactly 15 alphanumeric characters.
- **Rule 3.1.2 (MEDIUM), state code.** The first two characters of the GSTIN must be a state code from 01 to 37.
- **Rule 3.1.3 (HIGH), vendor match.** A GSTIN that satisfies Rules 3.1.1 and 3.1.2 must be identical to the GSTIN in the vendor master record. A malformed GSTIN is reported under Rule 3.1.1 or 3.1.2 only.

## 4. Vendor Behaviour
### 4.1 Splitting
- **Rule 4.1.1 (HIGH), same-day splitting.** A vendor may have at most 3 invoices dated on the same day. When there are more, every invoice of that vendor dated on that day is an exception.
- **Rule 4.1.2 (HIGH), structuring across days.** Invoices from one vendor for the same goods or services, dated on different days within a short period (as a guide, 7 days), each just below the approval limit of the approver who approved it (as a guide, within 15% of the limit) and together above that limit, are treated as one purchase divided to avoid a higher approval. Every invoice of the group is an exception. A single invoice near a limit is not an exception.

### 4.2 Timing
- **Rule 4.2.1 (MEDIUM), non-business day.** Business days are Monday to Friday. An invoice dated on a Saturday or Sunday is an exception.

### 4.3 Round Amounts
- **Rule 4.3.1 (LOW), round amount.** An invoice amount that is an exact multiple of INR 10,000 is an exception.

### 4.4 Vendor Status
- **Rule 4.4.1 (CRITICAL), blocked vendor.** An invoice from a vendor whose master record is marked blacklisted, or whose GST registration status is Suspended, is an exception.

## 5. Approval Hierarchy
### 5.1 Delegation of Authority
The approving entry of an invoice is its latest approval-log entry with the action "Approved". Entries with any other action, such as "Escalated", are not approvals.

| Approver role | Approval limit (INR) |
|---|---|
| Manager | 100,000 |
| Senior Manager | 500,000 |
| Director | 2,500,000 |
| CFO | 10,000,000 |

- **Rule 5.1.1 (CRITICAL), approval limit.** An invoice whose amount is greater than the approval limit of the role that approved it is an exception. An amount equal to the limit is within authority.

## 6. Next-Best Actions
A finding must propose the next verification step.
- Three-way match exceptions (2.1.1 to 2.1.5): request proof of delivery from the warehouse manager and hold payment until the difference is explained.
- Duplicates (2.2.1, 2.2.2): hold payment, confirm with the vendor which invoice is valid, and refer the pair to the Fraud Investigation team.
- GSTIN exceptions (3.1.1 to 3.1.3): ask the vendor for a corrected invoice and hold payment until it is received.
- Splitting and structuring (4.1.1, 4.1.2): review all invoices of the group together and obtain approval at the level required for their total.
- Timing and round amounts (4.2.1, 4.3.1): verify the supporting documents before payment.
- Blocked vendor (4.4.1): stop payment and refer to Vendor Management.
- Approval limit (5.1.1): escalate to an approver whose limit covers the amount.
