"""Static vocabulary of the generator: spending categories, items and remarks."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Item:
    category: str
    po_text: str        # wording used on the purchase order
    alt_text: str       # a different wording for the same goods or services
    unit: str
    price_low: float
    price_high: float
    goods: bool         # physical goods (countable at the dock) or a service


@dataclass(frozen=True)
class Category:
    name: str
    median_amount: float    # median invoice amount, INR
    sigma: float            # sigma of ln(amount)
    department: str


CATEGORIES: dict[str, Category] = {
    c.name: c
    for c in [
        Category("Logistics", 45_000, 0.9, "Supply Chain"),
        Category("IT Services", 180_000, 1.0, "Information Technology"),
        Category("Raw Materials", 250_000, 1.1, "Production"),
        Category("MRO", 30_000, 0.9, "Maintenance"),
        Category("Professional Services", 150_000, 0.9, "Finance"),
        Category("Utilities", 60_000, 0.8, "Administration"),
    ]
}

ITEMS: list[Item] = [
    # Logistics
    Item("Logistics", "Full truck load freight, Hyderabad to Pune", "FTL transport HYD-PNQ", "trips", 18_000, 32_000, False),
    Item("Logistics", "Part load freight, per tonne", "LTL carriage charges (per MT)", "tonnes", 2_200, 4_800, False),
    Item("Logistics", "Wooden export pallets, heat treated", "ISPM-15 wooden pallets", "pallets", 650, 1_400, True),
    Item("Logistics", "Stretch wrap film rolls, 23 micron", "Pallet wrapping film (23 mic) rolls", "rolls", 380, 720, True),
    Item("Logistics", "Corrugated shipping cartons, 5 ply", "5-ply corrugated boxes", "cartons", 45, 110, True),
    Item("Logistics", "Warehouse storage charges, per pallet position", "Pallet position rental, warehouse", "positions", 420, 900, False),
    # IT Services
    Item("IT Services", "Laptop computers, 14 inch, 16 GB RAM", "14-inch business notebooks (16GB)", "units", 58_000, 96_000, True),
    Item("IT Services", "LED monitors, 24 inch", "24-inch LED display units", "units", 9_500, 16_500, True),
    Item("IT Services", "Annual maintenance contract for servers", "Server AMC, yearly", "servers", 22_000, 48_000, False),
    Item("IT Services", "Software developer services, per person day", "Application development effort (person-days)", "days", 9_000, 17_000, False),
    Item("IT Services", "Network switches, 24 port managed", "Managed 24-port Ethernet switches", "units", 21_000, 44_000, True),
    Item("IT Services", "Endpoint security licences, annual", "Antivirus endpoint subscriptions (1 year)", "licences", 900, 2_400, False),
    # Raw Materials
    Item("Raw Materials", "Hot rolled steel coils, grade E250", "HR steel coil IS 2062 E250", "tonnes", 52_000, 64_000, True),
    Item("Raw Materials", "Aluminium ingots, 99.7 percent purity", "Primary aluminium ingot (P1020)", "tonnes", 205_000, 248_000, True),
    Item("Raw Materials", "Polypropylene granules, injection grade", "PP resin pellets, moulding grade", "tonnes", 96_000, 122_000, True),
    Item("Raw Materials", "Copper wire rods, 8 mm", "8 mm continuous cast copper rod", "tonnes", 720_000, 810_000, True),
    Item("Raw Materials", "Industrial solvent, isopropyl alcohol", "IPA solvent, technical grade", "drums", 14_000, 21_000, True),
    Item("Raw Materials", "Epoxy resin with hardener", "Two-part epoxy system (resin and hardener)", "kits", 3_800, 7_200, True),
    # MRO
    Item("MRO", "Deep groove ball bearings, 6205", "Bearings 6205-2RS", "pieces", 180, 420, True),
    Item("MRO", "Hydraulic oil, ISO VG 68", "VG-68 hydraulic fluid", "barrels", 16_000, 24_000, True),
    Item("MRO", "Safety helmets with chin strap", "Industrial hard hats (with chin strap)", "pieces", 240, 520, True),
    Item("MRO", "V-belts, B section", "B-section transmission belts", "pieces", 310, 680, True),
    Item("MRO", "Welding electrodes, E6013, 3.15 mm", "E6013 welding rods 3.15mm", "packets", 520, 940, True),
    Item("MRO", "Cutting tool inserts, carbide", "Carbide turning inserts", "boxes", 2_600, 5_400, True),
    # Professional Services
    Item("Professional Services", "Statutory audit fees", "Fees for statutory audit", "engagements", 140_000, 420_000, False),
    Item("Professional Services", "Legal advisory services, per hour", "Counsel fees (hourly)", "hours", 4_500, 12_000, False),
    Item("Professional Services", "Recruitment services, per hire", "Talent acquisition fee per position", "hires", 60_000, 140_000, False),
    Item("Professional Services", "Tax consultancy retainer", "Retainer for tax advisory", "months", 45_000, 110_000, False),
    Item("Professional Services", "Management training workshop, per day", "Leadership workshop facilitation (daily)", "days", 38_000, 85_000, False),
    Item("Professional Services", "Market research study", "Market survey and report", "studies", 180_000, 520_000, False),
    # Utilities
    Item("Utilities", "Diesel for generator sets", "HSD fuel for DG sets", "kilolitres", 86_000, 94_000, True),
    Item("Utilities", "Housekeeping services, monthly", "Facility cleaning contract (per month)", "months", 42_000, 96_000, False),
    Item("Utilities", "Security guard services, per guard month", "Manned guarding (guard-months)", "guard-months", 19_000, 27_000, False),
    Item("Utilities", "Drinking water jars, 20 litre", "20 L packaged water cans", "jars", 45, 90, True),
    Item("Utilities", "Industrial gas cylinders, oxygen", "Oxygen cylinders (industrial)", "cylinders", 380, 760, True),
    Item("Utilities", "Leased line internet, monthly rental", "Internet leased circuit rent (monthly)", "months", 28_000, 74_000, False),
]

ITEMS_BY_CATEGORY: dict[str, list[Item]] = {}
for _item in ITEMS:
    ITEMS_BY_CATEGORY.setdefault(_item.category, []).append(_item)

# Wording templates for the invoice description. All of them describe the same
# goods or services as the PO.
INVOICE_TEXT_TEMPLATES = [
    "{po}",
    "{po}, as per purchase order",
    "Supply of: {po}",
    "{alt}",
    "{alt} ({qty} {unit})",
    "Being charges towards {alt}",
]

# GRN remarks that confirm full acceptance.
BENIGN_REMARKS_GOODS = [
    "Received in good condition.",
    "Full quantity received and verified.",
    "Delivered to main stores; count verified.",
    "Outer cartons dented, contents intact; full quantity accepted.",
    "Delivered in two lots on the same day; total quantity matches the PO.",
    "QC passed; full quantity accepted.",
]
BENIGN_REMARKS_SERVICES = [
    "Service completion certificate signed by the user department.",
    "Work completed as per scope.",
    "Completion confirmed by the requester.",
]

# GRN remarks that reduce the accepted quantity (class J4). {k} units of {q}
# are not accepted; {a} = q - k.
CONTRADICTING_REMARKS = [
    "{k} {unit} rejected at QC and returned to the vendor.",
    "{k} {unit} found damaged in transit and not accepted.",
    "Short delivery: {k} {unit} not delivered; vendor to supply the balance.",
    "{k} {unit} returned to the vendor (wrong specification); accepted quantity {a}.",
    "Only {a} of {q} {unit} accepted; balance rejected on inspection.",
]

# Remarks for a GRN whose received-quantity field already shows the shortfall
# (class R2). They must not reduce the quantity a second time.
SHORT_RECEIPT_REMARKS = ["", "", "Partial receipt; quantity as recorded above."]

# State codes used for vendor GSTINs (all within 01-37).
STATES = {
    "07": ("Delhi", "New Delhi"),
    "09": ("Uttar Pradesh", "Noida"),
    "19": ("West Bengal", "Kolkata"),
    "24": ("Gujarat", "Ahmedabad"),
    "27": ("Maharashtra", "Pune"),
    "29": ("Karnataka", "Bengaluru"),
    "32": ("Kerala", "Kochi"),
    "33": ("Tamil Nadu", "Chennai"),
    "36": ("Telangana", "Hyderabad"),
}

# Invoice-number formats. {p} = vendor prefix, {fy} = financial year, {n} = sequence.
NUMBER_STYLES = [
    "{p}/{fy}/{n:05d}",
    "{p}-{n:06d}",
    "INV-{p}-{n:04d}",
    "{p}{n:05d}",
    "{p}/INV/{n:04d}",
]
