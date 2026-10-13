"""AuditIQ-Bench generator.

Builds linked procurement records (vendors, purchase orders, goods receipts,
invoices, approval logs) and injects labelled anomalies. Every label is written
by the function that performs the injection. This module shares no code with
the controls in ``controls/``; it reads only the policy registry, which is data.
"""
from __future__ import annotations

import string
from dataclasses import dataclass
from datetime import date, datetime, timedelta

import numpy as np
from faker import Faker

from . import catalog as cat
from .taxonomy import (
    CLASSES,
    HARD_NEGATIVE_TYPES,
    N_ORDINARY,
    N_VENDORS,
    PER_CLASS,
    PER_HARD_NEGATIVE_TYPE,
)

MAX_AMOUNT = 4_500_000.0
MIN_AMOUNT = 3_000.0
# Clean invoices are kept clear of the structuring rule (4.1.2) with a margin
# wider than the guide values in the policy: no two invoices of one vendor that
# are both within NEAR_BAND of the same approval limit may lie within
# NEAR_DAYS of each other, unless they form a labelled J2 group.
NEAR_BAND = 0.20
NEAR_DAYS = 10


@dataclass
class Vendor:
    vendor_id: str
    name: str
    category: str
    state_code: str
    pan: str
    gstin: str
    prefix: str
    number_style: str
    weight: float
    blacklisted: bool = False
    gstin_status: str = "Active"

    @property
    def blocked(self) -> bool:
        return self.blacklisted or self.gstin_status != "Active"


def _label(kind: str = "clean") -> dict:
    return {
        "label": kind,              # clean | hard_negative | anomalous
        "class_id": "",
        "clauses": [],
        "group_id": "",
        "related_key": None,        # key of the original invoice (R3, J1)
        "hard_negative_type": "",
        "note": "",
    }


class Builder:
    def __init__(self, seed: int, policy: dict, start: date, end: date,
                 extra_band_limits: tuple[float, ...] = (), n_vendors: int = N_VENDORS,
                 n_blocked_vendors: int = 4, approver_counts: tuple[int, ...] = (8, 5, 3, 1)):
        self.seed = seed
        self.n_vendors = n_vendors
        self.n_blocked_vendors = n_blocked_vendors
        self.approver_counts = approver_counts
        self.rng = np.random.default_rng(seed)
        self.fake = Faker("en_IN")
        self.fake.seed_instance(seed)
        self.policy = policy
        c = policy["clauses"]
        self.tol = c["2.1.1"]["params"]["amount_tolerance_pct"] / 100.0
        self.max_per_day = int(c["4.1.1"]["params"]["max_invoices_per_vendor_per_day"])
        self.round_multiple = int(c["4.3.1"]["params"]["round_amount_multiple"])
        self.window_days = int(c["4.1.2"]["params"]["guide_window_days"])
        self.band = c["4.1.2"]["params"]["guide_band_pct"] / 100.0
        self.gstin_len = int(c["3.1.1"]["params"]["gstin_length"])
        self.state_max = int(c["3.1.2"]["params"]["state_code_max"])
        limits = c["5.1.1"]["params"]["approval_limits"]
        self.limits = dict(sorted(limits.items(), key=lambda kv: kv[1]))
        self.roles = list(self.limits)
        self.band_limits = sorted(set(self.limits.values()) | set(extra_band_limits))

        n_days = (end - start).days + 1
        self.start, self.end = start, end
        self.days = [start + timedelta(days=i) for i in range(n_days)]
        self.weekdays = [d for d in self.days if d.weekday() < 5]
        self.weekends = [d for d in self.days if d.weekday() >= 5]

        self.occupancy: dict[tuple[str, date], int] = {}
        self.locked: set[tuple[str, date]] = set()
        self.near: dict[tuple[str, float], list[date]] = {}
        self.txns: list[dict] = []
        self.group_counter: dict[str, int] = {}

        self.vendors = self._make_vendors()
        self.normal_vendors = [v for v in self.vendors if not v.blocked]
        w = np.array([v.weight for v in self.normal_vendors])
        self.normal_weights = w / w.sum()
        self.approvers = self._make_approvers()

    # ------------------------------------------------------------------ utils
    def pick(self, seq):
        return seq[int(self.rng.integers(len(seq)))]

    def uniform(self, lo: float, hi: float) -> float:
        return float(self.rng.uniform(lo, hi))

    def chance(self, p: float) -> bool:
        return bool(self.rng.random() < p)

    def is_round(self, amount: float) -> bool:
        return round(amount * 100) % (self.round_multiple * 100) == 0

    def next_group(self, prefix: str) -> str:
        self.group_counter[prefix] = self.group_counter.get(prefix, 0) + 1
        return f"{prefix}-{self.group_counter[prefix]:02d}"

    def shift_weekday(self, d: date, step: int = -1) -> date:
        while d.weekday() >= 5:
            d += timedelta(days=step)
        return d

    def add_business_days(self, d: date, n: int) -> date:
        while n > 0:
            d += timedelta(days=1)
            if d.weekday() < 5:
                n -= 1
        return d

    # ------------------------------------------------------- master records
    def _make_vendors(self) -> list[Vendor]:
        cats = list(cat.CATEGORIES)
        letters = string.ascii_uppercase
        alnum = string.ascii_uppercase + string.digits
        vendors, names, prefixes = [], set(), set()
        for i in range(self.n_vendors):
            name = self.fake.company()
            while name in names:
                name = self.fake.company()
            names.add(name)
            state = self.pick(list(cat.STATES))
            pan = (
                "".join(self.pick(letters) for _ in range(5))
                + "".join(self.pick(string.digits) for _ in range(4))
                + self.pick(letters)
            )
            gstin = state + pan + str(int(self.rng.integers(1, 10))) + "Z" + self.pick(alnum)
            prefix = "".join(ch for ch in name.upper() if ch in letters)[:3]
            while len(prefix) < 3 or prefix in prefixes:
                prefix = "".join(self.pick(letters) for _ in range(3))
            prefixes.add(prefix)
            vendors.append(
                Vendor(
                    vendor_id=f"VEND{1001 + i}",
                    name=name,
                    category=cats[i % len(cats)],
                    state_code=state,
                    pan=pan,
                    gstin=gstin,
                    prefix=prefix,
                    number_style=self.pick(cat.NUMBER_STYLES),
                    weight=float(self.rng.lognormal(0.0, 0.6)),
                )
            )
        # A few vendors are blocked (four by default): half blacklisted, half with
        # a suspended registration. They receive only the R9 invoices.
        blocked = [int(i) for i in self.rng.choice(self.n_vendors, size=self.n_blocked_vendors, replace=False)]
        half = self.n_blocked_vendors // 2
        for i in blocked[:half]:
            vendors[i].blacklisted = True
        for i in blocked[half:]:
            vendors[i].gstin_status = "Suspended"
        return vendors

    def _make_approvers(self) -> dict[str, list[str]]:
        head_counts = list(self.approver_counts)
        roster, used = {}, set()
        for idx, role in enumerate(self.roles):
            n = head_counts[idx] if idx < len(head_counts) else 1
            people = []
            while len(people) < n:
                name = self.fake.name()
                if name not in used:
                    used.add(name)
                    people.append(name)
            roster[role] = people
        return roster

    # ---------------------------------------------------------- placement
    def near_limits(self, amount: float) -> list[float]:
        return [L for L in self.band_limits if (1 - NEAR_BAND) * L <= amount <= L]

    def is_free(self, vendor: Vendor, d: date, amount: float, cap: int | None = None) -> bool:
        cap = self.max_per_day if cap is None else cap
        key = (vendor.vendor_id, d)
        if key in self.locked or self.occupancy.get(key, 0) >= cap:
            return False
        for L in self.near_limits(amount):
            for other in self.near.get((vendor.vendor_id, L), []):
                if abs((other - d).days) <= NEAR_DAYS:
                    return False
        return True

    def commit(self, vendor: Vendor, d: date, amount: float) -> None:
        key = (vendor.vendor_id, d)
        self.occupancy[key] = self.occupancy.get(key, 0) + 1
        for L in self.near_limits(amount):
            self.near.setdefault((vendor.vendor_id, L), []).append(d)

    def place(self, vendor: Vendor, amount: float, candidates: list[date] | None = None) -> date | None:
        candidates = self.weekdays if candidates is None else candidates
        if not candidates:
            return None
        for _ in range(400):
            d = self.pick(candidates)
            if self.is_free(vendor, d, amount):
                return d
        return None

    # --------------------------------------------------------------- specs
    def pick_vendor(self) -> Vendor:
        return self.normal_vendors[int(self.rng.choice(len(self.normal_vendors), p=self.normal_weights))]

    def draw_spec(self, vendor: Vendor | None = None, target: tuple[float, float] | None = None,
                  goods_only: bool = False, min_qty: int = 1, units: tuple[str, ...] | None = None,
                  min_price: float | None = None,
                  max_price: float | None = None) -> tuple[Vendor, cat.Item, int, float]:
        """Draw (vendor, item, quantity, unit price) for one purchase.

        With ``target`` the amount lands inside the given range; otherwise it
        follows the log-normal distribution of the vendor's category.
        """
        for _ in range(5000):
            v = vendor or self.pick_vendor()
            c = cat.CATEGORIES[v.category]
            if target is None:
                want = float(np.clip(self.rng.lognormal(np.log(c.median_amount), c.sigma),
                                     MIN_AMOUNT, MAX_AMOUNT))
            else:
                want = self.uniform(*target)
            items = [
                it for it in cat.ITEMS_BY_CATEGORY[v.category]
                if it.price_low * min_qty <= want
                and (not goods_only or it.goods)
                and (units is None or it.unit in units)
                and (min_price is None or it.price_low >= min_price)
                and (max_price is None or it.price_high <= max_price)
            ]
            if not items:
                continue
            item = self.pick(items)
            price = round(self.uniform(item.price_low, item.price_high), 2)
            qty = max(min_qty, int(round(want / price)))
            if target is not None:
                price = round(want / qty, 2)
            amount = round(qty * price, 2)
            if amount > MAX_AMOUNT or self.is_round(amount):
                continue
            if target is not None and not (target[0] <= amount <= target[1]):
                continue
            return v, item, qty, price
        raise RuntimeError("could not draw a purchase specification")

    def render_invoice_text(self, item: cat.Item, qty: int) -> str:
        tpl = self.pick(cat.INVOICE_TEXT_TEMPLATES)
        return tpl.format(po=item.po_text, alt=item.alt_text, qty=qty, unit=item.unit)

    def adequate_role(self, amount: float) -> str:
        for role, limit in self.limits.items():
            if amount <= limit:
                return role
        raise RuntimeError(f"amount {amount} exceeds every approval limit")

    def make_approvals(self, amount: float, when: date, role: str | None = None,
                       approver: str | None = None, allow_chain: bool = True) -> list[dict]:
        if role is None:
            idx = self.roles.index(self.adequate_role(amount))
            if idx + 1 < len(self.roles) and self.chance(0.15):
                idx += 1
            role = self.roles[idx]
        idx = self.roles.index(role)
        approver = approver or self.pick(self.approvers[role])
        day = self.add_business_days(when, int(self.rng.integers(1, 5)))
        final = datetime(day.year, day.month, day.day, int(self.rng.integers(13, 18)), int(self.rng.integers(0, 60)))
        entries = []
        # A lower role sometimes forwards the invoice before the approval. The
        # forwarding entry is not an approval (SOP section 5.1).
        if allow_chain and idx >= 1 and self.chance(0.25):
            lower = self.roles[idx - 1]
            entries.append({
                "approver_name": self.pick(self.approvers[lower]),
                "approver_role": lower,
                "timestamp": datetime(day.year, day.month, day.day, int(self.rng.integers(9, 12)), int(self.rng.integers(0, 60))),
                "action_taken": "Escalated",
                "amount_limit": self.limits[lower],
            })
        entries.append({
            "approver_name": approver,
            "approver_role": role,
            "timestamp": final,
            "action_taken": "Approved",
            "amount_limit": self.limits[role],
        })
        return entries

    def build(self, vendor: Vendor, item: cat.Item, qty: int, po_price: float, *,
              inv_price: float | None = None, when: date | None = None,
              candidates: list[date] | None = None, role: str | None = None,
              approver: str | None = None, allow_chain: bool = True,
              text_suffix: str = "") -> dict | None:
        """Create one invoice with its own PO, GRN and approval entries."""
        inv_price = po_price if inv_price is None else inv_price
        inv_amount = round(qty * inv_price, 2)
        po_amount = round(qty * po_price, 2)
        if when is None:
            when = self.place(vendor, inv_amount, candidates)
            if when is None:
                return None
        self.commit(vendor, when, inv_amount)

        po_date = self.shift_weekday(when - timedelta(days=int(self.rng.integers(12, 46))))
        receipt = self.shift_weekday(when - timedelta(days=int(self.rng.integers(1, 9))))
        if receipt <= po_date:
            receipt = self.add_business_days(po_date, 1)
        remarks = cat.BENIGN_REMARKS_GOODS if item.goods else cat.BENIGN_REMARKS_SERVICES
        txn = {
            "key": len(self.txns),
            "vendor": vendor,
            "date": when,
            "item": item,
            "invoice": {
                "quantity": qty,
                "unit_price": inv_price,
                "amount": inv_amount,
                "gstin": vendor.gstin,
                "description": self.render_invoice_text(item, qty) + text_suffix,
                "number": None,
                "dangling_po": False,
            },
            "po": {
                "po_date": po_date,
                "quantity": qty,
                "unit_price": po_price,
                "amount": po_amount,
                "description": item.po_text + text_suffix,
                "vendor": vendor,
                "requester": self.fake.name(),
            },
            "grn": {
                "receipt_date": receipt,
                "ordered_quantity": qty,
                "received_quantity": qty,
                "unit_price": po_price,
                "notes": self.pick(remarks) if self.chance(0.45) else "",
                "vendor": vendor,
                "received_by": self.fake.name(),
            },
            "approvals": self.make_approvals(inv_amount, when, role, approver, allow_chain),
            "label": _label(),
        }
        self.txns.append(txn)
        return txn

    def clean(self, **spec_kwargs) -> dict:
        """One ordinary clean invoice on a free weekday."""
        while True:
            vendor, item, qty, price = self.draw_spec(**spec_kwargs)
            txn = self.build(vendor, item, qty, price)
            if txn is not None:
                return txn

    @staticmethod
    def mark(txn: dict, class_id: str, clauses: list[str], note: str, group_id: str = "",
             related_key: int | None = None) -> None:
        """Record the label of an injected anomaly."""
        assert txn["label"]["label"] == "clean", "an invoice carries at most one injection"
        assert set(clauses) <= set(CLASSES[class_id].clauses)
        txn["label"].update(label="anomalous", class_id=class_id, clauses=list(clauses),
                            note=note, group_id=group_id, related_key=related_key)

    @staticmethod
    def mark_hard_negative(txn: dict, kind: str, note: str, group_id: str = "") -> None:
        assert txn["label"]["label"] == "clean" and kind in HARD_NEGATIVE_TYPES
        txn["label"].update(label="hard_negative", hard_negative_type=kind, note=note, group_id=group_id)

    # ------------------------------------------------- group constructions
    def free_day(self, vendor: Vendor) -> date:
        """A weekday on which the vendor has no invoice yet."""
        for _ in range(2000):
            d = self.pick(self.weekdays)
            key = (vendor.vendor_id, d)
            if key not in self.locked and self.occupancy.get(key, 0) == 0:
                return d
        raise RuntimeError("no free day")

    def same_day_group(self, size: int) -> list[dict]:
        """`size` invoices of one vendor dated on one day; the day is then closed."""
        vendor = self.pick_vendor()
        day = self.free_day(vendor)
        group = []
        while len(group) < size:
            _, item, qty, price = self.draw_spec(vendor=vendor)
            amount = round(qty * price, 2)
            if not self.is_free(vendor, day, amount, cap=size):
                continue
            group.append(self.build(vendor, item, qty, price, when=day))
        self.locked.add((vendor.vendor_id, day))
        return group

    def inject_r6(self, total: int = PER_CLASS, small: int | None = None, large: int | None = None) -> None:
        small = small or self.max_per_day + 1
        large = large or self.max_per_day + 2
        for size in self.group_sizes(total, small, large):
            gid = self.next_group("R6")
            for txn in self.same_day_group(size):
                self.mark(txn, "R6", ["4.1.1"], group_id=gid,
                          note=f"{size} invoices of the vendor dated {txn['date']}; daily limit {self.max_per_day}")

    @staticmethod
    def group_sizes(total: int, small: int, large: int) -> list[int]:
        for n_large in range(total // large + 1):
            rest = total - n_large * large
            if rest % small == 0:
                return [small] * (rest // small) + [large] * n_large
        raise RuntimeError(f"cannot split {total} into groups of {small} or {large}")

    def hn_daily_limit(self, total: int = PER_HARD_NEGATIVE_TYPE) -> None:
        size = self.max_per_day
        assert total % size == 0
        for _ in range(total // size):
            gid = self.next_group("HN-DAY")
            for txn in self.same_day_group(size):
                self.mark_hard_negative(txn, "HN_DAILY_LIMIT", group_id=gid,
                                        note=f"{size} invoices of the vendor on {txn['date']}; daily limit {self.max_per_day}")

    def inject_j2(self, total: int = PER_CLASS, size: int = 3) -> None:
        assert total % size == 0
        made = 0
        while made < total // size:
            role = self.pick(self.roles[:2])
            limit = self.limits[role]
            lower = (1 - self.band) * limit
            # Unit price small enough for several distinct quantities inside
            # the band, large enough for the quantities to stay plausible.
            vendor, item, _, price = self.draw_spec(target=(0.87 * limit, 0.985 * limit),
                                                    min_price=0.002 * limit, max_price=0.04 * limit)
            # Three different business days inside the guide window.
            first = self.pick(self.weekdays)
            span = [d for d in self.weekdays if 0 <= (d - first).days < self.window_days]
            if len(span) < size:
                continue
            days = sorted(span[int(i)] for i in self.rng.choice(len(span), size=size, replace=False))
            quantities = []
            for _ in range(size):
                qty = int(self.uniform(0.87 * limit, 0.985 * limit) // price)
                amount = round(qty * price, 2)
                if lower < amount < limit and not self.is_round(amount):
                    quantities.append(qty)
            if len(quantities) < size:
                continue
            amounts = [round(q * price, 2) for q in quantities]
            if not all(self.is_free(vendor, d, a) for d, a in zip(days, amounts)):
                continue
            gid = self.next_group("J2")
            approver = self.pick(self.approvers[role])
            for d, qty in zip(days, quantities):
                txn = self.build(vendor, item, qty, price, when=d, role=role, approver=approver)
                self.mark(txn, "J2", ["4.1.2"], group_id=gid,
                          note=(f"{size} invoices for '{item.po_text}' on {days[0]}..{days[-1]}, each below the "
                                f"{role} limit {limit:,.0f}; total {sum(amounts):,.2f}"))
            made += 1

    def hn_similar_number(self, total: int = PER_HARD_NEGATIVE_TYPE) -> None:
        assert total % 2 == 0
        made = 0
        while made < total // 2:
            vendor, item, qty, price = self.draw_spec()
            amount = round(qty * price, 2)
            if self.near_limits(amount):
                continue
            first = self.place(vendor, amount)
            if first is None:
                continue
            second = self.add_business_days(first, int(self.rng.integers(1, 5)))
            if second > self.end or not self.is_free(vendor, second, amount):
                continue
            gid = self.next_group("HN-NUM")
            pair = [self.build(vendor, item, qty, price, when=d) for d in (first, second)]
            pair[1]["follows"] = pair[0]["key"]
            for txn in pair:
                self.mark_hard_negative(txn, "HN_SIMILAR_NUMBER", group_id=gid,
                                        note="two separate deliveries of the same order size; separate POs and GRNs")
            made += 1

    def hn_recurring(self, total: int = PER_HARD_NEGATIVE_TYPE, months: int | None = None) -> None:
        # Series of eight months where the total allows it, otherwise another length.
        months = months or next(m for m in (8, 12, 6, 10, 4) if total % m == 0)
        assert total % months == 0
        made = 0
        while made < total // months:
            vendor, item, qty, price = self.draw_spec(units=("months", "guard-months"))
            amount = round(qty * price, 2)
            if self.near_limits(amount):
                continue
            first_month = int(self.rng.integers(0, 12 - months + 1))
            dom = int(self.rng.integers(3, 26))
            days = []
            for m in range(months):
                month_index = (self.start.month - 1) + first_month + m
                year = self.start.year + month_index // 12
                d = self.shift_weekday(date(year, month_index % 12 + 1, dom), step=1)
                while not self.is_free(vendor, d, amount):
                    d = self.add_business_days(d, 1)
                days.append(d)
            if days[-1] > self.end:
                continue
            gid = self.next_group("HN-REC")
            for d in days:
                txn = self.build(vendor, item, qty, price, when=d, text_suffix=f", {d:%b %Y}")
                self.mark_hard_negative(txn, "HN_RECURRING", group_id=gid,
                                        note=f"monthly charge of {amount:,.2f}; separate PO and GRN each month")
            made += 1

    # ------------------------------------------------ single-invoice cases
    def hn_tolerance(self, total: int = PER_HARD_NEGATIVE_TYPE) -> None:
        made = 0
        while made < total:
            vendor, item, qty, price = self.draw_spec()
            sign = 1 if self.chance(0.7) else -1
            inv_price = round(price * (1 + sign * self.uniform(0.2, 0.9) * self.tol), 2)
            po_amount, inv_amount = round(qty * price, 2), round(qty * inv_price, 2)
            variance = abs(inv_amount - po_amount) / po_amount
            if not (0.1 * self.tol <= variance <= 0.95 * self.tol) or self.is_round(inv_amount):
                continue
            txn = self.build(vendor, item, qty, price, inv_price=inv_price)
            if txn is None:
                continue
            self.mark_hard_negative(txn, "HN_TOLERANCE",
                                    note=f"invoice {inv_amount:,.2f} vs PO {po_amount:,.2f} ({variance:.2%}); tolerance {self.tol:.0%}")
            made += 1

    def hn_near_limit(self, total: int = PER_HARD_NEGATIVE_TYPE) -> None:
        made = 0
        while made < total:
            role = self.pick(self.roles[:3])
            limit = self.limits[role]
            vendor, item, qty, price = self.draw_spec(target=(0.990 * limit, 0.9995 * limit))
            txn = self.build(vendor, item, qty, price, role=role)
            if txn is None:
                continue
            self.mark_hard_negative(txn, "HN_NEAR_LIMIT",
                                    note=f"amount {txn['invoice']['amount']:,.2f} approved by {role} (limit {limit:,.0f})")
            made += 1

    def inject_r1(self, total: int = PER_CLASS, variance: tuple[float, float] | None = None) -> None:
        lo, hi = variance or (max(2 * self.tol, 0.02), 0.30)
        made = 0
        while made < total:
            vendor, item, qty, price = self.draw_spec()
            sign = 1 if self.chance(0.8) else -1
            inv_price = round(price * (1 + sign * self.uniform(lo, hi)), 2)
            po_amount, inv_amount = round(qty * price, 2), round(qty * inv_price, 2)
            diff = abs(inv_amount - po_amount) / po_amount
            if not (lo <= diff <= hi) or self.is_round(inv_amount) or inv_amount > MAX_AMOUNT:
                continue
            txn = self.build(vendor, item, qty, price, inv_price=inv_price)
            if txn is None:
                continue
            self.mark(txn, "R1", ["2.1.1"],
                      note=f"invoice {inv_amount:,.2f} vs PO {po_amount:,.2f} ({sign * diff:+.2%}); tolerance {self.tol:.0%}")
            made += 1

    def inject_r2(self, total: int = PER_CLASS) -> None:
        for _ in range(total):
            txn = self.clean(goods_only=True, min_qty=4)
            qty = txn["invoice"]["quantity"]
            short = int(self.rng.integers(1, max(2, int(0.4 * qty) + 1)))
            txn["grn"]["received_quantity"] = qty - short
            txn["grn"]["notes"] = self.pick(cat.SHORT_RECEIPT_REMARKS)
            self.mark(txn, "R2", ["2.1.2"], note=f"billed {qty}, received {qty - short}")

    def inject_r4(self, total: int = PER_CLASS) -> None:
        for i in range(total):
            txn = self.clean()
            good = txn["vendor"].gstin
            if i % 2 == 0:
                # Too short, or a character that is not alphanumeric. (A GSTIN
                # longer than 15 characters cannot be stored in schema_v3.)
                if self.chance(0.5):
                    bad = good[: self.gstin_len - int(self.rng.integers(1, 3))]
                else:
                    pos = int(self.rng.integers(2, self.gstin_len))
                    bad = good[:pos] + self.pick("-/ ") + good[pos + 1:]
                clause = "3.1.1"
            else:
                code = self.pick(["00", "99"] + [f"{n:02d}" for n in range(self.state_max + 1, 99)])
                bad = code + good[2:]
                clause = "3.1.2"
            txn["invoice"]["gstin"] = bad
            self.mark(txn, "R4", [clause], note=f"invoice GSTIN '{bad}'; vendor master '{good}'")

    def inject_r5(self, total: int = PER_CLASS) -> None:
        for _ in range(total):
            txn = self.clean()
            good = txn["vendor"].gstin
            if self.chance(0.5):
                other = self.pick([s for s in cat.STATES if s != good[:2]]) + good[2:]
            else:
                letters = string.ascii_uppercase
                pan = ("".join(self.pick(letters) for _ in range(5))
                       + "".join(self.pick(string.digits) for _ in range(4)) + self.pick(letters))
                other = good[:2] + pan + good[12:]
            assert other != good and len(other) == self.gstin_len and other.isalnum()
            txn["invoice"]["gstin"] = other
            self.mark(txn, "R5", ["3.1.3"], note=f"invoice GSTIN '{other}'; vendor master '{good}'")

    def inject_r7(self, total: int = PER_CLASS, role: str | None = None,
                  target: tuple[float, float] | None = None) -> None:
        made = 0
        while made < total:
            r = role or self.roles[int(self.rng.choice(3, p=[0.5, 0.35, 0.15]))]
            limit = self.limits[r]
            lo, hi = target or (1.05 * limit, min(2.5 * limit, MAX_AMOUNT))
            vendor, item, qty, price = self.draw_spec(target=(lo, hi))
            txn = self.build(vendor, item, qty, price, role=r)
            if txn is None:
                continue
            self.mark(txn, "R7", ["5.1.1"],
                      note=f"amount {txn['invoice']['amount']:,.2f} approved by {r} (limit {limit:,.0f})")
            made += 1

    def inject_r8(self, total: int = PER_CLASS) -> None:
        for i in range(total):
            txn = self.clean()
            variant = i % 3
            if variant == 0:
                txn["po"], txn["grn"] = None, None
                note = "no PO reference and no GRN reference"
            elif variant == 1:
                txn["grn"] = None
                note = "no GRN reference"
            else:
                txn["po"], txn["grn"] = None, None
                txn["invoice"]["dangling_po"] = True
                note = "PO reference matches no purchase order; no GRN reference"
            self.mark(txn, "R8", ["2.1.3"], note=note)

    def inject_r9(self, total: int = PER_CLASS) -> None:
        blocked = [v for v in self.vendors if v.blocked]
        for i in range(total):
            vendor = blocked[i % len(blocked)]
            txn = self.clean(vendor=vendor)
            status = "blacklisted" if vendor.blacklisted else f"GST registration {vendor.gstin_status}"
            self.mark(txn, "R9", ["4.4.1"], note=f"vendor {vendor.vendor_id} is {status}")

    def inject_r10(self, total: int = PER_CLASS) -> None:
        n_weekend = total // 2
        made = 0
        while made < n_weekend:
            vendor, item, qty, price = self.draw_spec()
            txn = self.build(vendor, item, qty, price, candidates=self.weekends)
            if txn is None:
                continue
            self.mark(txn, "R10", ["4.2.1"], note=f"invoice dated {txn['date']:%A %Y-%m-%d}")
            made += 1
        made = 0
        while made < total - n_weekend:
            amount = float(self.round_multiple * int(self.rng.integers(2, 91)))
            if self.near_limits(amount):
                continue
            vendor = self.pick_vendor()
            items = [it for it in cat.ITEMS_BY_CATEGORY[vendor.category] if it.price_low <= amount]
            if not items:
                continue
            item = self.pick(items)
            nominal = max(1, int(round(amount / self.uniform(item.price_low, item.price_high))))
            cents = int(round(amount * 100))
            qty = next(q for q in sorted(range(1, nominal + 1), key=lambda q: abs(q - nominal)) if cents % q == 0)
            price = cents / qty / 100
            assert round(qty * price, 2) == amount
            txn = self.build(vendor, item, qty, price)
            if txn is None:
                continue
            self.mark(txn, "R10", ["4.3.1"],
                      note=f"amount {amount:,.2f} is a multiple of {self.round_multiple:,}")
            made += 1

    def inject_j3(self, total: int = PER_CLASS) -> None:
        for _ in range(total):
            txn = self.clean()
            other = self.pick([it for it in cat.ITEMS if it.category != txn["item"].category])
            text = self.render_invoice_text(other, txn["invoice"]["quantity"])
            txn["invoice"]["description"] = text
            self.mark(txn, "J3", ["2.1.5"], note=f"invoice describes '{text}'; PO orders '{txn['item'].po_text}'")

    def inject_j4(self, total: int = PER_CLASS) -> None:
        for _ in range(total):
            txn = self.clean(goods_only=True, min_qty=4)
            qty = txn["invoice"]["quantity"]
            k = int(self.rng.integers(1, max(2, int(0.4 * qty) + 1)))
            remark = self.pick(cat.CONTRADICTING_REMARKS).format(k=k, a=qty - k, q=qty, unit=txn["item"].unit)
            txn["grn"]["notes"] = remark
            self.mark(txn, "J4", ["2.1.4"],
                      note=f"billed {qty}; received-quantity field {qty}; remark: '{remark}'")

    def duplicate_of(self, base: dict) -> dict | None:
        """A later invoice of the same vendor billing the same PO and GRN."""
        amount = base["invoice"]["amount"]
        window = [d for d in self.weekdays if 3 <= (d - base["date"]).days <= 40]
        when = self.place(base["vendor"], amount, window)
        if when is None:
            return None
        self.commit(base["vendor"], when, amount)
        txn = {
            "key": len(self.txns),
            "vendor": base["vendor"],
            "date": when,
            "item": base["item"],
            "invoice": dict(base["invoice"]),
            "po": base["po"],
            "grn": base["grn"],
            "approvals": self.make_approvals(amount, when),
            "label": _label(),
        }
        self.txns.append(txn)
        return txn

    def inject_duplicates(self, class_id: str, clause: str, total: int = PER_CLASS) -> None:
        pool = [t for t in self.txns
                if t["label"]["label"] == "clean" and not t.get("is_base") and t["po"] and t["grn"]]
        order = [int(i) for i in self.rng.permutation(len(pool))]
        made = 0
        for i in order:
            if made == total:
                break
            base = pool[i]
            dup = self.duplicate_of(base)
            if dup is None:
                continue
            base["is_base"] = True
            kind = "same invoice number" if class_id == "R3" else "re-keyed invoice number"
            self.mark(dup, class_id, [clause], related_key=base["key"],
                      note=f"{kind}; same vendor, PO, GRN and amount as an invoice dated {base['date']}")
            made += 1
        if made < total:
            raise RuntimeError(f"only {made} of {total} duplicates could be placed")

    # -------------------------------------------------------------- recipe
    def build_main(self, per_class: int = PER_CLASS, per_hard_negative: int = PER_HARD_NEGATIVE_TYPE,
                   n_ordinary: int = N_ORDINARY) -> None:
        """One dataset: ``per_class`` invoices of each anomaly class, ``per_hard_negative``
        of each hard-negative type, and ``n_ordinary`` ordinary clean invoices.

        The defaults give the benchmark of the paper: 420 anomalous, 120 hard
        negatives, 660 clean.
        """
        # Constructions that need particular days or amounts go first.
        self.inject_j2(per_class)
        self.inject_r6(per_class)
        self.hn_daily_limit(per_hard_negative)
        self.hn_recurring(per_hard_negative)
        self.hn_similar_number(per_hard_negative)
        self.hn_near_limit(per_hard_negative)
        self.hn_tolerance(per_hard_negative)
        self.inject_r9(per_class)
        self.inject_r7(per_class)
        self.inject_r1(per_class)
        self.inject_r2(per_class)
        self.inject_r4(per_class)
        self.inject_r5(per_class)
        self.inject_r8(per_class)
        self.inject_r10(per_class)
        self.inject_j3(per_class)
        self.inject_j4(per_class)
        for _ in range(n_ordinary):
            self.clean()
        # Duplicates copy an ordinary clean invoice, which stays clean.
        self.inject_duplicates("R3", "2.2.1", per_class)
        self.inject_duplicates("J1", "2.2.2", per_class)

    def build_boundary(self, other: dict, per_kind: int = 50, n_ordinary: int = 0) -> None:
        """Policy-swap boundary set, optionally inside a ledger of clean invoices.

        Every boundary invoice violates one clause under this builder's policy
        and is clean under ``other``, which differs in the amount tolerance, the
        daily invoice count and one approval limit. The ``n_ordinary`` other
        invoices are clean under both versions.
        """
        oc = other["clauses"]
        other_tol = oc["2.1.1"]["params"]["amount_tolerance_pct"] / 100.0
        other_max = int(oc["4.1.1"]["params"]["max_invoices_per_vendor_per_day"])
        other_limits = oc["5.1.1"]["params"]["approval_limits"]
        changed = [r for r in self.roles if other_limits[r] != self.limits[r]]
        assert other_tol > self.tol and other_max > self.max_per_day and len(changed) == 1
        role = changed[0]
        assert other_limits[role] > self.limits[role]

        self.inject_r6(per_kind, small=self.max_per_day + 1, large=other_max)
        self.inject_r7(per_kind, role=role,
                       target=(1.02 * self.limits[role], 0.98 * other_limits[role]))
        self.inject_r1(per_kind, variance=(1.2 * self.tol, 0.96 * other_tol))
        # Clean under this policy implies clean under the other one, which only
        # relaxes thresholds; the near-limit rule already covers both sets of limits.
        for _ in range(n_ordinary):
            self.clean()
