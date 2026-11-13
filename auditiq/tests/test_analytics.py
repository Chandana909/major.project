"""Tests of the ledger analytics and the collusion rings (auditiq/analytics.py, auditiq/rings.py)."""
from __future__ import annotations

import math

import pytest

from auditiq import analytics, db, rings, service
from auditiq.graph import PRESETS


@pytest.fixture()
def audited(conn):
    """The small ledger with every invoice audited by the controls (C1)."""
    ids = [r[0] for r in conn.execute("SELECT invoice_id FROM invoices ORDER BY invoice_id")]
    service.audit_invoices(conn, PRESETS["C1"], db.read_policy(conn), None, ids)
    return conn


def test_the_views_add_up_to_the_ledger(audited):
    out = analytics.ledger_analytics(audited)
    invoices = int(audited.scalar("SELECT COUNT(*) FROM invoices"))
    total = float(audited.scalar("SELECT SUM(amount) FROM invoices"))
    assert out["invoices"] == invoices == 1200
    for view in (out["monthly"], out["weekdays"], out["categories"]["rows"]):
        assert sum(row["invoices"] for row in view) == invoices
        assert math.isclose(sum(row["amount"] for row in view), total, rel_tol=1e-9)
    assert sum(sum(row) for row in out["skyline"]["amounts"]) == pytest.approx(total)
    flagged = int(audited.scalar("SELECT COUNT(*) FROM v_latest_results WHERE flag_count > 0"))
    assert sum(m["flagged"] for m in out["monthly"]) == flagged
    findings = int(audited.scalar("SELECT COUNT(*) FROM audit_flags WHERE status = 'kept'"))
    assert sum(sum(row["findings"]) for row in out["categories"]["rows"]) == findings
    assert out["approvers"]["total"] == int(audited.scalar("SELECT COUNT(DISTINCT approved_by) FROM invoices"))
    assert sum(b["invoices"] for b in out["amounts"]["bins"]) == invoices


def test_amounts_are_counted_against_the_limits_of_the_active_policy(audited):
    near = analytics.ledger_analytics(audited)["amounts"]["limits"]
    assert [(n["role"], n["limit"]) for n in near] == [
        ("Manager", 100000), ("Senior Manager", 500000), ("Director", 2500000), ("CFO", 10000000)]
    for n in near:
        below = audited.scalar("SELECT COUNT(*) FROM invoices WHERE amount >= ? AND amount < ?", (n["limit"] * 0.9, n["limit"]))
        above = audited.scalar("SELECT COUNT(*) FROM invoices WHERE amount >= ? AND amount < ?", (n["limit"], n["limit"] * 1.1))
        assert (n["below"], n["above"]) == (int(below), int(above))


def test_benford_counts_significant_digits_whatever_the_size():
    out = analytics.benford([1000, 2000, 1500, 19.9, 99, 5, 0.5])
    assert out["n"] == 5                                                    # 5 and 0.5 are below 10
    first = {d["digit"]: d["count"] for d in out["first"]["digits"]}
    assert (first[1], first[2], first[9]) == (3, 1, 1)
    two = {d["digit"]: d["count"] for d in out["first_two"]["digits"]}
    assert (two[10], two[15], two[19], two[20], two[99]) == (1, 1, 1, 1, 1)
    assert sum(d["expected"] for d in out["first"]["digits"]) == pytest.approx(1)


def test_benford_conformity_follows_the_mean_absolute_deviation():
    spread = [10 ** (2 + k / 20000) for k in range(60000)]                 # uniform in log over three decades
    assert analytics.benford(spread)["first"]["conformity"] == "close conformity"
    assert analytics.benford(spread)["first_two"]["conformity"] == "close conformity"
    nines = analytics.benford([9000.0 + k for k in range(500)])
    assert nines["first"]["conformity"] == "nonconformity"
    assert next(d for d in nines["first"]["digits"] if d["digit"] == 9)["significant"]


def test_concentration_measures_how_unevenly_the_spend_is_spread():
    from collections import Counter
    even = analytics._concentration(Counter({f"V{i}": 100.0 for i in range(10)}), {})
    assert even["gini"] == pytest.approx(0, abs=1e-9) and even["lorenz"][0] == [0, 0] and even["lorenz"][-1] == [1, 1]
    skewed = analytics._concentration(Counter({"V0": 1000.0, **{f"V{i}": 0.0 for i in range(1, 10)}}), {})
    assert skewed["gini"] == pytest.approx(0.9) and skewed["top10_share"] == 1 and skewed["hhi"] == pytest.approx(10000)


def test_coverage_says_what_the_latest_results_did_not_check(audited):
    out = analytics.coverage(audited)
    assert out["configurations"] == {"C1": 1200}
    assert (out["controls_run"], out["judgement_run"]) == (1200, 0)
    assert out["judgement_clauses"] == ["2.1.4", "2.1.5", "2.2.2", "4.1.2"]
    held = audited.scalar("SELECT COUNT(*) FROM v_latest_results WHERE flag_count > 0 AND route = 'approve'")
    assert out["approved_with_findings"] == int(held)
    key = out["answer_key"]
    anomalous = int(audited.scalar("SELECT COUNT(*) FROM benchmark_labels WHERE label = 'anomalous'"))
    judged = int(audited.scalar("SELECT COUNT(*) FROM benchmark_labels WHERE label = 'anomalous' "
                                "AND clause_ids IN ('2.1.4', '2.1.5', '2.2.2', '4.1.2')"))
    assert key["found"] + key["missed"] + key["not_checked"] == anomalous == 420
    assert key["not_checked"] == judged                  # the controls cannot see a judgement rule
    assert (key["missed"], key["false_alarms"]) == (0, 0)
    assert key["by_configuration"]["C1"]["precision"] == 1


def test_the_answer_key_scores_only_results_under_its_own_policy(audited):
    assert audited.scalar("SELECT value FROM meta WHERE key = 'labels_policy'") == "2.5"      # from the manifest
    audited.execute("UPDATE meta SET value = '2.6' WHERE key = 'labels_policy'")
    audited.commit()
    key = analytics.coverage(audited)["answer_key"]
    assert (key["policy_version"], key["other_policy"], key["found"], key["false_alarms"]) == ("2.6", 1200, 0, 0)


def test_coverage_without_an_answer_key(audited):
    audited.execute("DELETE FROM benchmark_labels")
    audited.commit()
    assert analytics.coverage(audited)["answer_key"] is None


def test_the_binomial_tail_and_the_false_discovery_rate():
    assert rings.binomial_tail(2, 2, 0.1) == pytest.approx(0.01)
    assert rings.binomial_tail(1, 3, 0.5) == pytest.approx(0.875)
    assert (rings.binomial_tail(0, 5, 0.3), rings.binomial_tail(3, 2, 0.5), rings.binomial_tail(1, 10, 0.0)) == (1, 0, 0)
    # Benjamini-Hochberg: each q-value is the least of p * m / rank over its rank and those above it.
    assert rings.benjamini_hochberg([0.01, 0.04, 0.03, 0.5]) == pytest.approx([0.04, 0.16 / 3, 0.16 / 3, 0.5])


def high_or_critical(conn, approver: str, vendor: str) -> int:
    return int(conn.scalar(
        "SELECT COUNT(DISTINCT i.invoice_id) FROM audit_flags f JOIN v_latest_results l ON l.result_id = f.result_id "
        "JOIN invoices i ON i.invoice_id = l.invoice_id WHERE f.status = 'kept' AND f.severity IN ('high', 'critical') "
        "AND i.approved_by = ? AND i.vendor_id = ?", (approver, vendor)))


def test_every_pair_is_tested_against_the_rate_of_its_role(audited):
    out = rings.find_rings(audited, limit=200)
    tests = out["tests"]
    pairs = audited.scalar("SELECT COUNT(*) FROM (SELECT vendor_id, approved_by FROM invoices WHERE approved_by <> '' "
                           "GROUP BY vendor_id, approved_by HAVING COUNT(*) >= 2) t")
    assert tests["pairs_tested"] == int(pairs)
    assert tests["approvers_tested"] == int(audited.scalar("SELECT COUNT(DISTINCT approved_by) FROM invoices WHERE approved_by <> ''"))
    assert sum(r["invoices"] for r in tests["role_rates"]) == int(audited.scalar("SELECT COUNT(*) FROM invoices WHERE approved_by <> ''"))
    rates = {r["role"]: r["rate"] for r in tests["role_rates"]}
    assert [w["p"] for w in out["watch"]] == sorted(w["p"] for w in out["watch"])     # the most unusual first
    for w in out["watch"]:
        assert w["flagged"] == high_or_critical(audited, w["approver"], w["vendor_id"]) >= 2
        assert w["q"] >= w["p"] and w["expected"] == pytest.approx(w["invoices"] * rates[w["role"]])
        assert w["significant"] == (w["q"] <= rings.FDR)
    assert tests["pairs_significant"] == sum("repeated findings" in e["kinds"] for e in out["edges"])
    assert out["leads"]["groups"] and {n["ring"] for n in out["leads"]["nodes"]} == {g["id"] for g in out["leads"]["groups"]}


def test_links_that_pass_the_tests_form_rings(audited, monkeypatch):
    monkeypatch.setattr(rings, "FDR", 1.0)                     # every test passes: the links alone decide the rings
    out = rings.find_rings(audited, limit=200)
    assert out["rings"] and out["tests"]["hotspots"] == out["tests"]["approvers_tested"]
    nodes = {n["id"]: n for n in out["nodes"]}
    for ring in out["rings"]:
        assert len(ring["vendors"]) >= 2 and set(ring["link_kinds"]) <= set(rings.LINKS)
    for edge in out["edges"]:
        assert nodes[edge["source"]]["ring"] == nodes[edge["target"]]["ring"] == edge["ring"]
        approver, vendor = sorted((edge["source"], edge["target"]))           # "a:..." sorts before "v:..."
        if "repeated findings" in edge["kinds"]:
            assert high_or_critical(audited, approver[2:], vendor[2:]) >= 2
        if "approver hotspot" in edge["kinds"]:
            assert high_or_critical(audited, approver[2:], vendor[2:]) >= 1
    assert all(p["approvers"] for p in out["pairs"])          # a group around one vendor is held by its approvers


def test_a_pan_shared_by_two_vendors_makes_a_ring(audited):
    first, second = (r[0] for r in audited.execute("SELECT vendor_id FROM vendor_master ORDER BY vendor_id LIMIT 2"))
    audited.execute("UPDATE vendor_master SET pan_number = (SELECT pan_number FROM vendor_master WHERE vendor_id = ?) "
                    "WHERE vendor_id = ?", (first, second))
    audited.commit()
    out = rings.find_rings(audited, limit=200)
    assert out["identity"]["shared_pan"] == 1
    ring = next(r for r in out["rings"] if {first, second} <= set(r["vendors"]))
    assert ring["link_kinds"]["shared PAN"] == 1
