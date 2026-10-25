"""A vendor's other invoices, with an index the controls can look into instead of reading them all.

Two controls compare an invoice with the other invoices of its vendor: 2.2.1 (the invoice number was used
before) and 4.1.1 (too many invoices on one day). Read as a list, each costs time in proportion to the
vendor's history, so a ledger's time grew faster than its size: on 500,000 invoices from 15,000 vendors an
invoice cost 1.96 times as much as on 20,000 invoices (RESULTS.md, Section 5.1).

``History`` is the list the stages already read (oldest first), carrying a ``VendorIndex`` of all the
vendor's invoices, built once per vendor and shared by its transactions. It is a list in every other
respect: JSON writes it as one, the prompts show the same records, and a copy or a slice is a plain list,
for which the controls read the list as before. Both paths give the same findings (tests/test_controls.py).
"""
from __future__ import annotations


def number_key(value) -> str:
    """An invoice number as control 2.2.1 compares it."""
    return str(value or "").strip()


class VendorIndex:
    """Every invoice of one vendor, by invoice number and by date, each list oldest first."""

    __slots__ = ("by_number", "by_date")

    def __init__(self, records: list[dict]):
        self.by_number: dict[str, list[dict]] = {}
        self.by_date: dict[str, list[dict]] = {}
        for record in records:
            self.by_number.setdefault(number_key(record.get("invoice_number")), []).append(record)
            self.by_date.setdefault(record["date"], []).append(record)


class History(list):
    """The other invoices of the vendor, oldest first, with the vendor's index."""

    __slots__ = ("vendor_index",)

    def __init__(self, records, vendor_index: VendorIndex):
        super().__init__(records)
        self.vendor_index = vendor_index

    def __reduce__(self):                     # for the worker processes of evaluation.scalability
        return History, (list(self), self.vendor_index)


def vendor_histories(by_vendor: dict[str, list[dict]]) -> dict[str, VendorIndex]:
    """One index per vendor from the vendor's invoices, oldest first."""
    return {vendor_id: VendorIndex(records) for vendor_id, records in by_vendor.items()}
