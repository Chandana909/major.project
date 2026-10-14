# Accounts Payable Control Memorandum

**Version:** {{version}}  
**Issued by:** Finance Controller (synthetic policy written for AuditIQ-Bench)

## Purpose
This memorandum tells the accounts payable team which supplier bills must be reported to Internal Audit before they are paid. It replaces all earlier circulars on the subject.

## Matching the bill to the order and the delivery
A supplier's bill is paid only when it agrees with what we ordered and what we received. The billed amount should be the same as the amount on the purchase order; we accept a gap of no more than {{tolerance}}% of the order value, above or below, and anything wider is reported. The number of units billed may never be greater than the number of units the stores took in. A bill that does not quote a purchase order and a goods receipt note, or quotes one we cannot find, is reported. Stores staff write remarks on the goods receipt note; when a remark says that part of a delivery was rejected, damaged, sent back or never arrived, only the remaining units count as accepted, and a bill for more than that is reported even if the quantity box on the note says otherwise. What the bill describes has to be what the order asked for; a different product or service is reported, while different wording for the same thing is not.

## Bills submitted twice
If a supplier's bill carries a bill number that the same supplier has already used, the later bill is a duplicate and is reported. The same holds when a later bill charges the same order and delivery for the same amount under a number that has merely been re-typed, for instance with other separators, dropped zeros, an added letter or swapped digits. Bills with consecutive numbers for separate orders are not duplicates.

## Tax registration
The GSTIN printed on a bill must consist of exactly {{gstin_length}} letters and digits. Its first two digits are the state code, which must lie between {{state_min}} and {{state_max}}. A properly formed GSTIN must also be the very number we hold for that supplier in the vendor master.

## Supplier conduct
No supplier may present more than {{daily}} bills bearing the same date; if that happens, every bill of that date is reported. We also watch for purchases cut into pieces: bills from one supplier for the same goods, dated on different days inside roughly {{window}} days, each falling within {{band}}% under the approver's ceiling and together above it, are treated as one purchase and all of them are reported. We do not work on {{off_days}}; a bill dated on one of those days is reported. A bill whose amount is an exact multiple of INR {{round}} is reported as a round-sum bill. Bills from a supplier on our blacklist, or whose GST registration is shown as {{statuses}}, are reported and not paid.

## Who may approve what
Each approver may sign off bills up to a ceiling: a Manager up to INR {{limit_manager}}, a Senior Manager up to INR {{limit_senior_manager}}, a Director up to INR {{limit_director}} and the CFO up to INR {{limit_cfo}}. A bill approved by someone whose ceiling is below the bill amount is reported.
