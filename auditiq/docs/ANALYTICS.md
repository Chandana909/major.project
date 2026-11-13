# Analytics, coverage and collusion rings

Three read-only analyses of the store, shown on the Overview, Analytics and
Collusion rings pages of the web application. Each is computed from the
ledger, the latest audit result of each invoice and the policy (amounts are
measured against the limits of the version in force on the dates of most of
the invoices, not of a version that took effect after them); none
calls a model and none writes to the store.

| Analysis | Module | Endpoint | Page |
|---|---|---|---|
| Coverage of the latest results | `auditiq/analytics.py` (`coverage`) | `GET /api/overview` (`coverage`) | Overview |
| Forensic analytics of the ledger | `auditiq/analytics.py` (`ledger_analytics`) | `GET /api/analytics` | Analytics |
| Collusion rings and the watch list | `auditiq/rings.py` (`find_rings`) | `GET /api/rings?limit=` | Collusion rings |

Tests: `tests/test_analytics.py` (both backends) and `tests/test_api.py`.

## 1. Coverage of the latest results

The latest result of an invoice comes from the configuration it was last
audited with, so one store can hold results of several configurations. A
configuration without agents (C1) never evaluates the judgement clauses
(2.1.4, 2.1.5, 2.2.2, 4.1.2 in v2.5): an invoice it approves was not checked
against them. The coverage says so instead of letting an approval read as
"clean":

- **configurations**: the number of latest results per configuration;
- **controls_run** and **judgement_run**: how many latest results come from a
  configuration that ran the deterministic controls, and the agents;
- **approved_with_findings**: invoices with a kept finding that were approved.
  One medium (10) or low (5) finding alone cannot reach the threshold of 50,
  so such an invoice is approved with its finding recorded;
- **answer_key** (benchmark ledgers only): the latest results against the
  generator's labels. An anomaly is *found* when its invoice has any kept
  finding; a missed anomaly is *not checked* when its rule is a judgement rule
  and the configuration ran no agents, and *missed* otherwise; a flagged clean
  or hard-negative invoice is a *false alarm*.

The labels hold for the policy version they were written for, recorded from
the dataset's manifest in `meta.labels_policy` when the ledger is loaded
(stores loaded before that use 2.5, the generator's default). Results under
another version are left out and counted (`other_policy`): a changed threshold
makes an invoice anomalous or clean whatever the labels say. When the
500,000-invoice ledger had been audited under v3.12, which took effect after
all its invoices (CODE_REVIEW.md, finding 22), every result was left out
rather than reported as a false alarm.

The Overview page shows the coverage as a panel with these counts, a notice
for each gap, and the answer key per configuration.

## 2. Forensic analytics

One pass over the invoices joined with their latest results, plus small
queries for the vendors, approvers' roles and the policy's approval limits.

| View | What it computes |
|---|---|
| Monthly volume | invoices, amount, invoices with findings, escalated invoices and findings per month (from `invoices.date`) |
| Spend skyline | spend per vendor category and month; drawn in 3D |
| Benford's law | first-digit and first-two-digits tests on the amounts of at least 10: observed and expected shares, the z-statistic of each digit with the continuity correction (marked when above 1.96), chi-square, and the mean absolute deviation with Nigrini's thresholds (Benford's Law, Wiley 2012): first digit 0.006 / 0.012 / 0.015, first two digits 0.0012 / 0.0018 / 0.0022 for close, acceptable and marginally acceptable conformity |
| Amounts against the limits | invoices per quarter-decade of amount (logarithmic), with those that have findings; for each approval limit of the version in force, the invoices within 10 % under it and within 10 % over it. Splitting and structuring pile invoices up just under a limit |
| Day of the week | invoices, amount and invoices with findings per weekday |
| Findings by category and rule | kept findings of the latest results per vendor category and rule |
| Approvers | per approver: role, own limit, invoices, vendors, amount, invoices with findings and their amount, and approvals that broke the approval-limit rule; the twelve with most money on invoices with findings |
| Spend concentration | the Lorenz curve of spend over vendors (51 points), the Gini coefficient over every vendor, the share of the ten largest and the Herfindahl-Hirschman index (sum of squared shares, times 10,000) |

The approval limits are read from the parameter `approval_limits` of the
active version, whatever clause holds it, so a policy that moves or changes
them changes the bands without a code change.

## 3. Collusion rings

The links an auditor follows when looking for collusion between vendors, or
between a vendor and the people who approve its invoices:

| Link | Between | When |
|---|---|---|
| shared PAN | two vendors | two vendor records with the same PAN |
| shared GSTIN | two vendors | two vendor records with the same GST registration |
| another vendor's GSTIN | two vendors | an invoice of one vendor carries the registration of another |
| repeated findings | approver and vendor | the pair's invoices with high or critical findings are more than the approver's role makes likely (test below) |
| above own limit | approver and vendor | a repeated-findings link whose findings include approvals above the approver's own limit |
| approver hotspot | approver and each vendor of their flagged invoices | the approver's approvals as a whole carry more high or critical findings than the role's rate allows |
| concentrated approvals | approver and vendor | one approver approved at least 40 % of the vendor's invoices, at least 10 of them |

**The tests.** The rate of a role is the share of the invoices its approvers
approved that have a kept finding of high or critical severity. A pair is
tested when the approver approved at least two of the vendor's invoices: with
*k* such invoices with findings out of *n*, its p-value is P(X >= *k*) for X ~
Binomial(*n*, rate of the role), and it is a candidate when *k* >= 2. Each
approver is tested the same way over all their approvals. Each family (all
tested pairs; all approvers) is corrected with the Benjamini-Hochberg
procedure, and a link needs a q-value of 0.01 or less.

Comparing an approver with others of the *same role* matters. A policy that
gives a role a lower limit makes that role's approvals break the rules more
often; compared with the whole ledger, every approver of that role would look
unusual, and the whole ledger would form one ring. Identity links need no
test.

**Rings.** A ring is a connected group of links with at least two vendors.
A group around a single vendor is a *pair*, listed apart. Rings are ranked by
the money on the invoices with findings on their links; the strongest `limit`
are drawn, up to 1,500 members.

**The watch list.** When nothing passes, the page still has something to
investigate first: the forty approver-vendor pairs with the smallest p-values
(at least two invoices with findings), each with its *k* of *n*, the number
the role's rate makes expected, its p-value and q-value, grouped like rings
and drawn as *leads below significance*.

A ring, a pair or a lead is a lead for an investigation, not a finding: the
links say who is connected and why, the audit packs of the invoices say what
is wrong.

## 4. Caching

The overview, the risk map, the analytics and the rings take seconds on a
ledger of several hundred thousand invoices. The API keeps each answer with a
fingerprint of the store (`StoreCache` in `auditiq/api.py`): the ledger's name,
the newest audit result, the newest review decision, the policy versions and
their parameters, the offsets of the Kafka workers and the labels' policy.
An audit, a decision, a loaded ledger, a policy change or a streamed batch
moves the fingerprint, and the next request computes afresh; reading it costs
a few index lookups. Each server process has its own cache.

## 5. Limits

- The generated benchmark ledgers assign approvers at random and model no
  collusion, so on them no ring is expected to pass the tests; the watch list
  shows the strongest leads instead.
- Approvers are taken from `invoices.approved_by` and their roles from
  `approval_logs`; an approver without a role is compared with the others
  without one.
- Benford's law describes amounts that span several orders of magnitude and
  arise naturally. Amounts generated from a catalogue of prices and quantities,
  or bound by contracts, can depart from it without any manipulation; the test
  points at where to look, not at what is wrong.
- The answer key exists only for generated ledgers; on a real ledger the
  coverage panel shows the configurations and checks, without a score.
