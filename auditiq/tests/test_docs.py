"""The documentation that is generated from the code stays in step with the code."""
from __future__ import annotations

import pytest

from auditiq import datadict, db
from auditiq.extraction import HISTORY_FIELDS
from auditiq_bench import overview
from auditiq_bench.taxonomy import CLASSES


def test_every_table_and_column_is_described():
    for backend in ("sqlite", "postgres"):
        declared = datadict.schema_columns(backend)
        assert list(declared) == db.ALL_TABLES and set(datadict.TABLES) == set(db.ALL_TABLES)
        for table, columns in declared.items():
            assert [c for c, _ in columns] == list(datadict.TABLES[table]["columns"]), table
            assert all(text.strip().endswith((".", "`")) for text in datadict.TABLES[table]["columns"].values()), table
    grouped = [name for _, _, names in datadict.GROUPS for name in names]
    assert grouped == db.ALL_TABLES


def test_the_dictionary_describes_the_database_as_it_is_created(conn):
    declared = datadict.schema_columns("postgres" if conn.backend == "postgres" else "sqlite")
    for table in db.ALL_TABLES:
        assert list(conn.columns(table)) == [c for c, _ in declared[table]], table
    for view, columns in datadict.view_columns().items():
        cursor = conn.execute(f"SELECT * FROM {view} LIMIT 0")
        assert [d[0] for d in cursor.description] == columns, view
    assert set(datadict.view_columns()) == set(db.VIEWS) == set(datadict.VIEW_NOTES)


def test_audited_columns_are_the_columns_extraction_reads():
    for table, fields in datadict.AUDITED.items():
        assert set(fields) <= set(datadict.TABLES[table]["columns"]), table
    assert set(HISTORY_FIELDS) <= set(datadict.AUDITED["invoices"])      # the vendor history shows nothing more


def test_the_generated_data_dictionary_is_up_to_date():
    assert datadict.DOC.read_text(encoding="utf-8") == datadict.render(), "run: python -m auditiq.datadict"


def test_the_generated_api_reference_is_up_to_date_and_documents_every_endpoint():
    from auditiq import apidoc

    assert apidoc.DOC.read_text(encoding="utf-8") == apidoc.render(), "run: python -m auditiq.apidoc"
    found = apidoc.endpoints()
    assert len(found) == 22 and all(e["doc"] for e in found), [e["path"] for e in found if not e["doc"]]
    open_ = {e["path"] for e in found if not e["protected"]}
    assert open_ == {"/api/health", "/api/pipeline"}           # everything else needs the token
    ledger = next(e for e in found if e["path"] == "/api/ledger")
    assert {202, 409, 413, 415}.issubset(ledger["codes"]) and [f["name"] for f in ledger["form"]] == ["file", "replace"]


def test_every_anomaly_class_has_an_injection_note():
    assert list(overview.INJECTION) == list(CLASSES)
    assert {p.kind for p in overview.PROFILES} == set(overview.USE)


def test_the_generated_datasets_overview_is_up_to_date():
    data = overview.PROJECT_ROOT / "data"
    if len(overview.manifests(data)) < len(overview.PROFILES):
        pytest.skip("the datasets have not been generated here")
    assert overview.verify(data) == []
    assert overview.DOC.read_text(encoding="utf-8") == overview.render(data), "run: python -m auditiq_bench.overview"
