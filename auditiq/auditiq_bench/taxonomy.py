"""Anomaly classes of AuditIQ-Bench (Table II of the paper) and their clauses.

A class is what the benchmark injects. A clause is what a finding cites. Most
classes map to one clause; R4 and R10 each cover two.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class AnomalyClass:
    class_id: str
    name: str
    clauses: tuple[str, ...]
    kind: str  # "rule" (decidable from field values) or "judgement"


CLASSES: dict[str, AnomalyClass] = {
    c.class_id: c
    for c in [
        AnomalyClass("R1", "Invoice amount differs from PO amount beyond the tolerance", ("2.1.1",), "rule"),
        AnomalyClass("R2", "Billed quantity exceeds received quantity", ("2.1.2",), "rule"),
        AnomalyClass("R3", "Duplicate invoice number for the same vendor", ("2.2.1",), "rule"),
        AnomalyClass("R4", "Malformed GSTIN or invalid state code", ("3.1.1", "3.1.2"), "rule"),
        AnomalyClass("R5", "Invoice GSTIN differs from the vendor master", ("3.1.3",), "rule"),
        AnomalyClass("R6", "Same-day invoice splitting above the daily count", ("4.1.1",), "rule"),
        AnomalyClass("R7", "Invoice amount exceeds the approver's limit", ("5.1.1",), "rule"),
        AnomalyClass("R8", "Missing PO or GRN reference", ("2.1.3",), "rule"),
        AnomalyClass("R9", "Vendor blacklisted or suspended", ("4.4.1",), "rule"),
        AnomalyClass("R10", "Weekend-dated or round-amount invoice", ("4.2.1", "4.3.1"), "rule"),
        AnomalyClass("J1", "Near-duplicate invoice: re-keyed number, same vendor and amount", ("2.2.2",), "judgement"),
        AnomalyClass("J2", "Cross-day structuring just below an approval limit", ("4.1.2",), "judgement"),
        AnomalyClass("J3", "Invoice description inconsistent with the PO description", ("2.1.5",), "judgement"),
        AnomalyClass("J4", "GRN remark contradicts the billed quantity", ("2.1.4",), "judgement"),
    ]
}

RULE_CLASSES = [c for c, v in CLASSES.items() if v.kind == "rule"]
JUDGEMENT_CLASSES = [c for c, v in CLASSES.items() if v.kind == "judgement"]

CLAUSE_TO_CLASS: dict[str, str] = {
    clause: c.class_id for c in CLASSES.values() for clause in c.clauses
}

# Hard negatives: clean invoices built to resemble an anomaly class.
HARD_NEGATIVE_TYPES: dict[str, str] = {
    "HN_TOLERANCE": "Invoice-PO variance just inside the tolerance (resembles R1)",
    "HN_DAILY_LIMIT": "Invoice count exactly at the daily limit (resembles R6)",
    "HN_NEAR_LIMIT": "Amount just inside an approval limit (resembles R7 and J2)",
    "HN_SIMILAR_NUMBER": "Consecutive invoice numbers and equal amounts for separate deliveries (resembles J1)",
    "HN_RECURRING": "Identical recurring monthly amounts (resembles R3 and J1)",
}

# Composition of one dataset (Section VI-A of the paper).
PER_CLASS = 30
PER_HARD_NEGATIVE_TYPE = 24
N_ORDINARY = 660
N_VENDORS = 60
N_INVOICES = PER_CLASS * len(CLASSES) + PER_HARD_NEGATIVE_TYPE * len(HARD_NEGATIVE_TYPES) + N_ORDINARY
assert N_INVOICES == 1200
