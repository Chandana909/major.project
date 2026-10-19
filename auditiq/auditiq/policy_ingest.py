"""Ingestion of policy PDFs into the policy store.

    python -m auditiq policy ingest policy/pdf/*.pdf

A PDF is read with its layout (font size, indentation, page), split into
chunks, and stored in policy_documents and policy_chunks:

    clause chunk   one numbered rule ("Rule 2.1.4 (HIGH), receipt remarks. ...")
    text chunk     the other text of a section (introductions, tables, procedures)

Every chunk keeps the page it starts on, so a finding can cite its source as
"document, page". When the document carries the version of a stored policy,
each clause chunk is compared with the wording of the clause registry; a clause
whose PDF text differs is reported and marked unverified, because the pipeline
would otherwise apply one text and show another.
"""
from __future__ import annotations

import hashlib
import re
from collections import Counter
from pathlib import Path

import pymupdf

from . import db
from .policy import clause_texts

CLAUSE_START = re.compile(r"^Rule (\d+(?:\.\d+)+) \((\w+)\),")
SECTION = re.compile(r"^(\d+(?:\.\d+)*)\.?\s+(\S.*)$")
VERSION = re.compile(r"Version:\s*(\d+(?:\.\d+)*)")
FOOTER = re.compile(r"\|\s*page \d+\s*$")


def squeeze(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def read_lines(path: Path) -> tuple[list[dict], int, str]:
    """Text lines of a PDF in reading order, each with page, font size and left edge."""
    lines = []
    with pymupdf.open(path) as doc:
        pages, title = doc.page_count, (doc.metadata or {}).get("title") or ""
        for number, page in enumerate(doc, start=1):
            page_lines = []
            for block in page.get_text("dict")["blocks"]:
                for line in block.get("lines", []):
                    text = "".join(span["text"] for span in line["spans"])
                    if not any(ch.isalnum() for ch in text):
                        continue                         # a bullet mark or an empty line
                    page_lines.append({"page": number, "text": text,
                                       "size": max(span["size"] for span in line["spans"]),
                                       "x": line["bbox"][0], "y": line["bbox"][1]})
            lines += sorted(page_lines, key=lambda entry: (round(entry["y"]), entry["x"]))
    return lines, pages, title


def chunk_lines(lines: list[dict]) -> tuple[list[dict], str]:
    """Split the lines of a document into clause chunks and text chunks.

    Returns the chunks and the header text that precedes the first section.
    """
    sizes = Counter()
    for line in lines:
        sizes[round(line["size"], 1)] += len(line["text"])
    body_size = sizes.most_common(1)[0][0]
    body = [line for line in lines if line["size"] >= body_size - 0.5 and not FOOTER.search(line["text"])]
    margin = min(line["x"] for line in body)

    chunks, header, current, section = [], [], None, ""
    heading_size = None

    def flush() -> None:
        nonlocal current
        if current and current["lines"]:
            current["text"] = squeeze(" ".join(current.pop("lines")))
            chunks.append(current)
        current = None

    for line in body:
        text = line["text"].strip()
        if line["size"] >= body_size + 1:
            # A heading; a heading that wraps continues at the same size.
            flush()
            if heading_size == line["size"] and current is None and chunks == [] and not SECTION.match(text):
                section = squeeze(f"{section} {text}")
            else:
                section = text
            heading_size = line["size"]
            continue
        heading_size = None
        indented = line["x"] > margin + 3
        start = CLAUSE_START.match(text)
        if start:
            flush()
            current = {"kind": "clause", "clause_id": start.group(1), "section": section, "page": line["page"],
                       "lines": [text], "x": line["x"]}
        elif current and current["kind"] == "clause" and indented:
            current["lines"].append(text)
        else:
            if current is None or current["kind"] == "clause":
                flush()
                if not SECTION.match(section):
                    header.append(text)                  # document header, before the first numbered section
                    continue
                current = {"kind": "text", "clause_id": None, "section": section, "page": line["page"], "lines": []}
            current["lines"].append(text)
    flush()
    for c in chunks:
        c.pop("x", None)
    return chunks, squeeze(" ".join(header))


def ingest(conn: db.Database, path: Path) -> dict:
    """Read one PDF into the policy store, replacing an earlier ingestion of the same file."""
    path = Path(path)
    lines, pages, title = read_lines(path)
    chunks, header = chunk_lines(lines)
    version_match = VERSION.search(header)
    version = version_match.group(1) if version_match else None

    stored = conn.execute("SELECT markdown_content FROM company_policies WHERE version = ?", (version,)).fetchone()
    expected = clause_texts(stored["markdown_content"]) if stored else {}
    is_policy = bool(expected) and any(c["kind"] == "clause" for c in chunks)
    for c in chunks:
        c["verified"] = None
        if c["kind"] == "clause" and is_policy:
            c["verified"] = int(expected.get(c["clause_id"]) == c["text"])

    conn.execute("DELETE FROM policy_documents WHERE file_name = ?", (path.name,))
    doc_id = conn.insert(
        "INSERT INTO policy_documents (file_name, title, version, pages, sha256, ingested_at) VALUES (?, ?, ?, ?, ?, ?)",
        (path.name, title or path.stem, version, pages, hashlib.sha256(path.read_bytes()).hexdigest(), db.now()),
        "doc_id")
    conn.executemany(
        "INSERT INTO policy_chunks (doc_id, version, position, kind, clause_id, section, page, text, verified) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [(doc_id, version if is_policy else None, i, c["kind"], c["clause_id"], c["section"], c["page"], c["text"],
          c["verified"]) for i, c in enumerate(chunks)])
    conn.commit()

    found = [c["clause_id"] for c in chunks if c["kind"] == "clause"]
    return {
        "file": path.name, "title": title or path.stem, "version": version, "pages": pages,
        "chunks": len(chunks), "clauses": len(found), "is_policy_version": is_policy,
        "unverified": [c["clause_id"] for c in chunks if c["verified"] == 0],
        "missing_clauses": sorted(set(expected) - set(found)) if is_policy else [],
    }


def clause_citations(conn: db.Database, version: str) -> dict[str, dict]:
    """For each clause of a policy version: the document and page it is on, and its text."""
    rows = conn.execute(
        "SELECT c.clause_id, c.page, c.text, c.verified, d.file_name FROM policy_chunks c "
        "JOIN policy_documents d ON d.doc_id = c.doc_id WHERE c.kind = 'clause' AND c.version = ?", (version,))
    return {r["clause_id"]: {"document": r["file_name"], "page": r["page"], "text": r["text"],
                             "verified": bool(r["verified"])} for r in rows}
