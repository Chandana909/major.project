"""The Kafka ingestion layer (auditiq/stream.py), the e-mails it carries (auditiq/emails.py) and the synthetic
vendor correspondence (auditiq_bench/correspondence.py).

The tests that stream run against a real broker, named in AUDITIQ_TEST_KAFKA_BOOTSTRAP (in the environment or in
.env; `python scripts/kafka_local.py init` sets it, and CI runs a broker in a service container). Each test has
topics of its own (a fresh prefix), so tests never see each other's messages. Without a broker that answers, those
tests are skipped; the others need none.
"""
from __future__ import annotations

import os
import shutil
import socket
import threading
import time
import uuid
from pathlib import Path

import pandas as pd
import pytest
from dotenv import dotenv_values
from fastapi.testclient import TestClient

from auditiq import api, cli, db, emails, policy_ingest, service, stream
from auditiq.graph import preset
from auditiq.policy import load_policy
from auditiq_bench import correspondence

ROOT = Path(__file__).resolve().parents[1]
_BOOTSTRAP = (os.environ.get("AUDITIQ_TEST_KAFKA_BOOTSTRAP")
              or dotenv_values(ROOT / ".env").get("AUDITIQ_TEST_KAFKA_BOOTSTRAP"))


def broker() -> str:
    # CI sets AUDITIQ_REQUIRE_KAFKA: there, a missing broker fails the tests instead of skipping them.
    missing = pytest.fail if os.environ.get("AUDITIQ_REQUIRE_KAFKA") else pytest.skip
    if not _BOOTSTRAP:
        missing("no test broker (AUDITIQ_TEST_KAFKA_BOOTSTRAP)")
    host, _, port = _BOOTSTRAP.rpartition(":")
    with socket.socket() as s:
        s.settimeout(2)
        if s.connect_ex((host or "127.0.0.1", int(port))):
            missing(f"the test broker at {_BOOTSTRAP} does not answer")
    return _BOOTSTRAP


@pytest.fixture()
def settings() -> stream.StreamSettings:
    topics = stream.StreamSettings(broker(), f"test-{uuid.uuid4().hex[:10]}", partitions=3)
    stream.ensure_topics(topics)
    return topics


def empty_store(target: str, pdfs: list[Path] = (), versions: tuple[str, ...] = ("2.5", "2.6")) -> str:
    """A store with the policy versions (the first active) and documents, and no ledger: it comes by stream."""
    conn = db.connect(target)
    for version in versions:
        db.store_policy(conn, load_policy(version), active=version == versions[0])
    for pdf in pdfs:
        policy_ingest.ingest(conn, pdf)
    conn.commit()
    conn.close()
    return target


def work(settings: stream.StreamSettings, target: str, kind: str, idle_exit: float = 3.0, **options) -> dict:
    conn = db.connect(target)
    try:
        return stream.Worker(settings, conn, kind, **options).run(idle_exit=idle_exit)
    finally:
        conn.close()


def kept_findings(target: str) -> dict[str, frozenset]:
    conn = db.connect(target)
    try:
        latest = dict(conn.execute("SELECT invoice_id, result_id FROM latest_results").fetchall())
        flags: dict[int, set] = {}
        for result_id, clause in conn.execute("SELECT result_id, clause FROM audit_flags WHERE status = 'kept'"):
            flags.setdefault(int(result_id), set()).add(clause)
        return {i: frozenset(flags.get(int(r), ())) for i, r in latest.items()}
    finally:
        conn.close()


def publish(settings: stream.StreamSettings, dataset: Path | None = None, mbox: Path | None = None,
            limit: int | None = None) -> dict:
    publisher = stream.Publisher(settings)
    if dataset:
        stream.publish_ledger(publisher, dataset, limit=limit)
    if mbox:
        stream.publish_mailbox(publisher, mbox)
    return publisher.close()


# ------------------------------------------------------------------ without a broker
def test_another_ledger_with_the_same_invoice_numbers_would_replace_the_stores(ledger, small_dataset, tmp_path):
    conn = db.connect(ledger)
    try:
        assert stream.ledger_clash(conn, small_dataset) == 0                  # the store's own ledger: nothing changes
        other = tmp_path / "other"
        shutil.copytree(small_dataset, other)
        invoices = pd.read_csv(other / "invoices.csv", dtype=str, keep_default_na=False)
        first = invoices.sort_values(["date", "invoice_id"])["invoice_id"][:40]
        invoices.loc[invoices["invoice_id"].isin(list(first)[:3]), "amount"] = "1.00"
        invoices.to_csv(other / "invoices.csv", index=False)
        assert stream.ledger_clash(conn, other) == 3
        assert stream.ledger_clash(conn, other, limit=40) == 3 and stream.ledger_clash(conn, other, limit=0) == 0
    finally:
        conn.close()

def test_an_invoice_on_the_stream_is_audited_against_the_invoices_before_it(ledger):
    conn = db.connect(ledger)
    ids = db.invoice_ids(conn)
    arrived, batch = db.extract_arrived(conn, ids), db.extract_many(conn, ids)
    for a, b in zip(arrived, batch):
        assert {k: a[k] for k in ("invoice", "po", "grn", "vendor", "approvals")} == \
               {k: b[k] for k in ("invoice", "po", "grn", "vendor", "approvals")}
        own = (a["invoice"]["date"], a["invoice"]["invoice_id"])
        assert all((h["date"], h["invoice_id"]) < own for h in a["vendor_history"])
        assert {h["invoice_id"] for h in a["vendor_history"]} == {h["invoice_id"] for h in b["vendor_history"]
                                                                  if (h["date"], h["invoice_id"]) < own}
    conn.close()


def test_feed_records_are_stored_typed_and_updated_in_place(tmp_path):
    conn = db.connect(tmp_path / "s.db")
    record = {"vendor_id": "VEND9001", "vendor_name": "Test Ltd", "official_gstin": "", "pan_number": "",
              "vendor_category": "MRO", "city": "Pune", "state": "Maharashtra", "country": "India",
              "gstin_status": "Active", "kyc_status": "Verified", "is_active": "True", "blacklisted": "False",
              "blacklist_status": "False"}
    db.upsert_records(conn, "vendor_master", "vendor_id", [record])
    db.upsert_records(conn, "vendor_master", "vendor_id", [{**record, "city": "Nashik", "blacklisted": "True"}])
    rows = conn.execute("SELECT city, blacklisted, is_active FROM vendor_master").fetchall()
    assert [tuple(r) for r in rows] == [("Nashik", 1, 1)]
    conn.close()


def test_the_correspondence_is_seeded_labelled_and_addressed_to_reserved_domains(small_dataset):
    messages, labels = correspondence.generate(small_dataset, seed=3)
    again, _ = correspondence.generate(small_dataset, seed=3)
    assert [m["Message-ID"] for m in messages] == [m["Message-ID"] for m in again]
    assert len(messages) == len(labels) > 100
    assert {label["category"] for label in labels} >= {"invoice_submission", "payment_reminder"}
    assert all(m["From"].endswith(".example") and m["To"].endswith(".example") for m in messages)
    for message, label in zip(messages, labels):
        if label["suspicious"]:         # a look-alike domain, pressing for payment to a new account
            assert label["category"] == "bank_change" and "URGENT" in message["Subject"]


def test_an_email_that_arrives_before_its_invoice_is_linked_when_the_invoice_does(tmp_path, small_dataset):
    messages, labels = correspondence.generate(small_dataset, seed=3)
    conn = db.connect(tmp_path / "s.db")
    for message in messages:
        mail = emails.store(conn, message.as_bytes())
        assert mail["invoice_id"] is None and mail["mentions"]          # no invoice in the store yet
    db.load_dataset(conn, small_dataset, replace=False)
    numbers = [r[0] for r in conn.execute("SELECT invoice_number FROM invoices").fetchall()]
    assert emails.link_waiting(conn, numbers) == len(messages)
    linked = dict(conn.execute("SELECT message_id, invoice_id FROM emails").fetchall())
    right = sum(linked[label["message_id"]] == label["invoice_id"] for label in labels)
    assert right >= 0.99 * len(labels)
    assert emails.for_invoice(conn, labels[0]["invoice_id"])
    conn.close()


def test_stream_commands_say_how_to_get_a_broker(monkeypatch, capsys):
    monkeypatch.delenv("AUDITIQ_KAFKA_BOOTSTRAP", raising=False)
    assert cli.main(["stream", "status"]) == 2
    assert "kafka_local.py start" in capsys.readouterr().err


# ------------------------------------------------------------------ with a broker
def test_a_ledger_streams_into_the_store_with_the_findings_of_the_batch_audit(settings, backend, make_store,
                                                                            small_dataset, ledger, tmp_path):
    messages, labels = correspondence.generate(small_dataset, seed=3)
    mbox = tmp_path / "mail.mbox"
    correspondence.write(messages, labels, mbox)
    sent = publish(settings, small_dataset, mbox)
    assert sent["invoice"] == 1200 and sent["vendor"] == 60 and sent["email"] == len(messages)

    target = empty_store(make_store(backend))
    assert work(settings, target, "vendor") == {"stored": 60}
    assert work(settings, target, "invoice") == {"audited": 1200}
    assert work(settings, target, "email") == {"stored": len(messages)}

    conn = db.connect(ledger)          # the batch audit of the same ledger
    service.audit_invoices(conn, preset("C1"), db.read_policy(conn), None, db.invoice_ids(conn))
    conn.close()
    assert kept_findings(target) == kept_findings(ledger)

    conn = db.connect(target)
    linked = dict(conn.execute("SELECT message_id, invoice_id FROM emails").fetchall())
    assert sum(linked[label["message_id"]] == label["invoice_id"] for label in labels) >= 0.99 * len(labels)
    status = {row["kind"]: row for row in stream.status(settings, conn)}
    assert status["invoice"]["lag"] == 0 and status["invoice"]["processed"] == 1200
    assert status["invoice"]["outcomes"] == {"audited": 1200}
    results = conn.scalar("SELECT COUNT(*) FROM audit_results")
    conn.close()
    # Exactly once: a worker started again resumes from the offsets stored with the results and audits nothing.
    assert work(settings, target, "invoice", idle_exit=2) == {}
    conn = db.connect(target)
    assert conn.scalar("SELECT COUNT(*) FROM audit_results") == results
    conn.close()


def test_an_invoice_waits_for_its_vendor_on_the_other_topic(settings, make_store, small_dataset):
    publish(settings, small_dataset, limit=40)
    target = empty_store(make_store("sqlite"))
    outcome: dict = {}
    invoices = threading.Thread(target=lambda: outcome.update(work(settings, target, "invoice", idle_exit=6,
                                                                   vendor_wait=60)))
    invoices.start()                    # the invoices are read first and wait
    assert work(settings, target, "vendor") == {"stored": 60}
    invoices.join(timeout=120)
    assert outcome == {"audited": 40}


def test_an_invoice_whose_vendor_never_comes_is_logged_and_skipped(settings, make_store, small_dataset):
    publish(settings, small_dataset, limit=10)
    target = empty_store(make_store("sqlite"))
    assert work(settings, target, "invoice", idle_exit=4, vendor_wait=0.5) == {"error": 10}
    conn = db.connect(target)
    details = [r[0] for r in conn.execute("SELECT detail FROM stream_log WHERE outcome = 'error'").fetchall()]
    assert len(details) == 10 and all("is not known after" in d for d in details)
    conn.close()


def test_a_bad_message_is_logged_and_the_partition_goes_on(settings, make_store, small_dataset):
    publisher = stream.Publisher(settings)
    publisher.send("vendor", "x", b"not json")
    publisher.send("email", "y", b"no headers at all")
    publisher.close()
    publish(settings, small_dataset, limit=5)
    target = empty_store(make_store("sqlite"))
    assert work(settings, target, "vendor") == {"stored": 60, "error": 1}
    assert work(settings, target, "email") == {"error": 1}
    assert work(settings, target, "invoice") == {"audited": 5}


def test_a_policy_document_on_the_compliance_topic_becomes_the_version_the_workers_apply(
        settings, make_store, small_dataset, pdfs, tmp_path):
    sop_25 = next(p for p in pdfs if p.name.endswith("v2.5.pdf"))
    sop_26 = next(p for p in pdfs if p.name.endswith("v2.6.pdf"))
    review = next(p for p in pdfs if p.name.startswith("Audit_Review"))
    publisher = stream.Publisher(settings)
    stream.publish_policy(publisher, sop_25)                       # the active version's own document again
    stream.publish_policy(publisher, review, activate=True)       # not a policy the controls can execute
    publisher.close()
    target = empty_store(make_store("sqlite"), versions=("2.5",))
    assert work(settings, target, "compliance") == {"adopted": 1, "refused": 1}
    conn = db.connect(target)
    assert conn.scalar("SELECT version FROM company_policies WHERE is_active = 1") == "2.5"     # still active
    conn.close()
    publisher = stream.Publisher(settings)
    stream.publish_policy(publisher, sop_26, activate=True)
    publisher.close()
    assert work(settings, target, "compliance") == {"adopted": 1}
    # Twenty invoices, five of them dated after 2.6 took effect (1 April 2026): only those five fall under it.
    dataset = tmp_path / "later"
    shutil.copytree(small_dataset, dataset)
    invoices = pd.read_csv(dataset / "invoices.csv", dtype=str, keep_default_na=False)
    invoices = invoices.sort_values(["date", "invoice_id"]).head(20)
    later = set(invoices["invoice_id"][:5])
    invoices.loc[invoices["invoice_id"].isin(later), "date"] = "2026-04-15"
    invoices.to_csv(dataset / "invoices.csv", index=False)
    publish(settings, dataset)
    work(settings, target, "vendor")
    assert work(settings, target, "invoice") == {"audited": 20}
    conn = db.connect(target)
    assert conn.scalar("SELECT version FROM company_policies WHERE is_active = 1") == "2.6"
    versions = dict(conn.execute("SELECT invoice_id, policy_version FROM v_latest_results").fetchall())
    assert {i for i, v in versions.items() if v == "2.6"} == later and set(versions.values()) == {"2.5", "2.6"}
    log = dict(conn.execute("SELECT doc_key, detail FROM stream_log WHERE topic = ?",
                            (settings.topic("compliance"),)).fetchall())
    conn.close()
    assert log[sop_26.name] == "version 2.6, active"


def test_the_partitions_are_shared_by_the_workers_of_a_group(settings, make_store, small_dataset):
    """Two invoice workers at once (PostgreSQL, so that both can write): every invoice is audited exactly once."""
    publish(settings, small_dataset)
    target = empty_store(make_store("postgres"))
    work(settings, target, "vendor")
    outcomes: list[dict] = []
    workers = [threading.Thread(target=lambda: outcomes.append(work(settings, target, "invoice", idle_exit=5)))
               for _ in range(2)]
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join(timeout=300)
    assert sum(o.get("audited", 0) for o in outcomes) == 1200
    conn = db.connect(target)
    assert conn.scalar("SELECT COUNT(DISTINCT invoice_id) FROM latest_results") == 1200
    assert conn.scalar("SELECT COUNT(*) FROM stream_log WHERE outcome = 'audited'") == 1200
    conn.close()


def test_the_console_publishes_a_ledger_runs_the_workers_and_reads_the_topics(settings, make_store, small_dataset,
                                                                              tmp_path, monkeypatch):
    root = tmp_path / "root"
    shutil.copytree(small_dataset, root / "data" / "small")
    monkeypatch.setattr(api, "PROJECT_ROOT", root)
    monkeypatch.setenv("AUDITIQ_KAFKA_BOOTSTRAP", settings.bootstrap)
    monkeypatch.setenv("AUDITIQ_KAFKA_PREFIX", settings.prefix)
    monkeypatch.setenv("AUDITIQ_KAFKA_PARTITIONS", str(settings.partitions))
    client = TestClient(api.create_app(empty_store(make_store("sqlite")), token="", frontend=None))

    def wait(job: dict) -> dict:
        deadline = time.time() + 180
        while time.time() < deadline:
            state = client.get(f"/api/jobs/{job['id']}").json()
            if state["status"] in ("done", "failed"):
                return state
            time.sleep(0.2)
        raise AssertionError("the job did not finish")

    assert client.get("/api/system").json()["kafka"] == {"configured": True, "connected": True,
                                                         "bootstrap": settings.bootstrap, "prefix": settings.prefix}
    assert client.get("/api/stream/sources").json()["ledgers"] == [{"name": "small", "invoices": 1200, "vendors": 60}]
    assert client.post("/api/stream/publish", json={"source": "ledger", "name": "other"}).status_code == 404
    sent = wait(client.post("/api/stream/publish", json={"source": "ledger", "name": "small", "limit": 40}).json())
    assert sent["status"] == "done" and sent["result"]["sent"] == {"vendor": 60, "invoice": 40}
    peeked = client.get("/api/stream/peek", params={"kind": "invoice", "n": 5}).json()
    assert peeked["topic"] == settings.topic("invoice") and peeked["messages"]
    assert all(m["preview"]["invoice_id"].startswith("INV") and m["key"].startswith("VEND") for m in peeked["messages"])

    done = wait(client.post("/api/stream/work", json={"kinds": ["vendor", "invoice"], "idle_exit": 2}).json())
    assert done["status"] == "done" and done["result"]["counts"] == {"vendor": {"stored": 60}, "invoice": {"audited": 40}}
    other = root / "data" / "other"                     # another ledger with the same invoice numbers is refused
    shutil.copytree(small_dataset, other)
    invoices = pd.read_csv(other / "invoices.csv", dtype=str, keep_default_na=False)
    invoices["amount"] = "1.00"
    invoices.to_csv(other / "invoices.csv", index=False)
    refused = client.post("/api/stream/publish", json={"source": "ledger", "name": "other", "limit": 40})
    assert refused.status_code == 409 and "would replace 40 of its invoices" in refused.json()["detail"]
    log = client.get("/api/stream/log", params={"topic": settings.topic("invoice")}).json()["messages"]
    assert len(log) == 40 and all(r["outcome"] == "audited" and r["result_id"] for r in log)
    assert all(r["latency_ms"] is None or r["latency_ms"] >= 0 for r in log)
    topics = {t["kind"]: t for t in client.get("/api/stream").json()["topics"]}
    assert (topics["invoice"]["processed"], topics["invoice"]["lag"]) == (40, 0)
