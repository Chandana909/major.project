"""The dry run of a policy document: what it predicts is what adopting the document then does."""
from __future__ import annotations

from auditiq import db, service, simulation
from auditiq.graph import PRESETS
from auditiq.policy import load_policy


def test_the_same_policy_moves_nothing(conn):
    out = simulation.simulate(conn, load_policy("2.5").registry)
    assert out["invoices"] == 1200 and out["decisions_moved"] == 0 and out["route_changes"] == {}
    assert out["routes"]["before"] == out["routes"]["after"]


def test_the_predicted_routes_are_the_routes_of_the_audit_under_the_new_policy(conn):
    v26 = load_policy("2.6")
    out = simulation.simulate(conn, v26.registry)
    assert out["active_version"] == "2.5" and out["new_version"] == "2.6"
    assert out["decisions_moved"] > 0 and out["cleared"] > 0 and out["newly_flagged"] == 0    # 2.6 only loosens
    assert conn.scalar("SELECT COUNT(*) FROM audit_results") == 0                            # nothing was stored
    db.set_active_policy(conn, "2.6")
    run = service.audit_invoices(conn, PRESETS["C1"], db.read_policy(conn), None, db.invoice_ids(conn))
    routes = {r[0]: r[1] for r in conn.execute("SELECT route, COUNT(*) FROM audit_results WHERE run_id = ? "
                                               "GROUP BY route", (run,))}
    assert routes == out["routes"]["after"]
    flags = {r[0]: r[1] for r in conn.execute("SELECT f.clause, COUNT(DISTINCT r.invoice_id) FROM audit_flags f JOIN "
                                              "audit_results r ON r.result_id = f.result_id WHERE r.run_id = ? "
                                              "GROUP BY f.clause", (run,))}
    assert {r["rule"]: r["after"] for r in out["findings_by_rule"] if r["after"]} == flags
