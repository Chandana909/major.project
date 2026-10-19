"""Reading a ledger from a dataset folder, a zip archive of CSV files, or an Excel workbook.

A ledger is the five record tables of the data store: ``vendor_master``,
``purchase_orders``, ``goods_receipts``, ``invoices`` and ``approval_logs``,
optionally with ``labels`` (the answer key of a synthetic ledger). In a folder
or a zip archive each table is the CSV file of that name; in a workbook it is
the sheet of that name. Every column of the store must be present.

Before anything is replaced, the ledger is checked: every table and column is
there, every identifier is unique and filled, amounts and dates can be read,
and each reference the store enforces (a purchase order's, a goods receipt's
and an invoice's vendor; a goods receipt's purchase order) points to a record
of the ledger. An invoice may name a purchase order or a goods receipt that
does not exist: that is an exception the controls report (rule 2.1.3), not a
defect of the file.

    python -m auditiq ledger import ledger.xlsx          replaces the ledger of the store
    python -m auditiq ledger export data/large_seed_505 ledger.xlsx
"""
from __future__ import annotations

import datetime as dt
import io
import re
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

from . import db

TABLES = list(db.LEDGER_TABLES)
OPTIONAL = ["labels"]
KEYS = {"vendor_master": "vendor_id", "purchase_orders": "po_id", "goods_receipts": "grn_id",
        "invoices": "invoice_id", "approval_logs": "log_id"}
# (table, column, referenced table): the references the store enforces.
REFERENCES = [("purchase_orders", "vendor_id", "vendor_master"), ("goods_receipts", "po_id", "purchase_orders"),
              ("goods_receipts", "vendor_id", "vendor_master"), ("invoices", "vendor_id", "vendor_master")]
MAX_UNPACKED = 300 * 1024 * 1024       # a zip archive may not unpack to more than this
DATE = re.compile(r"^\d{4}-\d{2}-\d{2}([ T]\d{2}:\d{2}(:\d{2})?)?$")      # a date, or a date and time
BOOLEAN = {"true", "false", "t", "f", "1", "0"}
SHOWN = 5                              # problems of one kind listed before "and N more"


@dataclass
class Ledger:
    name: str
    frames: dict[str, pd.DataFrame] = field(default_factory=dict)
    problems: list[str] = field(default_factory=list)

    @property
    def usable(self) -> bool:
        return not self.problems

    def counts(self) -> dict[str, int]:
        return {name: len(frame) for name, frame in self.frames.items()}


def read(path: Path | str, conn: db.Database) -> Ledger:
    """Read and check a ledger; nothing is stored. ``conn`` supplies the columns of the store."""
    path = Path(path)
    ledger = Ledger(name=path.stem if path.is_file() else path.name)
    try:
        if path.is_dir():
            ledger.frames = _from_folder(path)
        elif path.suffix.lower() == ".zip":
            ledger.frames = _from_zip(path)
        elif path.suffix.lower() in (".xlsx", ".xlsm"):
            ledger.frames = _from_workbook(path)
        else:
            ledger.problems.append("give a folder of CSV files, a .zip archive of CSV files or an .xlsx workbook")
            return ledger
    except (zipfile.BadZipFile, ValueError, OSError, KeyError) as error:
        ledger.problems.append(f"the file cannot be read: {error}")
        return ledger
    ledger.problems += check(ledger.frames, conn)
    return ledger


def load(conn: db.Database, ledger: Ledger) -> dict[str, int]:
    """Replace the ledger of the store, and everything derived from it, with a checked ledger."""
    if not ledger.usable:
        raise ValueError("the ledger has problems: " + "; ".join(ledger.problems))
    return db.load_frames(conn, ledger.frames, ledger.name, replace=True)


def export_workbook(dataset: Path | str, out: Path | str) -> Path:
    """Write the tables of a dataset folder as the sheets of one workbook, every cell as text."""
    dataset, out = Path(dataset), Path(out)
    frames = _from_folder(dataset)
    out.parent.mkdir(parents=True, exist_ok=True)
    with pd.ExcelWriter(out, engine="openpyxl") as writer:
        for name, frame in frames.items():
            frame.to_excel(writer, sheet_name=name, index=False)
    return out


# ------------------------------------------------------------------ sources
def _from_folder(folder: Path) -> dict[str, pd.DataFrame]:
    return {name: _csv((folder / f"{name}.csv").read_bytes())
            for name in TABLES + OPTIONAL if (folder / f"{name}.csv").exists()}


def _from_zip(path: Path) -> dict[str, pd.DataFrame]:
    frames: dict[str, pd.DataFrame] = {}
    with zipfile.ZipFile(path) as archive:
        members = [m for m in archive.infolist() if not m.is_dir() and not Path(m.filename).name.startswith(".")]
        if sum(m.file_size for m in members) > MAX_UNPACKED:
            raise ValueError(f"the archive unpacks to more than {MAX_UNPACKED // (1024 * 1024)} MB")
        for member in members:
            name = Path(member.filename).stem
            if Path(member.filename).suffix.lower() != ".csv" or name not in TABLES + OPTIONAL:
                continue
            if name in frames:
                raise ValueError(f"the archive holds more than one {name}.csv")
            frames[name] = _csv(archive.read(member))
    return frames


def _from_workbook(path: Path) -> dict[str, pd.DataFrame]:
    sheets = pd.read_excel(path, sheet_name=None, dtype=object, engine="openpyxl")
    frames = {}
    for name, frame in sheets.items():
        if name.strip() in TABLES + OPTIONAL:
            columns = {str(column).strip(): frame[column] for column in frame.columns}
            frames[name.strip()] = pd.DataFrame({column: [_cell(v, column) for v in values]
                                                 for column, values in columns.items()}, dtype=str)
    return frames


def _csv(data: bytes) -> pd.DataFrame:
    frame = pd.read_csv(io.BytesIO(data), dtype=str, keep_default_na=False, encoding="utf-8-sig")
    frame.columns = [c.strip() for c in frame.columns]
    return frame


def _cell(value, column: str) -> str:
    """A workbook cell as the text a CSV file would hold."""
    if value is None or (isinstance(value, float) and pd.isna(value)) or value is pd.NaT:
        return ""
    if isinstance(value, (dt.datetime, pd.Timestamp)):
        midnight = (value.hour, value.minute, value.second) == (0, 0, 0)
        if _is_date(column) or (midnight and column != "timestamp"):
            return value.strftime("%Y-%m-%d")
        return value.strftime("%Y-%m-%d %H:%M:%S")
    if isinstance(value, dt.date):
        return value.isoformat()
    if isinstance(value, bool):
        return "True" if value else "False"
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip()


def _is_date(column: str) -> bool:
    return column == "date" or column.endswith("_date")


# ------------------------------------------------------------------- checks
def check(frames: dict[str, pd.DataFrame], conn: db.Database) -> list[str]:
    problems = [f"the table {name} is missing" for name in TABLES if name not in frames]
    for name, frame in frames.items():
        table = "benchmark_labels" if name == "labels" else name
        kinds = conn.columns(table)
        missing = [c for c in kinds if c not in frame.columns]
        if missing:
            problems.append(f"the table {name} lacks the column(s) {', '.join(missing)}")
            continue
        key = KEYS.get(name)
        if key:
            empty = int((frame[key].str.strip() == "").sum())
            if empty:
                problems.append(f"{name}: {empty} row(s) have no {key}")
            duplicated = sorted(set(frame.loc[frame[key].duplicated(), key]))
            if duplicated:
                problems.append(f"{name}: {key} is not unique ({_some(duplicated)})")
        for column, kind in kinds.items():
            values = frame[column].astype(str).str.strip()
            filled = values[values != ""]
            if column in db.BOOLEAN_COLUMNS:
                bad = sorted(set(v for v in filled if v.lower() not in BOOLEAN))
                if bad:
                    problems.append(f"{name}.{column}: not true or false ({_some(bad)})")
            elif kind in ("number", "integer"):
                bad = sorted(set(v for v in filled if not _number(v)))
                if bad:
                    problems.append(f"{name}.{column}: not a number ({_some(bad)})")
            elif _is_date(column) or column == "timestamp":
                bad = sorted(set(v for v in filled if not DATE.match(v)))
                if bad:
                    problems.append(f"{name}.{column}: not a date in the form YYYY-MM-DD, with or without "
                                    f"HH:MM:SS ({_some(bad)})")
    if problems:
        return problems
    for table, column, target in REFERENCES:
        known = set(frames[target][KEYS[target]])
        values = frames[table][column]
        dangling = sorted(set(v for v in values if v != "" and v not in known))
        if dangling:
            problems.append(f"{table}.{column} names records that are not in {target} ({_some(dangling)})")
    return problems


def _number(text: str) -> bool:
    try:
        float(text)
    except ValueError:
        return False
    return True


def _some(values: list[str]) -> str:
    shown = ", ".join(values[:SHOWN])
    return shown if len(values) <= SHOWN else f"{shown} and {len(values) - SHOWN} more"
