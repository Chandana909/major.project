"""Tests of the auditors'-side measures of evaluation/industry.py."""
from __future__ import annotations

import numpy as np

from evaluation.industry import expected_precision_at, ranking


def test_precision_in_the_top_k_does_not_credit_an_order_that_ties_hide():
    scores = np.array([9, 5, 5, 5, 5, 1])
    positive = np.array([1, 1, 0, 1, 0, 0])
    assert expected_precision_at(scores, positive, 1) == 1.0
    # k = 3 takes the 9 and two of the four tied 5s, of which half are anomalous: (1 + 2 * 0.5) / 3
    assert abs(expected_precision_at(scores, positive, 3) - 2 / 3) < 1e-12
    assert expected_precision_at(scores, positive, 5) == 3 / 5
    assert expected_precision_at(scores, positive, 50) == 3 / 6          # a budget beyond the ledger: all of it


def test_a_perfect_ranking_scores_one():
    out = ranking(np.array([3.0, 2.0, 1.0, 0.0]), np.array([1, 1, 0, 0]))
    assert out["average_precision"] == 1.0 and out["roc_auc"] == 1.0 and out["distinct_scores"] == 4
