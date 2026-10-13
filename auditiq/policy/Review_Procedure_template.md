# Audit Review Procedure

**Version:** 1.0  
**Effective Date:** 2025-04-01  
**Document Owner:** Internal Audit (synthetic procedure written for AuditIQ)

## 1. Purpose
This procedure describes what happens to an invoice after it has been audited against the Procurement & Vendor Auditing SOP: how its risk is scored, who must look at it, and what the reviewer records. It applies to every invoice audited by the pipeline.

## 2. Findings
A finding states the rule of the SOP that an invoice violates, its severity, and the record fields that show it. A finding comes either from a deterministic control, which compares field values, or from a specialist agent, which reads descriptions, remarks and the other invoices of the vendor. A challenger then tests every agent finding and removes those that the records do not support. Findings from controls are final.

## 3. Confidence
A finding from a control has confidence 1. For a finding from an agent, three things are checked: whether every cited value is in the records, whether the cited rule exists in the active SOP version, and how many of {{reruns}} repeated runs of the same agent report the same rule again. The confidence is the mean of the three.

## 4. Risk Score
Each finding adds points according to its severity: {{w_critical}} for critical, {{w_high}} for high, {{w_medium}} for medium and {{w_low}} for low, up to a maximum of 100. A critical finding raises the score to at least {{floor_critical}}, and a high finding to at least {{floor_high}}. Two scores are computed. The count-based score counts every finding in full. The weighted score counts each finding in proportion to its confidence.

## 5. Routing
- An invoice is approved automatically when its count-based score is below {{tau}}.
- An invoice is escalated to a human reviewer when its weighted score is {{tau}} or more. Payment is held until the review is recorded.
- An invoice whose count-based score is {{tau}} or more but whose weighted score is below {{tau}} goes to the sampled-review queue. It is not approved automatically. A share of this queue, set by Internal Audit, is reviewed by a human.

## 6. Review
The reviewer sees the findings with their evidence, the findings removed by the challenger with the reasons, both scores, and the SOP version applied. The reviewer records one of three decisions, with name and date.
- Approve: the findings do not prevent payment.
- Reject: the invoice is not to be paid as submitted.
- Override: the reviewer sets the findings aside. An override requires a written justification.

## 7. Audit Pack and Audit Trail
For every audited invoice the system keeps an audit pack: the findings with rule, severity, source, confidence and evidence; the removed findings; both scores and the route; the SOP version; and the decision of the reviewer. It also keeps an audit trail with one entry for each stage of the audit. These records are not changed after the decision is recorded.
