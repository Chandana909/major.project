# Kafka ingestion

Documents can reach AuditIQ in two ways: a ledger loaded in one go (`setup --dataset`, `ledger import`, the
web application), or a stream of documents through Apache Kafka, where each arrives on its own and is
stored and audited as it comes. This document describes the stream: the topics, the workers, how each
message changes the database exactly once, what an invoice is audited against when it arrives on its own,
how to run it, and what was measured.

Code: `auditiq/stream.py` (topics, publisher, workers, status), `auditiq/emails.py` (vendor e-mails),
`auditiq_bench/correspondence.py` (synthetic e-mails), `scripts/kafka_local.py` (a local broker),
`evaluation/stream_eval.py` (the measurement), `tests/test_stream.py`.

## 1. Topics

Four topics, each with `AUDITIQ_KAFKA_PARTITIONS` partitions (4 by default). Their names start with
`AUDITIQ_KAFKA_PREFIX` (`auditiq` by default).

| Topic | One message is | Key | Written to |
|---|---|---|---|
| `auditiq.vendor` | a vendor master record from the vendor feed | vendor id | `vendor_master` |
| `auditiq.invoice` | an invoice with its purchase order, goods receipt and approval log entries, as the procurement system has them | vendor id | the four ledger tables, then an audit result |
| `auditiq.email` | a vendor e-mail as received: MIME bytes (RFC 5322) | `Message-ID` | `emails`, `email_mentions` |
| `auditiq.compliance` | a policy document (PDF) and whether to activate it | file name | a policy version (`policy_extract.adopt`) |

Records are published as the source system exports them, every value as text; the worker converts each
value to the type its column stores (`db.typed`), as loading a CSV file does.

Invoices are keyed by vendor, so all invoices of a vendor go to the same partition, in the order they
were published (the ledger's order: date, then id). One partition is read by one worker at a time, so a
vendor's invoices are processed in order.

## 2. Workers

A worker consumes one topic in that topic's consumer group (`auditiq-invoice-workers`, ...). It keeps no
state of its own: everything it learns goes to the database. Kafka divides a topic's partitions among the
group's workers, so partitions are the unit of parallelism: up to as many invoice workers as the invoice
topic has partitions do useful work, and adding partitions (`stream topics --partitions N`) and workers
raises the throughput without changing a worker. A worker that stops (or is added) makes the group
rebalance; the others take over its partitions.

What each worker does with a message:

- **vendor**: inserts the vendor, or updates it if it is known (a change of name, of GSTIN status, a
  blacklisting).
- **invoice**: waits until the invoice's vendor is known (it comes through the vendor topic, which another
  worker reads); stores the invoice, PO, goods receipt and approvals; audits the invoice with the
  configuration of the worker (`--config`, C1 by default) under the policy version in force on the invoice's
  date (a version activated on the compliance topic governs the invoices from its effective date); stores the result
  as a batch audit does (flags, citations, revision, audit trail, review queue). A model configuration
  (C3 to C5) calls the model for each invoice, as `run` does.
- **email**: parses the message with Python's email package, stores it, and links it to the invoice it
  names (Section 5).
- **compliance**: compiles the document into a policy version, or refuses it with the reasons if the
  controls cannot execute it (the same check as `policy adopt`); activates it if the message says so. The
  invoice workers change to a newly activated version at their next batch, in a run of its own.

Each message gets a row in `stream_log`: when it was published, when it was processed, the outcome
(`stored`, `audited`, `adopted`, `refused`, `error`) and the detail. A message that cannot be processed (not
JSON, not an e-mail, an invoice that refers to unknown records) is logged with the reason and skipped, so one
bad document does not stop its partition. An invoice whose vendor has not arrived after `vendor_wait`
seconds (60) is logged as an error and skipped.

## 3. Each message changes the database exactly once

Kafka delivers a message at least once: after a crash or a rebalance, a worker can be given messages that
were already processed. So the worker does not rely on the offsets it commits to Kafka:

1. A batch of messages and everything they write go into one database transaction, together with the next
   offset of each partition, in `stream_offsets`.
2. When it is given a partition, a worker starts from the offset in the database, not from Kafka's.
3. A batch is stored only if no other worker has moved a partition past where the batch began. A worker that
   lost its partitions in a rebalance it had not yet noticed rolls its batch back (`Fenced`) and goes on from
   what the database holds.

The offsets committed to Kafka serve only to show the lag. The publisher is idempotent
(`enable.idempotence`, `acks=all`), so a retried send does not duplicate a message. A run holds one result per
invoice; an invoice published twice starts a new run of the worker.

On SQLite, a worker takes the write lock when it begins a batch (`BEGIN IMMEDIATE`): two workers that each
read and then tried to write would deadlock, and SQLite fails one of them instead of letting it wait.
SQLite runs one write at a time, so several workers on SQLite take turns writing; PostgreSQL lets them write
at once.

## 4. What an invoice is audited against

In a batch audit an invoice is compared with every other invoice of its vendor in the ledger, earlier and
later. On the stream, a later invoice has not arrived yet. The stream worker therefore audits an invoice
against the vendor's invoices that come before it in ledger order (`db.extract_arrived`). That is the order
in which they arrive, so the result does not depend on how the stream was cut into batches.

One control looks at later invoices too: same-day splitting (Rule 4.1.1) counts all invoices of the vendor on
the invoice's day. When invoices are split, the first ones of the day are within the limit when they arrive;
only the one that takes the day over the limit shows the pattern. When that happens, the worker audits the
day's earlier invoices again, now that the group is complete, in a run of its own ("invoices audited again
when a later invoice completed their same-day group"), and says so in the triggering invoice's log entry.
Without this step, a development run of the measurement (27 October, before the step was added) lost the
4.1.1 finding of 21 of the 5,000 invoices of `bench_seed_202`, and F1 fell from 0.833 to 0.798; with it, the
stream ends with the findings of the batch audit for every invoice (Section 8). The duplicate control (2.2.1) already looks only at earlier invoices.

## 5. Vendor e-mails

An e-mail is linked to the invoice whose number it contains: the subject first, then the body; a number shared
by two invoices (a duplicate) goes to the latest one dated on or before the e-mail. Numbers are found as tokens
of letters and digits (INV-ROU-0146, BED00312, GOY/25-26/00432) and looked up as written.

An e-mail and its invoice come through different topics, so the e-mail can arrive first. The numbers each
e-mail mentions are stored (`email_mentions`); when invoices arrive, the invoice worker links the waiting
e-mails that mention them. On PostgreSQL the two workers can write an e-mail and its invoice at the same
moment, and neither transaction sees the other's row before it commits; both take an advisory lock for the
linking (`emails.lock_linking`), so the later one sees the earlier one's row. The invoice worker takes it at
the end of its batch, so invoice workers do not wait for each other's audits. In a development run with 4
invoice workers before the lock was added, 1,569 of 2,105 e-mails were linked; with it, see Section 8.

The web application shows an invoice's e-mails on its page. Reading what an e-mail asks for (a change of bank
details from a look-alike domain, for instance) is the job of an e-mail triage agent, which is not built: the
e-mails are stored and linked, not judged.

`python -m auditiq_bench.correspondence --dataset <ledger> --out <file.mbox>` writes synthetic e-mails for a
ledger: invoices sent for payment, payment reminders, quantity queries, and requests to change bank details,
some of them from a look-alike of the vendor's domain. A labels file beside the mbox says what each one is.
Every address is under the reserved domain `.example`; the same ledger and seed give the same file.

## 6. Running it

A local broker, without Docker (Java 17 or later; Kafka 4.3.2 was downloaded from downloads.apache.org and
checked against its published SHA-512):

```
python scripts/kafka_local.py init kafka_2.13-4.3.2.tgz     # unpack, format; writes AUDITIQ_KAFKA_BOOTSTRAP to .env
python scripts/kafka_local.py start
```

Then, with a store that has the policy versions (`setup` without `--dataset` loads no ledger):

```
python -m auditiq setup
python -m auditiq stream topics                              # the four topics, 4 partitions each
python -m auditiq stream work --processes 4                  # one worker per topic, four on the invoices
python -m auditiq_bench.correspondence --dataset data/bench_seed_202 --out .auditiq/mail.mbox
python -m auditiq stream publish --dataset data/bench_seed_202 --emails .auditiq/mail.mbox
python -m auditiq stream publish --policy policy/pdf/Procurement_Audit_SOP_v2.6.pdf --activate
python -m auditiq stream status                              # messages, processed, lag, outcomes per topic
```

`stream work` runs until Ctrl+C (`--idle-exit N` stops it after N seconds without a message); `--topic`
runs one topic only, `--config` audits with another configuration. In containers,
`deploy/docker-compose.yml` starts a broker and a `workers` service beside the application and the database.
The Pipeline page of the web application shows the four topics (`GET /api/stream`), and the Kafka streams
page drives the same path from the browser (Section 6.1).

The local broker listens on 127.0.0.1 only and keeps messages until `kafka_local.py reset`: deleting log
segments by age is unreliable on Windows. `stop` ends the broker process; Kafka recovers its logs at the next
start.

### 6.1 From the web application

The Kafka streams page (`/kafka`) publishes and consumes through the API, as the commands above do:

| Endpoint | Does |
|---|---|
| `GET /api/stream/sources` | the ledgers under `data/`, the mailboxes under `.auditiq/` and the policy documents under `policy/pdf/` that can be published |
| `POST /api/stream/publish` | a job: a ledger (its first `limit` invoices in ledger order), a mailbox or a policy document to the topics; the topics are created when missing |
| `POST /api/stream/work` | a job: the workers of the topics chosen run until each topic has been idle for `idle_exit` seconds |
| `GET /api/stream/log` | the newest messages the workers processed, with partition, offset, outcome, the result and the time from produced to processed |
| `GET /api/stream/peek?kind=` | the newest messages of a topic as they sit in Kafka, read without joining a worker's group |
| `GET /api/system` | whether the broker answers, and the model, the embeddings and the store |

The generated ledgers reuse their invoice numbers (INV40001 onward), so publishing another ledger into a store
would silently replace its invoices with different ones under the same numbers. `POST /api/stream/publish`
refuses such a ledger with 409 and says how many invoices it would replace (`stream.ledger_clash`: same number,
another vendor, date or amount); the store's own ledger can be published again, which replaces nothing. The
page offers the store's own ledger first.

On Windows the local broker had two faults of its own (CODE_REVIEW.md, finding 26): it could not delete a
metadata snapshot it had marked read-only, and compaction failed to rename an open segment, which took the log
directory offline. `kafka_local.py start` now clears the read-only flag on the broker's files and writes the
configuration with `log.cleaner.enable=false` (a development broker keeps every message anyway).

## 7. Tests

`tests/test_stream.py` runs against a real broker (`AUDITIQ_TEST_KAFKA_BOOTSTRAP`), each test with topics of
its own. It checks that a ledger streamed into an empty store ends with the findings of the batch audit on
SQLite and on PostgreSQL; that a worker started again processes nothing (exactly once); that an invoice waits
for its vendor, and is skipped with a reason if the vendor never comes; that bad messages are logged and the
partition goes on; that a policy document becomes the version the workers apply, that a document the controls
cannot execute is refused, and that the active version's own document leaves it active; that two workers
share the partitions and audit every invoice once; and that e-mails are linked whichever arrives first. CI
runs the broker in a service container and fails the job if it is missing.

## 8. Measured

`python -m evaluation.stream_eval` publishes the 5,000 invoices of `bench_seed_202`, its 250 vendors and 2,105
synthetic e-mails as one burst to fresh topics of 4 partitions on the local broker, with the workers already
waiting, and takes the time until every invoice is audited (C1) and every e-mail stored. The results are in
`results/stream/` (one file per backend).

| Backend | Invoice workers | Seconds to the last result, median (all three runs) | Invoices/s | Latency median / p95 (s) | Same findings as the batch audit | F1 | E-mails linked to their invoice | Messages in error |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| SQLite | 1 | 21.92 (19.35, 24.75, 21.92) | 228.1 | 12.8 / 21.2 | 5,000 of 5,000 | 0.833 | 2,100 of 2,105 | 0 |
| SQLite | 2 | 17.56 (19.97, 17.56, 16.95) | 284.8 | 11.0 / 16.2 | 5,000 of 5,000 | 0.833 | 2,102 of 2,105 | 0 |
| PostgreSQL | 1 | 27.2 (32.91, 27.2, 26.38) | 183.8 | 16.2 / 26.8 | 5,000 of 5,000 | 0.833 | 2,102 of 2,105 | 0 |
| PostgreSQL | 2 | 23.22 (23.22, 23.3, 22.66) | 215.3 | 14.0 / 20.9 | 5,000 of 5,000 | 0.833 | 2,101 of 2,105 | 0 |
| PostgreSQL | 4 | 18.04 (18.46, 18.04, 17.24) | 277.2 | 12.9 / 17.6 | 5,000 of 5,000 | 0.833 | 2,101 of 2,105 | 0 |

Every run of every setting gave the batch audit's findings for every invoice. On SQLite one worker took 21.92 s (228.1 invoices/s; its three runs from 19.35 to 24.75 s) and two took 17.56 s (16.95 to 19.97 s). A worker on SQLite holds the write lock for its whole batch, audits included, so what a second worker gains comes from outside the lock, such as fetching and decoding the next batch; that was not measured separately. On PostgreSQL 1, 2 and 4 workers took 27.2, 23.22 and 18.04 s (183.8, 215.3 and 277.2 invoices/s): 1.51 times faster with four workers, on a laptop that also runs the broker and the database. One worker is slower on PostgreSQL than on SQLite: each statement is a round trip to a server rather than a call into a library (the likely reason; not measured separately). In every run 2,100 to 2,102 of the 2,105 e-mails were linked to the invoice they were written about. Each setting was run three times; RESULTS.md, Section 5.2, discusses the numbers.

Latency is the time from publication to the stored result. With everything published at once it is mostly
time spent waiting in the topic; it is not the time to audit one invoice. The machine is one laptop
(Intel Core i5-1235U, 12 logical CPUs, 16 GB), with the broker, the database and the workers on it.

## 9. Limits

- One broker and one replica per partition locally and in the compose file: a lost disk loses the messages
  not yet processed. A production cluster has three brokers and a replication factor of 3
  (`AUDITIQ_KAFKA_REPLICATION`).
- Invoices are ordered per vendor because they are keyed by vendor; adding partitions to a topic that already
  has messages moves some vendors to another partition for new messages.
- The workers are parallel, the database is not distributed: past a point the database is the limit. On
  SQLite the writes take turns; more than two workers on SQLite were not measured.
- E-mails are stored and linked; no agent reads them yet (Section 5).
