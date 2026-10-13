"""Shared fixtures.

Datasets: the tests do not read the datasets under data/. They generate their
own, at the size of the original benchmark specification, so that they are fast
and do not depend on what has been generated on a machine.

Stores: every test that needs a database gets a new, empty one. Tests marked
with the `backend` fixture run once on SQLite and once on PostgreSQL. The
PostgreSQL run needs a test database, named in AUDITIQ_TEST_DATABASE_URL (in
the environment or in .env; `python scripts/pg_local.py init` sets it). Each
test works in its own schema of that database, dropped afterwards. Without a
reachable test database the PostgreSQL runs are skipped.

The tests never read .env for the application's own settings, so they cannot
touch a developer's database or call a model.
"""
from __future__ import annotations

import os
import uuid
from pathlib import Path

os.environ["AUDITIQ_NO_DOTENV"] = "1"          # before the application is imported

import pytest  # noqa: E402
from dotenv import dotenv_values  # noqa: E402

from auditiq import db, policy_ingest  # noqa: E402
from auditiq.policy import load_policy  # noqa: E402
from auditiq.policy_pdf import make_sample_pdfs  # noqa: E402
from auditiq_bench.__main__ import Profile, generate  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
APPLICATION_SETTINGS = ("AUDITIQ_DATABASE_URL", "AUDITIQ_DB", "AUDITIQ_LLM_BASE_URL", "AUDITIQ_LLM_MODEL",
                        "AUDITIQ_LLM_API_KEY", "AUDITIQ_LLM_CONTEXT", "AUDITIQ_EMBED_MODEL", "AUDITIQ_EMBED_BASE_URL")
_TEST_URL = os.environ.get("AUDITIQ_TEST_DATABASE_URL") or dotenv_values(ROOT / ".env").get("AUDITIQ_TEST_DATABASE_URL")
_reachable: bool | None = None


def postgres_url() -> str | None:
    """The test database's URL if it is configured and answers, else None."""
    global _reachable
    if not _TEST_URL:
        return None
    if _reachable is None:
        try:
            import psycopg
            with psycopg.connect(_TEST_URL, connect_timeout=3):
                _reachable = True
        except Exception:
            _reachable = False
    return _TEST_URL if _reachable else None


@pytest.fixture(autouse=True)
def no_application_settings(monkeypatch):
    """A developer's exported settings must not leak into a test."""
    for name in APPLICATION_SETTINGS:
        monkeypatch.delenv(name, raising=False)


@pytest.fixture(scope="session")
def small_dataset(tmp_path_factory) -> Path:
    """A ledger of 1,200 invoices from 60 vendors: 420 anomalous, 120 hard negatives, 660 clean."""
    out = tmp_path_factory.mktemp("datasets")
    generate(Profile("small_seed_7", "benchmark", 7, 1200, 60, "Test ledger.", approver_counts=(8, 5, 3, 1)), out)
    return out / "small_seed_7"


@pytest.fixture(scope="session")
def boundary_dataset(tmp_path_factory) -> Path:
    """The 150 policy-swap boundary invoices alone: anomalous under v2.5, clean under v2.6."""
    out = tmp_path_factory.mktemp("datasets")
    generate(Profile("swap_seed_11", "policy_swap", 11, 150, 60, "Test policy-swap ledger.", eval_ordinary=0,
                     approver_counts=(8, 5, 3, 1)), out)
    return out / "swap_seed_11"


@pytest.fixture(scope="session")
def pdfs(tmp_path_factory) -> list[Path]:
    return make_sample_pdfs(tmp_path_factory.mktemp("pdf"))


@pytest.fixture()
def make_store(tmp_path):
    """make_store(backend) returns the target of a new, empty store."""
    schemas, count = [], 0

    def make(backend: str = "sqlite") -> str:
        nonlocal count
        count += 1
        if backend == "sqlite":
            return str(tmp_path / f"store_{count}.db")
        url = postgres_url()
        if url is None:
            pytest.skip("no reachable test PostgreSQL (AUDITIQ_TEST_DATABASE_URL)")
        import psycopg
        schema = f"t_{uuid.uuid4().hex[:16]}"
        with psycopg.connect(url, autocommit=True) as admin:
            admin.execute(f"CREATE SCHEMA {schema}")
        schemas.append(schema)
        return f"{url}{'&' if '?' in url else '?'}options=-csearch_path%3D{schema}"

    yield make
    if schemas:
        import psycopg
        with psycopg.connect(postgres_url(), autocommit=True) as admin:
            for schema in schemas:
                admin.execute(f"DROP SCHEMA IF EXISTS {schema} CASCADE")


@pytest.fixture(params=["sqlite", "postgres"])
def backend(request) -> str:
    return request.param


def fill(target: str, dataset: Path, documents: list[Path] = ()) -> str:
    conn = db.connect(target)
    db.load_dataset(conn, dataset)
    db.store_policy(conn, load_policy("2.5"), active=True)
    db.store_policy(conn, load_policy("2.6"))
    for pdf in documents:
        policy_ingest.ingest(conn, pdf)
    conn.close()
    return target


@pytest.fixture()
def ledger(backend, make_store, small_dataset) -> str:
    """Target of a store with the small ledger and both policy versions, on each backend."""
    return fill(make_store(backend), small_dataset)


@pytest.fixture()
def conn(ledger):
    connection = db.connect(ledger)
    yield connection
    connection.close()


@pytest.fixture()
def library(backend, make_store, small_dataset, pdfs) -> str:
    """Like `ledger`, with the three sample policy PDFs ingested."""
    return fill(make_store(backend), small_dataset, pdfs)


@pytest.fixture()
def lib(library):
    connection = db.connect(library)
    yield connection
    connection.close()


@pytest.fixture()
def sqlite_library(make_store, small_dataset, pdfs) -> str:
    """SQLite only: for tests of things that do not depend on the backend."""
    return fill(make_store("sqlite"), small_dataset, pdfs)
