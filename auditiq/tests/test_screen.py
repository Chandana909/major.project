"""The risk screen (auditiq/screen.py) and its exact SHAP values (auditiq/treeshap.py)."""
from __future__ import annotations

import json
import math
from itertools import combinations

import numpy as np
import pytest
from sklearn.tree import DecisionTreeRegressor

from auditiq import screen
from auditiq.extraction import extract
from auditiq.policy import load_policy
from auditiq.treeshap import Tree, _value_of_subset, ensemble_shap, exact_shap, tree_shap


def shapley_by_enumeration(tree: Tree, x: np.ndarray, n: int) -> np.ndarray:
    """The Shapley values of the path-dependent game over all n features, from the definition."""
    phi = np.zeros(n)
    X = x[None, :]
    value = {frozenset(s): float(_value_of_subset(tree, X, frozenset(s))[0])
             for size in range(n + 1) for s in combinations(range(n), size)}
    for i in range(n):
        others = [f for f in range(n) if f != i]
        for size in range(n):
            weight = math.factorial(size) * math.factorial(n - size - 1) / math.factorial(n)
            for s in combinations(others, size):
                phi[i] += weight * (value[frozenset(s) | {i}] - value[frozenset(s)])
    return phi


@pytest.fixture(scope="module")
def fitted() -> tuple[list[Tree], np.ndarray]:
    rng = np.random.default_rng(3)
    X = rng.normal(size=(400, 6))
    X[:, 5] = rng.integers(0, 3, size=400)                       # a feature with ties
    y = X[:, 0] * 2 + (X[:, 1] > 0.3) * 3 + X[:, 2] * X[:, 5] + rng.normal(scale=0.1, size=400)
    trees = [Tree.from_sklearn(DecisionTreeRegressor(max_depth=depth, random_state=k).fit(X, y))
             for k, depth in enumerate((1, 2, 3, 4))]
    return trees, X[:25]


def test_the_trees_read_back_predict_like_scikit_learn(fitted):
    rng = np.random.default_rng(3)
    X = rng.normal(size=(50, 6))
    model = DecisionTreeRegressor(max_depth=4, random_state=0).fit(X, X[:, 0] + X[:, 3])
    tree = Tree.from_sklearn(model)
    assert np.allclose(tree.predict(X), model.predict(X))
    assert Tree.from_json(json.loads(json.dumps(tree.to_json()))).predict(X) == pytest.approx(tree.predict(X))


def test_tree_shap_and_the_shapley_formula_give_the_same_values(fitted):
    trees, X = fitted
    for tree in trees:
        exact = exact_shap(tree, X)
        for r, x in enumerate(X):
            algorithm = np.asarray(tree_shap(tree, x, X.shape[1]))
            assert np.abs(algorithm - exact[r]).max() < 1e-9
            # and both are the Shapley values of the game over every feature, not only the ones the tree uses
            assert np.abs(shapley_by_enumeration(tree, x, X.shape[1]) - exact[r]).max() < 1e-9


def test_shap_values_add_up_to_the_output_and_ignore_unused_features(fitted):
    trees, X = fitted
    for tree in trees:
        phi = exact_shap(tree, X)
        assert np.abs(tree.expected_value() + phi.sum(axis=1) - tree.predict(X)).max() < 1e-9
        unused = [f for f in range(X.shape[1]) if f not in tree.features_used()]
        assert np.all(phi[:, unused] == 0)
    total = ensemble_shap(trees, X, scale=0.5)
    assert np.allclose(total, ensemble_shap(trees, X, scale=0.5, method="tree"))
    with pytest.raises(ValueError):
        ensemble_shap(trees, X, method="kernel")


def inv(invoice_id, day, amount, number="AB-100", po="PO1", grn="GRN1", description="Corrugated shipping cartons",
        role="Manager"):
    return {"invoice_id": invoice_id, "invoice_number": number, "date": day, "amount": amount, "quantity": 10,
            "po_id": po, "grn_id": grn, "description": description, "approver_role": role, "approver_name": "M. Rao"}


def txn(invoice: dict, history: list[dict], notes: str = "", po_description: str = "Corrugated shipping cartons, 5 ply",
        po_amount: float | None = None) -> dict:
    return {"invoice": {**invoice, "vendor_id": "V1", "gstin": "27ABCDE1234F1Z5", "unit_price": 1.0},
            "po": {"po_id": invoice["po_id"], "amount": po_amount or invoice["amount"], "quantity": 10,
                   "description": po_description},
            "grn": {"grn_id": invoice["grn_id"], "received_quantity": 10, "ordered_quantity": 10, "notes": notes},
            "vendor": {"vendor_id": "V1", "official_gstin": "27ABCDE1234F1Z5", "blacklisted": False,
                       "gstin_status": "Active"},
            "approvals": [{"log_id": "L1", "approver_name": "M. Rao", "approver_role": invoice["approver_role"],
                           "timestamp": f"{invoice['date']} 10:00:00", "action_taken": "Approved"}],
            "vendor_history": history}


def test_the_features_measure_what_they_say():
    params = screen.policy_parameters(load_policy("2.5"))
    earlier = [inv("I1", "2025-04-01", 92000.0), inv("I2", "2025-04-03", 95000.0, number="AB-101", po="PO2", grn="GRN2")]
    later = inv("I3", "2025-04-05", 92000.0, number="ab100")             # re-keyed, same PO, GRN and amount
    f = screen.features(txn(later, earlier, notes="3 cartons rejected at QC and returned to the vendor."), params)
    assert f["limit_ratio"] == pytest.approx(0.92) and f["below_limit_pct"] == pytest.approx(8.0)
    assert f["rekeyed_before"] == 1 and f["same_receipt_before"] == 1 and f["same_amount_before"] == 1
    assert f["same_number_before"] == 0 and f["window_near_limit"] == 3
    assert f["window_total_ratio"] == pytest.approx((92000 + 95000 + 92000) / 100000)
    assert f["remark_quantity"] == 1 and f["remark_adverse"] == 1
    assert f["desc_po_overlap"] > 0.5 and f["po_variance_pct"] == 0
    other = screen.features(txn(inv("I4", "2025-04-07", 640000.0, description="Annual tax consultancy retainer",
                                    role="Senior Manager"), [], notes="Received in good condition."), params)
    assert other["limit_ratio"] > 1 and other["below_limit_pct"] == 100 and other["window_near_limit"] == 0
    assert other["desc_po_overlap"] == 0 and other["remark_quantity"] == 0 and other["remark_adverse"] == 0
    assert screen.overlap("", "anything") == 0.0


@pytest.fixture(scope="module")
def trained(small_dataset) -> screen.Screen:
    return screen.train(small_dataset, load_policy("2.5"), params={"n_estimators": 25})


def test_a_trained_screen_ranks_its_training_ledger_and_reads_back_exactly(trained, small_dataset, tmp_path):
    assert set(trained.heads) == set(screen.HEADS)
    assert trained.training["ledger"] == small_dataset.name and trained.training["heads"]["2.2.2"]["positives"] == 30
    assert all(h["training_auc"] > 0.95 for h in trained.training["heads"].values())
    transactions = extract(small_dataset)
    params = screen.policy_parameters(load_policy("2.5"))
    X = screen.matrix(transactions, lambda _t: params)
    path = trained.save(tmp_path / "screen.json")
    again = screen.Screen.load(path)
    for name in screen.HEADS:
        assert np.allclose(again.heads[name].probability(X), trained.heads[name].probability(X))
    suggested, best = trained.suggested_rule(trained.scores(X))
    assert set(suggested) <= set(screen.JUDGEMENT_HEADS) and best.shape == (len(transactions),)


def test_an_explanation_adds_up_and_lists_the_largest_contributions(trained, small_dataset):
    params = screen.policy_parameters(load_policy("2.5"))
    X = screen.matrix(extract(small_dataset)[:40], lambda _t: params)
    for x in X[:5]:
        out = screen.explain_row(trained, x, top=4)
        for head in out.values():
            assert abs(head["check"]) < 1e-6
            sizes = [abs(c["shap"]) for c in head["contributions"]]
            assert sizes == sorted(sizes, reverse=True) and len(sizes) <= 4
            shown = sum(c["shap"] for c in head["contributions"]) + head["other"]
            # each listed value is rounded to 6 decimals, so their sum may differ by a few millionths; the exact
            # check is `check` above, computed before rounding
            assert head["base"] + shown == pytest.approx(head["raw"], abs=1e-5)
    ranked = screen.importance(trained, X, beeswarm=10)
    assert ranked["any"]["rows"] == 40 and len(ranked["any"]["features"]) == len(screen.FEATURE_NAMES)
    assert len(ranked["any"]["points"]) == 10 and len(ranked["any"]["points"][0]["shap"]) == 10


def test_a_model_of_other_features_is_refused(trained, tmp_path):
    path = trained.save(tmp_path / "screen.json")
    data = json.loads(path.read_text(encoding="utf-8"))
    data["features"] = data["features"][:-1]
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(screen.ScreenUnavailable):
        screen.Screen.load(path)
    with pytest.raises(screen.ScreenUnavailable):
        screen.Screen.load(tmp_path / "missing.json")


def test_the_committed_model_is_the_screen_of_these_features():
    committed = screen.Screen.load()
    assert set(committed.heads) == set(screen.HEADS) and committed.training["ledger"] == screen.TRAINING_LEDGER
    assert all(len(h.trees) == screen.PARAMS["n_estimators"] for h in committed.heads.values())


def test_the_area_under_the_curve_counts_ties_as_half():
    assert screen.auc(np.array([1, 0, 1, 0]), np.array([0.9, 0.1, 0.8, 0.2])) == 1.0
    assert screen.auc(np.array([1, 0]), np.array([0.5, 0.5])) == 0.5
    assert screen.auc(np.array([0, 0]), np.array([0.1, 0.2])) is None
