"""Loading a ledger from a workbook or a zip archive: the same ledger as the CSV files, or a refusal with reasons."""
from __future__ import annotations

import zipfile
from pathlib import Path

import pandas as pd
import pytest

from auditiq import db, ledger_import, service
from auditiq.graph import PRESETS
from auditiq.policy import load_policy


@pytest.fixture()
def store(tmp_path):
    conn = db.connect(str(tmp_path / "store.db"))
    yield conn
    conn.close()


def zip_of(folder: Path, out: Path, inside: str = "ledger") -> Path:
    with zipfile.ZipFile(out, "w") as archive:
        for csv in folder.glob("*.csv"):
            archive.write(csv, f"{inside}/{csv.name}")
    return out


def findings(conn: db.Database) -> dict[str, list[str]]:
    rows = conn.execute("SELECT r.invoice_id, f.clause, f.message FROM audit_flags f JOIN audit_results r "
                        "ON r.result_id = f.result_id ORDER BY r.invoice_id, f.clause, f.message").fetchall()
    out: dict[str, list[str]] = {}
    for invoice_id, clause, message in rows:
        out.setdefault(invoice_id, []).append(f"{clause}: {message}")
    return out


def test_a_workbook_and_a_zip_archive_hold_the_same_ledger_as_the_csv_files(small_dataset, tmp_path, store):
    folder = ledger_import.read(small_dataset, store)
    book = ledger_import.read(ledger_import.export_workbook(small_dataset, tmp_path / "ledger.xlsx"), store)
    archive = ledger_import.read(zip_of(small_dataset, tmp_path / "ledger.zip"), store)
    assert folder.usable and book.usable and archive.usable, folder.problems + book.problems + archive.problems
    assert set(folder.frames) == set(ledger_import.TABLES) | {"labels"}
    for name, frame in folder.frames.items():
        for other in (book, archive):
            pd.testing.assert_frame_equal(frame, other.frames[name][frame.columns], check_dtype=False)


def test_a_workbook_typed_by_hand_is_audited_like_the_csv_ledger(small_dataset, tmp_path, store):
    """Real spreadsheet cells (dates, numbers, true/false) are read as the CSV text they stand for."""
    typed = {}
    for name, frame in ledger_import.read(small_dataset, store).frames.items():
        kinds = store.columns("benchmark_labels" if name == "labels" else name)
        frame = frame.copy().astype(object)
        for column, kind in kinds.items():
            filled = frame[column] != ""
            if column in db.BOOLEAN_COLUMNS:
                frame.loc[filled, column] = frame.loc[filled, column].str.lower().isin(["true", "t", "1"])
            elif kind in ("number", "integer"):
                frame.loc[filled, column] = frame.loc[filled, column].astype(float)
            elif column == "date" or column.endswith("_date") or column == "timestamp":
                frame.loc[filled, column] = [t.to_pydatetime() for t in pd.to_datetime(frame.loc[filled, column])]
            frame.loc[~filled, column] = None
        typed[name] = frame
    path = tmp_path / "typed.xlsx"
    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        for name, frame in typed.items():
            frame.to_excel(writer, sheet_name=name, index=False)

    outcomes = []
    for source in (small_dataset, path):
        conn = db.connect(str(tmp_path / f"{Path(source).stem}.db"))
        ledger = ledger_import.read(source, conn)
        assert ledger.usable, ledger.problems
        ledger_import.load(conn, ledger)
        db.store_policy(conn, load_policy("2.5"), active=True)
        service.audit_invoices(conn, PRESETS["C1"], db.read_policy(conn), None, db.invoice_ids(conn))
        outcomes.append(findings(conn))
        conn.close()
    assert outcomes[0] == outcomes[1] and outcomes[0]


def test_a_defective_ledger_is_refused_with_its_reasons_and_nothing_is_replaced(small_dataset, tmp_path, store):
    db.load_dataset(store, small_dataset)
    before = store.execute("SELECT COUNT(*) FROM invoices").fetchone()[0]
    frames = ledger_import.read(small_dataset, store).frames
    frames.pop("approval_logs")
    frames["goods_receipts"] = frames["goods_receipts"].drop(columns=["receipt_date"])
    invoices = frames["invoices"].copy()
    invoices.loc[1, "invoice_id"] = invoices.loc[0, "invoice_id"]
    invoices.loc[2, "amount"] = "twelve thousand"
    invoices.loc[3, "date"] = "03/04/2025"
    frames["invoices"] = invoices
    folder = tmp_path / "defective"
    folder.mkdir()
    for name, frame in frames.items():
        frame.to_csv(folder / f"{name}.csv", index=False)

    ledger = ledger_import.read(zip_of(folder, tmp_path / "defective.zip"), store)
    assert not ledger.usable
    text = "\n".join(ledger.problems)
    assert "the table approval_logs is missing" in text
    assert "the table goods_receipts lacks the column(s) receipt_date" in text
    assert f"invoices: invoice_id is not unique ({invoices.loc[0, 'invoice_id']})" in text
    assert "invoices.amount: not a number (twelve thousand)" in text
    assert "invoices.date: not a date" in text and "03/04/2025" in text
    with pytest.raises(ValueError):
        ledger_import.load(store, ledger)
    assert store.execute("SELECT COUNT(*) FROM invoices").fetchone()[0] == before


def test_a_vendor_that_is_not_in_the_ledger_is_refused_but_a_missing_purchase_order_is_an_exception(
        small_dataset, tmp_path, store):
    frames = ledger_import.read(small_dataset, store).frames
    invoices = frames["invoices"].copy()
    invoices.loc[0, "po_id"] = "PO-NOT-ISSUED"          # rule 2.1.3 reports this; the file is still sound
    assert not ledger_import.check({**frames, "invoices": invoices}, store)
    invoices.loc[1, "vendor_id"] = "VEND-UNKNOWN"
    problems = ledger_import.check({**frames, "invoices": invoices}, store)
    assert problems == ["invoices.vendor_id names records that are not in vendor_master (VEND-UNKNOWN)"]


def test_a_file_that_is_not_a_ledger_is_refused(tmp_path, store):
    text = tmp_path / "notes.txt"
    text.write_text("not a ledger", encoding="utf-8")
    assert ledger_import.read(text, store).problems == [
        "give a folder of CSV files, a .zip archive of CSV files or an .xlsx workbook"]
    broken = tmp_path / "broken.zip"
    broken.write_bytes(b"PK\x03\x04 not really a zip")
    assert ledger_import.read(broken, store).problems[0].startswith("the file cannot be read")
