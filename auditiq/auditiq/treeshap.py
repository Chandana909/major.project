"""Exact SHAP values for tree ensembles, written from the published algorithms, with no dependency.

A SHAP value (Lundberg and Lee, 2017) splits a model's output for one invoice into a part for each feature: the
parts and the model's expected output add up to the output exactly ("local accuracy"), a feature the model does not
use gets zero, and the split is the Shapley value of the game whose players are the features. For a tree, the value
of a set S of features is the tree's expected output when the features in S are fixed at the invoice's values and
the others follow the training data down the tree ("path-dependent" expectation: at a split on a feature outside S
both branches are taken, weighted by the training rows that went each way, the node's cover).

Two implementations of the same quantity, so that each checks the other (tests/test_screen.py):

    tree_shap()        TreeSHAP, Algorithm 2 of Lundberg, Erion and Lee (2018), "Consistent individualized
                       feature attribution for tree ensembles" (arXiv:1802.03888), as in the reference
                       implementation: polynomial time, one invoice at a time. Used for a single invoice.
    exact_shap()       the Shapley formula itself, over every subset of the features a tree splits on (a tree of
                       depth 3 splits on at most 7), vectorised over many invoices with numpy. Used for the
                       importance of each feature over a ledger.

Shapley values are linear in the game, so the values of an ensemble are the sums of the values of its trees,
scaled by the learning rate. Everything here works on ``Tree``: plain arrays read from a fitted scikit-learn tree,
or from the JSON file the screen is stored in (auditiq/screen.py).
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from itertools import combinations

import numpy as np


@dataclass(frozen=True)
class Tree:
    """One regression tree: node arrays in scikit-learn's layout (a leaf has left = right = -1)."""
    left: tuple[int, ...]
    right: tuple[int, ...]
    feature: tuple[int, ...]
    threshold: tuple[float, ...]
    value: tuple[float, ...]
    cover: tuple[float, ...]

    def to_json(self) -> dict:
        return {"left": list(self.left), "right": list(self.right), "feature": list(self.feature),
                "threshold": [round(t, 12) for t in self.threshold], "value": list(self.value),
                "cover": list(self.cover)}

    @classmethod
    def from_json(cls, data: dict) -> Tree:
        return cls(tuple(int(v) for v in data["left"]), tuple(int(v) for v in data["right"]),
                   tuple(int(v) for v in data["feature"]), tuple(float(v) for v in data["threshold"]),
                   tuple(float(v) for v in data["value"]), tuple(float(v) for v in data["cover"]))

    @classmethod
    def from_sklearn(cls, tree) -> Tree:
        """From a fitted ``sklearn.tree.DecisionTreeRegressor`` (its public ``tree_`` arrays)."""
        t = tree.tree_
        return cls(tuple(int(v) for v in t.children_left), tuple(int(v) for v in t.children_right),
                   tuple(int(v) if t.children_left[i] >= 0 else -1 for i, v in enumerate(t.feature)),
                   tuple(float(v) for v in t.threshold), tuple(float(v) for v in t.value[:, 0, 0]),
                   tuple(float(v) for v in t.weighted_n_node_samples))

    def is_leaf(self, node: int) -> bool:
        return self.left[node] < 0

    def features_used(self) -> list[int]:
        return sorted({f for n, f in enumerate(self.feature) if not self.is_leaf(n)})

    def predict(self, X: np.ndarray) -> np.ndarray:
        """The leaf value each row reaches (a row goes left when its value is at most the threshold)."""
        X = np.atleast_2d(X)
        node = np.zeros(X.shape[0], dtype=np.int64)
        left, right = np.asarray(self.left), np.asarray(self.right)
        feature, threshold = np.asarray(self.feature), np.asarray(self.threshold)
        for _ in range(len(self.left)):                         # at most one step per level; depth < node count
            inner = left[node] >= 0
            if not inner.any():
                break
            rows = np.nonzero(inner)[0]
            n = node[rows]
            go_left = X[rows, feature[n]] <= threshold[n]
            node[rows] = np.where(go_left, left[n], right[n])
        return np.asarray(self.value)[node]

    def expected_value(self) -> float:
        """The cover-weighted mean of the leaves: the tree's expected output over its training data."""
        return float(sum(self.value[n] * self.cover[n] for n in range(len(self.left)) if self.is_leaf(n))
                     / self.cover[0])


# ------------------------------------------------------------------ TreeSHAP (Algorithm 2)
# A path element is [feature, zero_fraction, one_fraction, permutation_weight].
def _extend(path: list[list], zero: float, one: float, feature: int) -> None:
    depth = len(path)
    path.append([feature, zero, one, 1.0 if depth == 0 else 0.0])
    for i in range(depth - 1, -1, -1):
        path[i + 1][3] += one * path[i][3] * (i + 1) / (depth + 1)
        path[i][3] = zero * path[i][3] * (depth - i) / (depth + 1)


def _unwind(path: list[list], index: int) -> None:
    depth = len(path) - 1
    one, zero = path[index][2], path[index][1]
    next_one = path[depth][3]
    for i in range(depth - 1, -1, -1):
        if one != 0:
            kept = path[i][3]
            path[i][3] = next_one * (depth + 1) / ((i + 1) * one)
            next_one = kept - path[i][3] * zero * (depth - i) / (depth + 1)
        else:
            path[i][3] = path[i][3] * (depth + 1) / (zero * (depth - i))
    for i in range(index, depth):
        path[i][0], path[i][1], path[i][2] = path[i + 1][0], path[i + 1][1], path[i + 1][2]
    path.pop()


def _unwound_sum(path: list[list], index: int) -> float:
    depth = len(path) - 1
    one, zero = path[index][2], path[index][1]
    next_one = path[depth][3]
    total = 0.0
    for i in range(depth - 1, -1, -1):
        if one != 0:
            part = next_one * (depth + 1) / ((i + 1) * one)
            total += part
            next_one = path[i][3] - part * zero * ((depth - i) / (depth + 1))
        else:
            total += (path[i][3] / zero) / ((depth - i) / (depth + 1))
    return total


def _recurse(tree: Tree, x, phi: list[float], node: int, parent: list[list], zero: float, one: float,
             feature: int) -> None:
    path = [list(e) for e in parent]
    _extend(path, zero, one, feature)
    if tree.is_leaf(node):
        for i in range(1, len(path)):
            f, z, o, _ = path[i]
            phi[f] += _unwound_sum(path, i) * (o - z) * tree.value[node]
        return
    split = tree.feature[node]
    left, right = tree.left[node], tree.right[node]
    hot, cold = (left, right) if x[split] <= tree.threshold[node] else (right, left)
    cover = tree.cover[node]
    incoming_zero, incoming_one = 1.0, 1.0
    seen = next((i for i, e in enumerate(path) if e[0] == split), None)
    if seen is not None:                     # the feature was split on above: undo that split, redo it here
        incoming_zero, incoming_one = path[seen][1], path[seen][2]
        _unwind(path, seen)
    _recurse(tree, x, phi, hot, path, tree.cover[hot] / cover * incoming_zero, incoming_one, split)
    _recurse(tree, x, phi, cold, path, tree.cover[cold] / cover * incoming_zero, 0.0, split)


def tree_shap(tree: Tree, x, n_features: int) -> list[float]:
    """The SHAP values of one row ``x`` for one tree (Algorithm 2)."""
    phi = [0.0] * n_features
    _recurse(tree, x, phi, 0, [], 1.0, 1.0, -1)
    return phi


# ------------------------------------------------------------------ the Shapley formula, vectorised
def _value_of_subset(tree: Tree, X: np.ndarray, fixed: frozenset[int]) -> np.ndarray:
    """E[tree(x) | the features in ``fixed`` take the row's values], path-dependent, for every row of X."""
    total = np.zeros(X.shape[0])
    stack = [(0, np.ones(X.shape[0]))]
    while stack:
        node, weight = stack.pop()
        if tree.is_leaf(node):
            total += weight * tree.value[node]
            continue
        left, right, f = tree.left[node], tree.right[node], tree.feature[node]
        if f in fixed:
            go_left = X[:, f] <= tree.threshold[node]
            stack.append((left, weight * go_left))
            stack.append((right, weight * ~go_left))
        else:
            cover = tree.cover[node]
            stack.append((left, weight * (tree.cover[left] / cover)))
            stack.append((right, weight * (tree.cover[right] / cover)))
    return total


def exact_shap(tree: Tree, X: np.ndarray) -> np.ndarray:
    """SHAP values of every row of X for one tree, from the Shapley formula over the features the tree uses."""
    X = np.atleast_2d(np.asarray(X, dtype=float))
    phi = np.zeros(X.shape)
    used = tree.features_used()
    m = len(used)
    if m == 0:
        return phi
    values = {frozenset(s): _value_of_subset(tree, X, frozenset(s))
              for size in range(m + 1) for s in combinations(used, size)}
    for i in used:
        others = [f for f in used if f != i]
        for size in range(m):
            weight = math.factorial(size) * math.factorial(m - size - 1) / math.factorial(m)
            for s in combinations(others, size):
                subset = frozenset(s)
                phi[:, i] += weight * (values[subset | {i}] - values[subset])
    return phi


def ensemble_shap(trees: list[Tree], X: np.ndarray, scale: float = 1.0, method: str = "exact") -> np.ndarray:
    """SHAP values of every row of X for a sum of trees, each multiplied by ``scale`` (the learning rate)."""
    X = np.atleast_2d(np.asarray(X, dtype=float))
    phi = np.zeros(X.shape)
    if method == "exact":
        for tree in trees:
            phi += exact_shap(tree, X)
    elif method == "tree":
        for r, row in enumerate(X):
            for tree in trees:
                phi[r] += tree_shap(tree, row, X.shape[1])
    else:
        raise ValueError(f"unknown method {method!r}")
    return phi * scale
