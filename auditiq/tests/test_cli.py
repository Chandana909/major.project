"""The command line, end to end on a small ledger, without a model, on both backends."""
from __future__ import annotations

import pytest

from auditiq import db
from auditiq.cli import main


@pytest.fixture()
def cli(backend, make_store, capsys):
    target = make_store(backend)

    def run(*args: str) -> tuple[int, str]:
        code = main(["--db", target, *args])
        captured = capsys.readouterr()
        return code, captured.out + captured.err
    run.path = target
    return run


def test_setup_run_review_and_search_from_the_command_line(cli, small_dataset, backend, tmp_path):
    code, out = cli("setup", "--dataset", str(small_dataset))
    assert code == 0 and "1200 invoices" in out and "policy versions stored: 2.5, 2.6 (active: 2.5)" in out
    assert out.count("16 clauses") == 2 and "MISMATCH" not in out and "lexical only" in out

    code, out = cli("run", "--config", "C1")
    assert code == 0 and '"invoices": 1200' in out and '"PENDING_REVIEW": 240' in out and '"AUTO_APPROVED": 960' in out
    code, out = cli("run", "--config", "C1", "--unaudited")
    assert "no invoice to audit" in out

    code, out = cli("queue", "--limit", "3")
    assert code == 0 and "240 invoice(s) waiting for review" in out
    conn = db.connect(cli.path)
    first = db.review_queue(conn)[0]
    conn.close()

    code, out = cli("show", "--invoice", first["invoice_id"])
    assert code == 0 and f"# Audit pack: {first['invoice_id']}" in out
    assert "Source: Procurement_Audit_SOP_v2.5.pdf, page" in out and "Audit trail" in out and "PENDING_REVIEW" in out

    code, out = cli("decide", "--result", str(first["result_id"]), "--decision", "override", "--reviewer", "A. Auditor")
    assert code == 2 and "justification" in out
    code, out = cli("decide", "--result", str(first["result_id"]), "--decision", "approve", "--reviewer", "A. Auditor")
    assert code == 0 and "recorded: approve by A. Auditor" in out
    code, out = cli("queue")
    assert "239 invoice(s) waiting for review" in out
    code, out = cli("show", "--invoice", first["invoice_id"])
    assert "Decision: approve" in out and "REVIEW_APPROVED" in out
    assert cli("show", "--invoice", "INV00000")[0] == 2

    code, out = cli("policy", "search", "invoice", "dated", "on", "a", "Saturday", "or", "Sunday", "-k", "2")
    assert code == 0 and "ranking: lexical" in out and "[1] Rule 4.2.1 (Procurement_Audit_SOP_v2.5.pdf, page 2)" in out
    code, out = cli("ask", "--no-llm", "vendor", "marked", "blacklisted")
    assert code == 0 and "Rule 4.4.1" in out

    code, out = cli("status")
    assert code == 0 and f"backend   {backend}" in out and "ledger    small_seed_7" in out
    assert "policy    version 2.5" in out and "audit_results" in out
    assert "password" not in out and "@" not in out.split("location")[1].splitlines()[0].split("localhost")[0]
    code, out = cli("export", "--out", str(tmp_path / "export"), "--tables", "invoices", "audit_flags")
    assert code == 0 and "invoices.csv  1,200 rows" in out and (tmp_path / "export" / "audit_flags.csv").exists()


def test_a_ledger_is_exported_to_a_workbook_checked_and_imported(cli, small_dataset, boundary_dataset, tmp_path):
    assert cli("setup", "--dataset", str(boundary_dataset))[0] == 0
    book = tmp_path / "ledger.xlsx"
    code, out = cli("ledger", "export", str(small_dataset), str(book))
    assert code == 0 and book.exists()
    code, out = cli("ledger", "check", str(book))
    assert code == 0 and "ledger: usable; 60 vendor_master" in out and "1200 invoices" in out
    code, out = cli("ledger", "import", str(book))
    assert code == 0 and "ledger ledger loaded" in out and "1200 invoices" in out
    conn = db.connect(cli.path)
    assert conn.scalar("SELECT COUNT(*) FROM invoices") == 1200
    conn.close()

    broken = tmp_path / "broken"
    broken.mkdir()
    (broken / "invoices.csv").write_text("invoice_id\nINV1\n", encoding="utf-8")
    code, out = cli("ledger", "import", str(broken))
    assert code == 1 and "the table vendor_master is missing" in out and "the ledger was not loaded" in out
    code, out = cli("setup", "--dataset", str(broken))
    assert code == 1 and "the ledger was not loaded" in out


def test_the_policy_swap_from_the_command_line(cli, boundary_dataset):
    """Activating version 2.6 changes what the same controls flag, with no other change."""
    cli("setup", "--dataset", str(boundary_dataset))
    code, out = cli("run", "--config", "C1")
    assert '"invoices": 150' in out and '"flags": 150' in out and '"PENDING_REVIEW": 150' in out
    code, out = cli("policy", "activate", "2.6")
    assert code == 0 and "active policy version: 2.6" in out
    code, out = cli("run", "--config", "C1")
    assert '"flags": 0' in out and '"AUTO_APPROVED": 150' in out
    assert "0 invoice(s) waiting for review" in cli("queue")[1]


def test_commands_that_need_a_model_say_so(cli, boundary_dataset):
    cli("setup", "--dataset", str(boundary_dataset))
    with pytest.raises(RuntimeError, match="No model is configured"):
        cli("run", "--config", "C5", "--limit", "1")
    code, out = cli("policy", "embed")
    assert code == 2 and "AUDITIQ_EMBED_MODEL" in out


def test_an_unreachable_database_ends_with_a_message_not_a_traceback(capsys):
    with pytest.raises(db.DatabaseUnavailable, match="pg_local.py start"):
        db.connect("postgresql://nobody:x@127.0.0.1:1/none")
    assert main(["--db", "postgresql://nobody:secret-word@127.0.0.1:1/none", "status"]) == 2
    err = capsys.readouterr().err
    assert "cannot connect to PostgreSQL at 127.0.0.1:1/none" in err and "secret-word" not in err
