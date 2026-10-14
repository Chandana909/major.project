# Procure-to-Pay Compliance Handbook

**Version:** {{version}}  
**Custodian:** Internal Audit Department (synthetic policy written for AuditIQ-Bench)

## 1. Three-way check
(a) Invoice value and purchase order value are to agree; a variance of up to {{tolerance}} per cent of the purchase order value is condoned, and a larger variance is an audit exception. (b) Invoiced quantity in excess of the quantity received per the goods receipt note is an audit exception. (c) Every invoice is to cite a purchase order and a goods receipt note held on record; a missing or untraceable citation is an audit exception. (d) Where the receiving remarks on a goods receipt note record rejection, damage, return or non-delivery of part of a consignment, the accepted quantity stands reduced accordingly, and invoicing beyond it is an audit exception. (e) The invoice narration is to correspond to the goods or services on the purchase order; narration of other goods or services is an audit exception.

## 2. Repeat invoices
(a) Re-use by a vendor of an invoice number it has used before makes the later invoice an audit exception. (b) A later invoice for the same purchase order, goods receipt and value, whose number is only a re-keyed variant of the earlier number, is likewise an audit exception.

## 3. GST particulars
(a) A GSTIN is {{gstin_length_word}} alphanumeric characters long; any other length or character is an audit exception. (b) The leading two digits, the state code, are to fall in the range {{state_min}} to {{state_max}}. (c) A well-formed GSTIN that differs from the GSTIN registered in the vendor master is an audit exception.

## 4. Vendor behaviour
(a) Not more than {{daily_word}} invoices of one vendor may bear the same invoice date; on a breach, all invoices of that date are audit exceptions. (b) Invoices of one vendor for like goods, raised on separate days within about {{window_word}} days, each within {{band}} per cent below the sanctioning limit of the approver and jointly above it, constitute structuring and are audit exceptions. (c) The office is closed on {{off_days}}; an invoice dated on such a day is an audit exception. (d) An invoice value that is an exact multiple of Rs. {{round_indian}} is an audit exception. (e) An invoice of a blacklisted vendor, or of a vendor whose GST registration status is {{statuses}}, is an audit exception.

## 5. Sanctioning limits
The sanctioning limit of a Manager is Rs. {{limit_manager_indian}}, of a Senior Manager Rs. {{limit_senior_manager_indian}}, of a Director Rs. {{limit_director_indian}} and of the CFO Rs. {{limit_cfo_indian}}. An invoice sanctioned by an officer whose limit is lower than the invoice value is an audit exception.
