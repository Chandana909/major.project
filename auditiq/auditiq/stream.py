"""The Kafka ingestion layer: four partitioned topics and stateless workers that write to the database.

Documents enter through four topics (the names start with AUDITIQ_KAFKA_PREFIX, `auditiq` by default):

    auditiq.vendor      a vendor master record from the vendor feed              key: vendor id
    auditiq.invoice     an invoice with its purchase order, goods receipt and
                        approval log entries, as the procurement system has them  key: vendor id
    auditiq.email       a vendor e-mail, as MIME bytes (RFC 5322)                 key: Message-ID
    auditiq.compliance  a policy document (PDF) to compile into a policy version  key: file name

A worker consumes one topic in that topic's consumer group and keeps no state of
its own: what it learns goes to the database. Partitions are the unit of
parallelism, so the number of partitions is the scaling lever: run up to as many
invoice workers as the invoice topic has partitions. Invoices are keyed by vendor,
so the invoices of a vendor stay in order on one partition and each is audited
against the vendor's invoices that came before it (db.extract_arrived). An
invoice can complete a pattern that earlier ones belong to: the one that takes a
vendor's day over the limit of invoices per day makes the day's earlier invoices
split invoices too. Those are audited again when that happens, so the stream
ends with the findings an audit of the whole ledger gives.

Each message changes the database exactly once. A worker stores the next offset
of each of its partitions in the database, in the same transaction as what the
messages wrote, and resumes from the stored offsets after a restart or a
rebalance; the offsets it also commits to Kafka only serve to show the lag. A
batch is stored only if no other worker has moved a partition past where the
batch began, so a worker that lost its partitions cannot write them twice.
Every message gets a row in stream_log: when it was produced, when it was
processed, and what came of it. A message that cannot be processed is logged
with the reason and skipped, so one bad document does not stop a partition. An
invoice whose vendor is not known yet waits (the vendor feed is another topic)
and is logged as an error only if the vendor has not arrived after a while.
"""
from __future__ import annotations

import base64
import email as email_parser
import json
import logging
import mailbox
import os
import socket
import tempfile
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from . import db, emails, policy_extract, prompts
from .config import load_env
from .graph import PipelineConfig, build_graph, preset
from .llm import ChatClient
from .policy_ingest import clause_citations
from .service import store_result

log = logging.getLogger(__name__)
KINDS = ("invoice", "email", "vendor", "compliance")


class StreamUnavailable(RuntimeError):
    """No Kafka broker is configured, or it cannot be reached."""


class Fenced(RuntimeError):
    """Another worker has processed a partition past where this batch began (after a rebalance this worker did not
    see in time); the batch is rolled back so that no message is written twice."""


@dataclass(frozen=True)
class StreamSettings:
    bootstrap: str
    prefix: str = "auditiq"
    partitions: int = 4
    replication: int = 1

    @classmethod
    def from_env(cls) -> StreamSettings:
        load_env()
        bootstrap = os.environ.get("AUDITIQ_KAFKA_BOOTSTRAP", "").strip()
        if not bootstrap:
            raise StreamUnavailable("AUDITIQ_KAFKA_BOOTSTRAP is not set. Start the local broker with "
                                    "`python scripts/kafka_local.py start`, or point it at a Kafka cluster.")
        return cls(bootstrap, os.environ.get("AUDITIQ_KAFKA_PREFIX", "auditiq").strip() or "auditiq",
                   int(os.environ.get("AUDITIQ_KAFKA_PARTITIONS", "4")),
                   int(os.environ.get("AUDITIQ_KAFKA_REPLICATION", "1")))

    def topic(self, kind: str) -> str:
        return f"{self.prefix}.{kind}"

    def group(self, kind: str) -> str:
        return f"{self.prefix}-{kind}-workers"

    def client(self, **extra) -> dict:
        return {"bootstrap.servers": self.bootstrap, **extra}


def _admin(settings: StreamSettings):
    from confluent_kafka.admin import AdminClient
    return AdminClient(settings.client())


def _cluster_topics(settings: StreamSettings, timeout: float = 10.0) -> dict:
    from confluent_kafka import KafkaException
    try:
        return _admin(settings).list_topics(timeout=timeout).topics
    except KafkaException as error:
        raise StreamUnavailable(f"cannot reach the Kafka broker at {settings.bootstrap}: {error}") from None


def ensure_topics(settings: StreamSettings, partitions: int | None = None) -> dict[str, int]:
    """Create the four topics, or add partitions to those that have fewer than asked. Returns topic -> partitions.

    Kafka cannot take partitions away. Adding them moves some keys to other partitions for new messages, so the
    order of a vendor's invoices holds only from then on."""
    from confluent_kafka.admin import NewPartitions, NewTopic
    want = partitions or settings.partitions
    existing = _cluster_topics(settings)
    admin = _admin(settings)
    new = [NewTopic(settings.topic(k), num_partitions=want, replication_factor=settings.replication)
           for k in KINDS if settings.topic(k) not in existing]
    for future in admin.create_topics(new).values() if new else ():
        future.result()
    grow = [NewPartitions(settings.topic(k), want) for k in KINDS
            if settings.topic(k) in existing and len(existing[settings.topic(k)].partitions) < want]
    for future in admin.create_partitions(grow).values() if grow else ():
        future.result()
    deadline = time.monotonic() + 15
    while True:                     # creation is asynchronous: wait until the metadata shows every partition
        topics = _cluster_topics(settings)
        counts = {settings.topic(k): len(topics[settings.topic(k)].partitions) if settings.topic(k) in topics else 0
                  for k in KINDS}
        if all(n >= want for n in counts.values()) or time.monotonic() > deadline:
            return counts
        time.sleep(0.2)


# ------------------------------------------------------------------ producing
class Publisher:
    """Sends documents to the topics. Delivery is idempotent (`enable.idempotence`) and acknowledged by all
    in-sync replicas; `close` waits for every message and raises if any was not delivered."""

    def __init__(self, settings: StreamSettings):
        from confluent_kafka import Producer
        self.settings = settings
        self.failed: list[str] = []
        self.sent = {kind: 0 for kind in KINDS}
        self.producer = Producer(settings.client(**{
            "enable.idempotence": True, "acks": "all", "linger.ms": 20, "compression.type": "lz4",
            "client.id": f"auditiq-publisher-{socket.gethostname()}"}))

    def _delivered(self, error, message) -> None:
        if error is not None:
            self.failed.append(f"{message.topic()} key {message.key()!r}: {error}")

    def send(self, kind: str, key: str, value: bytes) -> None:
        while True:
            try:
                self.producer.produce(self.settings.topic(kind), key=key.encode("utf-8"), value=value,
                                      on_delivery=self._delivered)
                break
            except BufferError:             # the local queue is full: let the broker take some first
                self.producer.poll(0.5)
        self.producer.poll(0)
        self.sent[kind] += 1

    def send_json(self, kind: str, key: str, document: dict) -> None:
        self.send(kind, key, json.dumps(document, ensure_ascii=False).encode("utf-8"))

    def close(self, timeout: float = 120.0) -> dict[str, int]:
        left = self.producer.flush(timeout)
        if left or self.failed:
            raise StreamUnavailable(f"{left} message(s) not delivered; " + "; ".join(self.failed[:5]))
        return dict(self.sent)


def _feed(dataset: Path, name: str) -> list[dict]:
    # As the procurement system exports them: every value is text, converted by the worker as the column stores it.
    return pd.read_csv(Path(dataset) / f"{name}.csv", dtype=str, keep_default_na=False,
                       encoding="utf-8").to_dict("records")


def publish_ledger(publisher: Publisher, dataset: Path, limit: int | None = None) -> dict[str, int]:
    """The vendor feed, then the invoices in ledger order (date, then id), each with its PO, GRN and approvals."""
    po = {r["po_id"]: r for r in _feed(dataset, "purchase_orders")}
    grn = {r["grn_id"]: r for r in _feed(dataset, "goods_receipts")}
    approvals: dict[str, list[dict]] = {}
    for entry in _feed(dataset, "approval_logs"):
        approvals.setdefault(entry["transaction_id"], []).append(entry)
    for vendor in _feed(dataset, "vendor_master"):
        publisher.send_json("vendor", vendor["vendor_id"], {"vendor": vendor})
    invoices = sorted(_feed(dataset, "invoices"), key=lambda r: (r["date"], r["invoice_id"]))
    for invoice in invoices[:limit]:
        publisher.send_json("invoice", invoice["vendor_id"], {
            "invoice": invoice, "po": po.get(invoice["po_id"]), "grn": grn.get(invoice["grn_id"]),
            "approvals": approvals.get(invoice["invoice_id"], [])})
    return {"vendor": publisher.sent["vendor"], "invoice": publisher.sent["invoice"]}


def publish_mailbox(publisher: Publisher, path: Path) -> int:
    """Every message of an mbox file, as it was received."""
    box = mailbox.mbox(Path(path), create=False)
    try:
        count = 0
        for message in box:
            publisher.send("email", str(message["Message-ID"] or count), message.as_bytes())
            count += 1
        return count
    finally:
        box.close()


def publish_policy(publisher: Publisher, path: Path, activate: bool = False) -> None:
    path = Path(path)
    publisher.send_json("compliance", path.name, {"file": path.name, "activate": activate,
                                                  "pdf": base64.b64encode(path.read_bytes()).decode("ascii")})


# ------------------------------------------------------------------ consuming
Outcome = tuple[object, str, str, int | None]        # (message, outcome, detail, result id)


class Worker:
    """Consumes one topic in its consumer group and writes what it reads to the database."""

    def __init__(self, settings: StreamSettings, conn: db.Database, kind: str, *, config: PipelineConfig | None = None,
                 client: ChatClient | None = None, batch: int = 500, sample_rate: float = 1.0,
                 vendor_wait: float = 60.0):
        if kind not in KINDS:
            raise ValueError(f"unknown topic {kind!r}; one of {', '.join(KINDS)}")
        self.settings, self.conn, self.kind = settings, conn, kind
        self.topic, self.group = settings.topic(kind), settings.group(kind)
        self.config = config or preset("C1")
        self.client, self.batch, self.sample_rate, self.vendor_wait = client, batch, sample_rate, vendor_wait
        self.handle: Callable[[list], tuple[list[Outcome], dict[int, int]]] = {
            "vendor": self._vendors, "invoice": self._invoices, "email": self._emails,
            "compliance": self._policies}[kind]
        # The worker's runs, one per policy version: (version, False), and (version, True) for audits done again.
        self.runs: dict[tuple[str, bool], int] = {}
        self.new_runs: set[tuple[str, bool]] = set()     # runs started in the batch not yet committed
        self.timeline: list[tuple[str, str]] | None = None
        self.governing: dict[str, tuple] = {}            # version -> (policy, graph, citations)
        self.known_vendors: set[str] = set()
        self.waiting_since: dict[tuple[int, int], float] = {}
        self.counts: dict[str, int] = {}
        if conn.backend == "sqlite":        # other workers may be writing: wait for the lock instead of failing
            conn.raw.execute("PRAGMA busy_timeout = 60000")

    # -- the consumer -----------------------------------------------------------
    def _consumer(self):
        from confluent_kafka import Consumer
        consumer = Consumer(self.settings.client(**{
            "group.id": self.group, "enable.auto.commit": False, "auto.offset.reset": "earliest",
            "client.id": f"auditiq-{self.kind}-{socket.gethostname()}-{os.getpid()}",
            # A batch audited with a model can take minutes; the group must not take the partitions away meanwhile.
            "max.poll.interval.ms": 1_800_000}))

        def on_assign(consumer, partitions):
            stored = self._stored()
            self.conn.rollback()            # the read must not hold a transaction open while the worker waits
            for p in partitions:
                if p.partition in stored:
                    p.offset = int(stored[p.partition])     # the database, not Kafka, says where to go on
            consumer.assign(partitions)
            log.info("%s: assigned partitions %s", self.topic, sorted(p.partition for p in partitions))

        consumer.subscribe([self.topic], on_assign=on_assign)
        return consumer

    def run(self, idle_exit: float | None = None, max_messages: int | None = None) -> dict[str, int]:
        """Consume until stopped (Ctrl+C); with ``idle_exit``, also stop after that many seconds without a message.
        Returns the number of messages per outcome."""
        from confluent_kafka import KafkaError, KafkaException, TopicPartition
        consumer = self._consumer()
        idle_since, seen = time.monotonic(), 0
        try:
            while max_messages is None or seen < max_messages:
                messages = []
                for m in consumer.consume(num_messages=self.batch, timeout=1.0):
                    if m.error() is None:
                        messages.append(m)
                    elif m.error().code() != KafkaError._PARTITION_EOF:
                        raise KafkaException(m.error())
                if not messages:
                    if idle_exit is not None and time.monotonic() - idle_since >= idle_exit:
                        break
                    continue
                idle_since = time.monotonic()
                self._begin()
                try:
                    done, waiting = self.handle(messages)
                    nexts = self._record(done)
                    self.conn.commit()
                    self.new_runs.clear()
                except Fenced as error:
                    self.conn.rollback()
                    for key in self.new_runs:           # their rows were rolled back with the batch
                        self.runs.pop(key, None)
                    self.new_runs.clear()
                    log.warning("%s: %s", self.topic, error)
                    for partition, offset in self._stored().items():     # go on from what the database holds
                        consumer.seek(TopicPartition(self.topic, partition, offset))
                    continue
                for _, outcome, _, _ in done:
                    self.counts[outcome] = self.counts.get(outcome, 0) + 1
                seen += len(done)
                if nexts:
                    consumer.commit(offsets=[TopicPartition(self.topic, p, n) for p, n in nexts.items()],
                                    asynchronous=True)
                for partition, offset in waiting.items():      # read these again once their vendor is known
                    consumer.seek(TopicPartition(self.topic, partition, offset))
                if waiting and not done:
                    time.sleep(0.5)
        except KeyboardInterrupt:
            log.info("%s: stopping", self.topic)
        finally:
            self.conn.rollback()
            consumer.close()
            self._finish_runs()
        return dict(self.counts)

    def _stored(self) -> dict[int, int]:
        return {int(p): int(n) for p, n in self.conn.execute(
            "SELECT partition_no, next_offset FROM stream_offsets WHERE consumer_group = ? AND topic = ?",
            (self.group, self.topic)).fetchall()}

    def _begin(self) -> None:
        # SQLite: open the transaction now, so that a message's savepoint is nested in it and its release does not
        # commit the batch piecemeal, and take the write lock at once (IMMEDIATE): two workers that each read
        # first and then try to write would deadlock, and SQLite fails one of them instead of letting it wait.
        # On PostgreSQL the first statement opens the transaction and rows are locked one by one.
        if self.conn.backend == "sqlite" and not self.conn.raw.in_transaction:
            self.conn.execute("BEGIN IMMEDIATE")

    def _record(self, done: list[Outcome]) -> dict[int, int]:
        """Log the processed messages and store, per partition, the offset to resume from. Not committed. Raises
        Fenced if another worker has moved a partition past where this batch began."""
        now_ms = int(time.time() * 1000)
        self.conn.executemany(
            "INSERT INTO stream_log (topic, partition_no, kafka_offset, doc_key, produced_ms, processed_ms, outcome, "
            "detail, result_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT (topic, partition_no, kafka_offset) "
            "DO UPDATE SET processed_ms = excluded.processed_ms, outcome = excluded.outcome, "
            "detail = excluded.detail, result_id = excluded.result_id",
            [(self.topic, m.partition(), m.offset(), (m.key() or b"").decode("utf-8", "replace"),
              m.timestamp()[1] if m.timestamp()[1] > 0 else None, now_ms, outcome, detail[:1000], result_id)
             for m, outcome, detail, result_id in done])
        firsts: dict[int, int] = {}
        nexts: dict[int, int] = {}
        for m, _, _, _ in done:
            firsts[m.partition()] = min(firsts.get(m.partition(), m.offset()), m.offset())
            nexts[m.partition()] = max(nexts.get(m.partition(), 0), m.offset() + 1)
        for partition, next_offset in nexts.items():
            # Move the stored offset only from at most where this batch began (it can be lower when old messages
            # were deleted by retention); a stored offset beyond it means another worker got there first.
            moved = self.conn.execute(
                "UPDATE stream_offsets SET next_offset = ? WHERE consumer_group = ? AND topic = ? AND partition_no = ? "
                "AND next_offset <= ?", (next_offset, self.group, self.topic, partition, firsts[partition])).rowcount
            if moved:
                continue
            added = self.conn.execute(
                "INSERT INTO stream_offsets (consumer_group, topic, partition_no, next_offset) VALUES (?, ?, ?, ?) "
                "ON CONFLICT (consumer_group, topic, partition_no) DO NOTHING",
                (self.group, self.topic, partition, next_offset)).rowcount
            if not added:
                raise Fenced(f"partition {partition} was processed past offset {firsts[partition]} by another worker")
        return nexts

    def _each(self, messages: list, work: Callable[[object], tuple[str, str, int | None]]) -> list[Outcome]:
        """Process messages one by one; a message that fails is logged with the reason, the others are kept."""
        done = []
        for m in messages:
            self._begin()
            self.conn.execute("SAVEPOINT message")
            try:
                done.append((m, *work(m)))
                self.conn.execute("RELEASE SAVEPOINT message")
            except Exception as error:      # noqa: BLE001 - any bad document is logged and skipped
                self.conn.execute("ROLLBACK TO SAVEPOINT message")
                self.conn.execute("RELEASE SAVEPOINT message")
                log.warning("%s offset %d: %s", self.topic, m.offset(), error)
                done.append((m, "error", f"{type(error).__name__}: {error}", None))
        return done

    # -- the four topics ---------------------------------------------------------
    def _vendors(self, messages: list) -> tuple[list[Outcome], dict[int, int]]:
        def work(m):
            vendor = json.loads(m.value())["vendor"]
            db.upsert_records(self.conn, "vendor_master", "vendor_id", [vendor])
            return "stored", vendor["vendor_id"], None
        return self._each(messages, work), {}

    def _emails(self, messages: list) -> tuple[list[Outcome], dict[int, int]]:
        self._begin()
        emails.lock_linking(self.conn)

        def work(m):
            mail = emails.store(self.conn, m.value())
            if mail["invoice_id"]:
                return "stored", f"linked to {mail['invoice_id']}", None
            if mail["mentions"]:
                return "stored", "waiting for the invoice it names: " + ", ".join(mail["mentions"][:3]), None
            return "stored", "names no invoice", None
        return self._each(messages, work), {}

    def _policies(self, messages: list) -> tuple[list[Outcome], dict[int, int]]:
        # Adopting a document commits by itself (policy_extract.adopt), so it cannot sit in a message's savepoint.
        # Adopting the same document again stores the same version again, so a repeat after a crash is harmless.
        done: list[Outcome] = []
        for m in messages:
            try:
                document = json.loads(m.value())
                with tempfile.TemporaryDirectory() as folder:
                    path = Path(folder) / Path(document["file"]).name
                    path.write_bytes(base64.b64decode(document["pdf"]))
                    report = policy_extract.adopt(self.conn, path, activate=bool(document.get("activate")))
                if report["adopted"]:
                    done.append((m, "adopted", f"version {report['version']}" + (", active" if report.get("active")
                                                                                   else ""), None))
                else:
                    done.append((m, "refused", "; ".join(report["problems"]) or "not adopted", None))
            except Exception as error:      # noqa: BLE001 - any bad document is logged and skipped
                self.conn.rollback()
                done.append((m, "error", f"{type(error).__name__}: {error}", None))
            self._begin()
        return done, {}

    def _invoices(self, messages: list) -> tuple[list[Outcome], dict[int, int]]:
        self._read_timeline()
        packets, blocked, waiting = [], set(), {}

        def vendor_of(m) -> str | None:
            try:
                return str(json.loads(m.value())["invoice"]["vendor_id"])
            except (ValueError, KeyError, TypeError):
                return None             # not an invoice document: store() logs why

        missing = {vendor_of(m) for m in messages} - self.known_vendors - {None}
        if missing:
            found = self.conn.execute(f"SELECT vendor_id FROM vendor_master WHERE vendor_id IN "
                                      f"({', '.join('?' for _ in missing)})", sorted(missing)).fetchall()
            self.known_vendors |= {r[0] for r in found}
        for m in messages:
            partition, offset = m.partition(), m.offset()
            if partition in blocked:
                continue
            vendor_id = vendor_of(m)
            if vendor_id is not None and vendor_id not in self.known_vendors:
                first = self.waiting_since.setdefault((partition, offset), time.monotonic())
                if time.monotonic() - first < self.vendor_wait:
                    blocked.add(partition)          # keep the partition's order: wait here for the vendor
                    waiting[partition] = offset
                    continue
            self.waiting_since.pop((partition, offset), None)
            packets.append(m)

        def store(m):
            document = json.loads(m.value())
            invoice = document["invoice"]
            if invoice["vendor_id"] not in self.known_vendors:
                raise LookupError(f"vendor {invoice['vendor_id']} is not known after {self.vendor_wait:.0f} s")
            for table, key, records in (("purchase_orders", "po_id", [document.get("po")]),
                                        ("goods_receipts", "grn_id", [document.get("grn")]),
                                        ("invoices", "invoice_id", [invoice]),
                                        ("approval_logs", "log_id", document.get("approvals") or [])):
                db.upsert_records(self.conn, table, key, [r for r in records if r])
            return "received", invoice["invoice_id"], None

        done = self._each(packets, store)
        received = [(i, m) for i, (m, outcome, _, _) in enumerate(done) if outcome == "received"]
        transactions = db.extract_arrived(self.conn, [done[i][2] for i, _ in received])
        model = getattr(self.client, "model", None)
        for (i, m), txn in zip(received, transactions):
            state = self._audit(txn, model)
            if state is None:
                done[i] = (m, "error", f"audit of {txn['invoice']['invoice_id']} failed; see the worker's log", None)
                continue
            pack, result_id = state["audit_pack"], state["result_id"]
            detail = f"{pack['route']}, {len(pack['flags'])} finding(s)"
            again = [x for x in self._completed_group(state)
                     if self._audit(db.extract_one(self.conn, x), model, again=True)]
            if again:
                detail += "; completed a same-day group, audited again: " + ", ".join(again)
            done[i] = (m, "audited", detail, result_id)
        # E-mails that arrived before these invoices are linked to them now; the lock is taken last, so that it is
        # held only until the batch commits and the invoice workers do not wait for each other's audits.
        emails.lock_linking(self.conn)
        emails.link_waiting(self.conn, [json.loads(m.value())["invoice"].get("invoice_number", "") for _, m in received])
        return done, waiting

    def _audit(self, txn: dict | None, model: str | None, again: bool = False) -> dict | None:
        """Audit one invoice and store the result (in a savepoint); the final state with its result id, or None.
        ``again``: an invoice audited again because a later one completed its group; it goes to a run of its own."""
        if txn is None:
            return None
        version = db.version_in_force(self.timeline, txn["invoice"].get("date"))
        policy, graph, citations = self._governing(version)
        run_id = self._run(version, again, txn["invoice"]["invoice_id"])
        self._begin()
        self.conn.execute("SAVEPOINT audit")
        try:
            state = graph.invoke({"txn": txn})
            state["result_id"] = store_result(self.conn, run_id, state, self.config, policy, model,
                                              citations, self.sample_rate)
            self.conn.execute("RELEASE SAVEPOINT audit")
            return state
        except Exception as error:      # noqa: BLE001 - the invoice is kept; its audit failure is logged
            self.conn.execute("ROLLBACK TO SAVEPOINT audit")
            self.conn.execute("RELEASE SAVEPOINT audit")
            log.warning("%s: audit of %s failed: %s", self.topic, txn["invoice"]["invoice_id"], error)
            return None

    def _completed_group(self, state: dict) -> list[str]:
        """The earlier invoices of the same vendor and day that an over-the-limit finding of this invoice names
        and whose latest result does not have that finding: they were audited before the group was complete."""
        named = sorted({e["field"].split(".")[1] for f in state["flags"] if f.get("control") == "same_day_splitting"
                        for e in f["evidence"] if e["field"].startswith("history.")})
        if not named:
            return []
        clause = next(f["clause"] for f in state["flags"] if f.get("control") == "same_day_splitting")
        flagged = {r[0] for r in self.conn.execute(
            "SELECT l.invoice_id FROM latest_results l JOIN audit_flags f ON f.result_id = l.result_id "
            f"WHERE f.status = 'kept' AND f.clause = ? AND l.invoice_id IN ({', '.join('?' for _ in named)})",
            [clause, *named]).fetchall()}
        return [x for x in named if x not in flagged]

    def _read_timeline(self) -> None:
        """Each invoice is audited under the policy version in force on its date (``db.policy_timeline``). When the
        compliance topic adopts or activates a version, the timeline changes and the worker follows it."""
        timeline = db.policy_timeline(self.conn)
        if not timeline:
            raise StreamUnavailable("no active policy version in the database; run `python -m auditiq setup` first")
        if timeline == self.timeline:
            return
        self._finish_runs()
        self.timeline, self.governing = timeline, {}

    def _governing(self, version: str) -> tuple:
        """The policy, the audit graph and the citations of a version, built once per version."""
        if version not in self.governing:
            policy = db.read_policy(self.conn, version)
            self.governing[version] = (policy, build_graph(self.config, policy, self.client),
                                       clause_citations(self.conn, version))
        return self.governing[version]

    def _run(self, version: str, again: bool, invoice_id: str) -> int:
        """The run a result goes to: one per policy version. A run holds one result per invoice: an invoice that is
        already in the run (it was published twice) starts a new one. The run's start is committed with the batch,
        not before it."""
        key = (version, again)
        run_id = self.runs.get(key)
        if run_id is not None and self.conn.scalar(
                "SELECT 1 FROM audit_results WHERE run_id = ? AND invoice_id = ?", (run_id, invoice_id)):
            self.conn.execute("UPDATE audit_runs SET finished_at = ? WHERE run_id = ?", (db.now(), run_id))
            run_id = None
        if run_id is None:
            note = f"Kafka worker {socket.gethostname()}:{os.getpid()} on {self.topic}" + (
                ": invoices audited again when a later invoice completed their same-day group" if again else "")
            run_id = self.conn.insert(
                "INSERT INTO audit_runs (configuration, policy_version, model, prompt_hash, note, started_at) "
                "VALUES (?, ?, ?, ?, ?, ?)", (self.config.name, version, getattr(self.client, "model", None),
                                              prompts.prompt_hash() if self.config.agents != "none" else None, note,
                                              db.now()), "run_id")
            self.runs[key] = run_id
            self.new_runs.add(key)
        return run_id

    def _finish_runs(self) -> None:
        for run_id in self.runs.values():
            db.finish_run(self.conn, run_id)
        self.runs = {}


# ------------------------------------------------------------------ status
def status(settings: StreamSettings, conn: db.Database, timeout: float = 10.0) -> list[dict]:
    """Per topic: partitions, messages in the topic, messages the workers have processed, lag, and outcomes."""
    from confluent_kafka import Consumer, TopicPartition
    topics = _cluster_topics(settings, timeout)
    probe = Consumer(settings.client(**{"group.id": f"{settings.prefix}-status", "enable.auto.commit": False}))
    out = []
    try:
        for kind in KINDS:
            topic = settings.topic(kind)
            partitions = sorted(topics[topic].partitions) if topic in topics else []
            ends = {p: probe.get_watermark_offsets(TopicPartition(topic, p), timeout=timeout)[1] for p in partitions}
            stored = dict(conn.execute("SELECT partition_no, next_offset FROM stream_offsets WHERE consumer_group = ? "
                                       "AND topic = ?", (settings.group(kind), topic)).fetchall())
            outcomes = dict(conn.execute("SELECT outcome, COUNT(*) FROM stream_log WHERE topic = ? GROUP BY outcome",
                                         (topic,)).fetchall())
            out.append({"kind": kind, "topic": topic, "partitions": len(partitions),
                        "messages": sum(ends.values()),
                        "processed": sum(int(stored.get(p, 0)) for p in partitions),
                        "lag": sum(max(0, ends[p] - int(stored.get(p, 0))) for p in partitions),
                        "outcomes": {k: int(v) for k, v in outcomes.items()}})
    finally:
        probe.close()
    return out


# ------------------------------------------------------------------ the console
def sources(root: Path) -> dict:
    """What can be published from the server: the generated ledgers under data/, the mailboxes under .auditiq/
    and the policy documents under policy/pdf/."""
    ledgers = []
    for folder in sorted((Path(root) / "data").glob("*")):
        if not (folder / "invoices.csv").exists():
            continue
        manifest = folder / "manifest.json"
        counts = json.loads(manifest.read_text(encoding="utf-8")).get("counts", {}) if manifest.exists() else {}
        ledgers.append({"name": folder.name, "invoices": counts.get("invoices"), "vendors": counts.get("vendors")})
    mailboxes = [{"name": p.name, "bytes": p.stat().st_size} for p in sorted((Path(root) / ".auditiq").glob("*.mbox"))]
    policies = [{"name": p.name, "bytes": p.stat().st_size} for p in sorted((Path(root) / "policy" / "pdf").glob("*.pdf"))]
    return {"ledgers": ledgers, "mailboxes": mailboxes, "policies": policies}


def ledger_clash(conn: db.Database, dataset: Path, limit: int | None = None) -> int:
    """How many invoices of the store publishing this ledger (its first ``limit``, as ``publish_ledger`` sends
    them) would replace with different ones: same invoice number, another vendor, date or amount. The generated
    ledgers reuse their invoice numbers, so another ledger would silently overwrite the store's; publishing the
    store's own ledger again replaces nothing."""
    held = pd.DataFrame(conn.execute("SELECT invoice_id, vendor_id, CAST(date AS TEXT), amount FROM invoices").fetchall(),
                        columns=["invoice_id", "vendor_id", "date", "amount"])
    if held.empty:
        return 0
    ledger = pd.read_csv(Path(dataset) / "invoices.csv", usecols=["invoice_id", "vendor_id", "date", "amount"],
                         dtype=str, keep_default_na=False).sort_values(["date", "invoice_id"])
    if limit is not None:
        ledger = ledger.head(limit)
    both = ledger.merge(held, on="invoice_id", suffixes=("", "_held"))
    if both.empty:
        return 0
    amount = pd.to_numeric(both["amount"], errors="coerce").astype(float)
    amount_held = pd.to_numeric(both["amount_held"].astype(str), errors="coerce").astype(float)
    differs = ((both["vendor_id"] != both["vendor_id_held"]) | (both["date"].str[:10] != both["date_held"].astype(str).str[:10])
               | ~((amount - amount_held).abs() <= 0.005))
    return int(differs.sum())


def source_path(root: Path, source: str, name: str) -> Path:
    """The file or folder of a source listed by ``sources``; ValueError for anything else."""
    listed = sources(root)
    key = {"ledger": "ledgers", "mailbox": "mailboxes", "policy": "policies"}[source]
    if name not in {x["name"] for x in listed[key]}:
        raise ValueError(f"no {source} named {name!r}")
    folder = {"ledger": Path(root) / "data", "mailbox": Path(root) / ".auditiq", "policy": Path(root) / "policy" / "pdf"}
    return folder[source] / name


def _preview(kind: str, value: bytes | None) -> dict:
    """What a message carries, short enough to show: the fields that identify it, not its whole body."""
    if not value:
        return {}
    if kind == "email":
        message = email_parser.message_from_bytes(value)
        return {"from": message.get("From"), "subject": message.get("Subject"), "date": message.get("Date")}
    try:
        doc = json.loads(value)
    except ValueError:
        return {"bytes": len(value)}
    if kind == "invoice":
        inv = doc.get("invoice", {})
        return {"invoice_id": inv.get("invoice_id"), "vendor_id": inv.get("vendor_id"), "date": inv.get("date"),
                "amount": inv.get("amount"), "po": (doc.get("po") or {}).get("po_id"),
                "grn": (doc.get("grn") or {}).get("grn_id"), "approvals": len(doc.get("approvals") or [])}
    if kind == "vendor":
        v = doc.get("vendor", {})
        return {"vendor_id": v.get("vendor_id"), "vendor_name": v.get("vendor_name"), "category": v.get("vendor_category"),
                "gstin_status": v.get("gstin_status")}
    return {"file": doc.get("file"), "activate": doc.get("activate"), "pdf_bytes": len(doc.get("pdf") or "") * 3 // 4}


def peek(settings: StreamSettings, kind: str, n: int = 10, timeout: float = 5.0) -> list[dict]:
    """The newest ``n`` messages of a topic (from the end of each partition), without joining any worker's group."""
    from confluent_kafka import Consumer, TopicPartition
    topic = settings.topic(kind)
    topics = _cluster_topics(settings, timeout)
    if topic not in topics:
        return []
    consumer = Consumer(settings.client(**{"group.id": f"{settings.prefix}-console", "enable.auto.commit": False}))
    out: list[dict] = []
    try:
        assigned, want = [], 0
        for p in sorted(topics[topic].partitions):
            low, high = consumer.get_watermark_offsets(TopicPartition(topic, p), timeout=timeout)
            if high > low:
                start = max(low, high - n)
                assigned.append(TopicPartition(topic, p, start))
                want += high - start
        if not assigned:
            return []
        consumer.assign(assigned)
        deadline = time.time() + timeout
        while len(out) < want and time.time() < deadline:
            message = consumer.poll(0.5)
            if message is None or message.error():
                continue
            out.append({"partition": message.partition(), "offset": message.offset(),
                        "key": (message.key() or b"").decode("utf-8", errors="replace"),
                        "timestamp": message.timestamp()[1], "bytes": len(message.value() or b""),
                        "preview": _preview(kind, message.value())})
    finally:
        consumer.close()
    out.sort(key=lambda m: (m["timestamp"] or 0, m["offset"]), reverse=True)
    return out[:n]


def recent_log(conn: db.Database, limit: int = 60, topic: str | None = None) -> list[dict]:
    """The newest messages the workers have processed, with what became of each and how long it took."""
    where, params = ("WHERE topic = ? ", [topic]) if topic else ("", [])
    rows = conn.execute(
        "SELECT topic, partition_no, kafka_offset, doc_key, produced_ms, processed_ms, outcome, detail, result_id "
        f"FROM stream_log {where}ORDER BY processed_ms DESC, kafka_offset DESC LIMIT ?", (*params, limit)).fetchall()
    out = []
    for r in rows:
        row = dict(zip(r.keys(), r))
        produced, processed = row["produced_ms"], row["processed_ms"]
        row["latency_ms"] = processed - produced if produced and processed else None
        out.append(row)
    return out
