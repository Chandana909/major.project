"""Sample policy documents as PDF files.

    python -m auditiq policy make-pdfs

Writes to policy/pdf/:
    Procurement_Audit_SOP_v2.5.pdf, _v2.6.pdf   the policy text of each version
    Audit_Review_Procedure_v1.0.pdf             how audited invoices are scored, routed and reviewed

The PDFs are rendered from the same Markdown the pipeline reads, so they say
exactly what the system applies. They are the input of the document ingestion
(policy_ingest.py), which is how an organization's own policy PDFs would enter.
"""
from __future__ import annotations

import re
from pathlib import Path
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from .graph import PRESETS
from .policy import POLICY_DIR, Policy, load_policy
from .scoring import ScoringOptions

PDF_DIR = POLICY_DIR / "pdf"
BODY_SIZE = 10


def _styles() -> dict[str, ParagraphStyle]:
    base = getSampleStyleSheet()["Normal"]
    body = ParagraphStyle("body", parent=base, fontName="Helvetica", fontSize=BODY_SIZE, leading=14, spaceAfter=6)
    return {
        "body": body,
        "bullet": ParagraphStyle("bullet", parent=body, leftIndent=14, bulletIndent=2),
        "title": ParagraphStyle("title", parent=body, fontName="Helvetica-Bold", fontSize=17, leading=22, spaceAfter=10),
        "h1": ParagraphStyle("h1", parent=body, fontName="Helvetica-Bold", fontSize=13.5, leading=18,
                             spaceBefore=12, spaceAfter=6),
        "h2": ParagraphStyle("h2", parent=body, fontName="Helvetica-Bold", fontSize=11.5, leading=15,
                             spaceBefore=8, spaceAfter=4),
    }


def _inline(text: str) -> str:
    """Markdown bold and code spans to reportlab markup."""
    text = escape(text)
    text = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", text)
    return re.sub(r"`(.+?)`", r'<font face="Courier">\1</font>', text)


def markdown_to_flowables(markdown: str) -> list:
    """The subset of Markdown used by the policy texts: headings, bullets, one-level tables, paragraphs."""
    styles = _styles()
    flow, table = [], []

    def flush_table() -> None:
        if not table:
            return
        rows = [[Paragraph(_inline(cell), styles["body"]) for cell in row] for row in table]
        grid = Table(rows, colWidths=[70 * mm, 50 * mm], hAlign="LEFT")
        grid.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
                                  ("BACKGROUND", (0, 0), (-1, 0), colors.whitesmoke),
                                  ("VALIGN", (0, 0), (-1, -1), "TOP")]))
        flow.extend([grid, Spacer(1, 6)])
        table.clear()

    for raw in markdown.splitlines():
        line = raw.rstrip()
        if line.startswith("|"):
            cells = [c.strip() for c in line.strip("|").split("|")]
            if not all(re.fullmatch(r":?-+:?", c) for c in cells):
                table.append(cells)
            continue
        flush_table()
        if not line.strip():
            continue
        if line.startswith("### "):
            flow.append(Paragraph(_inline(line[4:]), styles["h2"]))
        elif line.startswith("## "):
            flow.append(Paragraph(_inline(line[3:]), styles["h1"]))
        elif line.startswith("# "):
            flow.append(Paragraph(_inline(line[2:]), styles["title"]))
        elif line.startswith("- "):
            flow.append(Paragraph(_inline(line[2:]), styles["bullet"], bulletText="•"))
        else:
            flow.append(Paragraph(_inline(line), styles["body"]))
    flush_table()
    return flow


def write_pdf(markdown: str, path: Path, title: str, footer: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)

    def draw_footer(canvas, doc) -> None:
        canvas.saveState()
        canvas.setFont("Helvetica", 8)
        canvas.setFillColor(colors.grey)
        canvas.drawString(22 * mm, 12 * mm, f"{footer} | page {doc.page}")
        canvas.restoreState()

    # invariant: no creation date or random id, so the same text gives the same file.
    doc = SimpleDocTemplate(str(path), pagesize=A4, leftMargin=22 * mm, rightMargin=22 * mm, topMargin=20 * mm,
                            bottomMargin=22 * mm, title=title, author="AuditIQ (synthetic policy)", invariant=1)
    doc.build(markdown_to_flowables(markdown), onFirstPage=draw_footer, onLaterPages=draw_footer)
    return path


def review_procedure_markdown() -> str:
    """The review procedure, with the numbers the scorer and the pipeline actually use."""
    options = ScoringOptions()
    values = {
        "tau": f"{options.tau:g}",
        "w_critical": options.weights["critical"], "w_high": options.weights["high"],
        "w_medium": options.weights["medium"], "w_low": options.weights["low"],
        "floor_critical": options.floors["critical"], "floor_high": options.floors["high"],
        "reruns": PRESETS["C5"].reruns,
    }
    template = (POLICY_DIR / "Review_Procedure_template.md").read_text(encoding="utf-8")
    return re.sub(r"\{\{(\w+)\}\}", lambda m: str(values[m.group(1)]), template)


def sop_pdf_name(version: str) -> str:
    return f"Procurement_Audit_SOP_v{version}.pdf"


def make_sample_pdfs(out: Path = PDF_DIR, versions: tuple[str, ...] = ("2.5", "2.6")) -> list[Path]:
    written = []
    for version in versions:
        policy: Policy = load_policy(version)
        name = policy.registry["policy_name"]
        written.append(write_pdf(policy.text, out / sop_pdf_name(version), f"{name}, version {version}",
                                 f"{name} | version {version}"))
    written.append(write_pdf(review_procedure_markdown(), out / "Audit_Review_Procedure_v1.0.pdf",
                             "Audit Review Procedure, version 1.0", "Audit Review Procedure | version 1.0"))
    return written
