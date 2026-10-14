"""The data dictionary: what every table and column of the database means.

The meanings are kept here, next to the schema, and docs/DATA_DICTIONARY.md is
generated from this module and from the schema in auditiq/db.py:

    python -m auditiq.datadict            writes docs/DATA_DICTIONARY.md

A test fails when a column has no description, when a description names a
column that no longer exists, or when the generated file is out of date.
"""
from __future__ import annotations

import re
from pathlib import Path

from . import db
from .extraction import GRN_FIELDS, INVOICE_FIELDS, LOG_FIELDS, PO_FIELDS, VENDOR_FIELDS

DOC = Path(__file__).resolve().parents[1] / "docs" / "DATA_DICTIONARY.md"

# Ledger columns the audit reads. Every other ledger column is carried for the
# reviewer, the dashboard and the copilot, and no control or agent sees it.
AUDITED = {"vendor_master": VENDOR_FIELDS, "purchase_orders": PO_FIELDS, "goods_receipts": GRN_FIELDS,
           "invoices": INVOICE_FIELDS, "approval_logs": LOG_FIELDS + ["transaction_id"]}

GROUPS = [
    ("Ledger", "The records under audit. They are loaded from the five CSV files of a dataset by "
               "`python -m auditiq setup --dataset <folder>` and are never changed by the audit.",
     ["vendor_master", "purchase_orders", "goods_receipts", "invoices", "approval_logs"]),
    ("Policy", "The policy the audit applies: the clause registry and the rendered text of every version, and the "
               "policy documents (PDF) cut into passages for retrieval.",
     ["company_policies", "policy_clauses", "policy_parameters", "policy_documents", "policy_chunks"]),
    ("Audit", "What the audit produced. Every audit of an invoice adds rows, so an invoice that is audited "
              "again has one result per run and the earlier ones remain. The only later change to a result "
              "is its review: the decision sets the status of the result, is added to its audit pack and "
              "closes its audit trail.",
     ["audit_runs", "audit_results", "audit_flags", "audit_trail", "review_decisions"]),
    ("Other", "", ["benchmark_labels", "meta"]),
]

TABLES: dict[str, dict] = {
    "vendor_master": {
        "summary": "One row per vendor.",
        "source": "`vendor_master.csv`",
        "used": "Extraction attaches the vendor to each of its invoices. Controls 3.1.3 and 4.4.1 read it, as do "
                "the Tax and Identity agent and the Vendor Intelligence agent.",
        "columns": {
            "vendor_id": "Vendor identifier: `VEND` and four digits.",
            "vendor_name": "Registered name of the vendor.",
            "official_gstin": "The GSTIN registered for the vendor: 15 characters, of which the first two are the "
                              "state code. Control 3.1.3 compares the GSTIN printed on an invoice with it.",
            "pan_number": "The vendor's PAN: characters 3 to 12 of the GSTIN.",
            "vendor_category": "One of Raw Materials, MRO, Logistics, IT Services, Utilities, Professional Services. "
                               "The category decides what the vendor sells and which department orders from it.",
            "city": "City of the registered address.",
            "state": "State of the registered address; it agrees with the state code of the GSTIN.",
            "country": "`India` for every vendor.",
            "gstin_status": "Status of the registration with the tax authority: `Active` or `Suspended`. A status "
                            "listed in parameter `blocked_gstin_statuses` of Rule 4.4.1 blocks the vendor.",
            "kyc_status": "`Verified` for every generated vendor.",
            "is_active": "1 for every generated vendor.",
            "blacklisted": "1 when the vendor is on the company's blacklist (Rule 4.4.1), otherwise 0.",
            "blacklist_status": "Copy of `blacklisted` under the column name of the prototype's schema.",
        },
    },
    "purchase_orders": {
        "summary": "One row per purchase order: what the company ordered from a vendor.",
        "source": "`purchase_orders.csv`",
        "used": "Extraction attaches the order an invoice refers to. Control 2.1.1 compares amounts, Rule 2.1.5 "
                "(Math and Approvals agent) compares descriptions.",
        "columns": {
            "po_id": "Order identifier: `PO` and five digits.",
            "vendor_id": "The vendor the order was placed with.",
            "po_date": "Date the order was issued. It precedes the receipt and the invoice.",
            "amount": "Value of the order before tax: `quantity` times `unit_price`. Control 2.1.1 compares the "
                      "invoice amount with it.",
            "po_amount": "Copy of `amount` under the column name of the prototype's schema.",
            "quantity": "Units ordered.",
            "unit_price": "Agreed price per unit, before tax.",
            "tax_amount": "GST at 18% of `amount`.",
            "total_amount": "`amount` plus `tax_amount`.",
            "currency": "`INR` for every order.",
            "department": "Department that raised the order; it follows from the vendor's category.",
            "requester": "Employee who raised the order.",
            "status": "`Closed` for every generated order.",
            "description": "What was ordered, in words. Rule 2.1.5 asks whether the invoice bills the same thing.",
        },
    },
    "goods_receipts": {
        "summary": "One row per goods receipt note (GRN): what the stores received against an order.",
        "source": "`goods_receipts.csv`",
        "used": "Extraction attaches the receipt an invoice refers to. Control 2.1.2 compares quantities, Rule 2.1.4 "
                "(Math and Approvals agent) reads the receiver's remark.",
        "columns": {
            "grn_id": "Receipt identifier: `GRN` and five digits.",
            "po_id": "The order the goods were received against.",
            "vendor_id": "The vendor that delivered.",
            "receipt_date": "Date of the receipt, between the order date and the invoice date.",
            "received_quantity": "Units accepted into stores. Control 2.1.2 compares the billed quantity with it.",
            "ordered_quantity": "Units on the order.",
            "unit_price": "Price per unit, as on the order.",
            "amount": "`received_quantity` times `unit_price`.",
            "received_amount": "Copy of `amount` under the column name of the prototype's schema.",
            "received_by": "Storekeeper who signed the receipt.",
            "warehouse_location": "`Main Stores` for every generated receipt.",
            "quality_check": "`Passed` for every generated receipt. What happened at a particular inspection is "
                             "written in `notes`.",
            "status": "`Complete` for every generated receipt.",
            "notes": "Free-text remark of the receiver, for example \"QC passed; full quantity accepted.\" or a "
                     "remark that some units were rejected. Rule 2.1.4 is violated when the remark contradicts "
                     "the quantity billed; only an agent can read that.",
        },
    },
    "invoices": {
        "summary": "One row per vendor invoice: the unit of audit.",
        "source": "`invoices.csv`",
        "used": "Every control and agent reads the invoice under audit. The other invoices of the same vendor are "
                "its vendor history, which the duplicate, splitting and structuring rules need.",
        "columns": {
            "invoice_id": "The company's identifier of the invoice: `INV` and five digits, in order of invoice date.",
            "vendor_id": "The vendor that sent the invoice.",
            "invoice_number": "The vendor's own number printed on the invoice. Its format differs from vendor to "
                              "vendor. Rule 2.2.1 (exact duplicate) and Rule 2.2.2 (near duplicate) compare it "
                              "with the vendor's other invoices.",
            "date": "Invoice date. Rules 4.1.1, 4.1.2 and 4.2.1 depend on it.",
            "invoice_date": "The same date as a timestamp at midnight, under the column name of the prototype's schema.",
            "due_date": "`date` plus 30 days.",
            "amount": "Billed value before tax. Rules 2.1.1, 4.1.2, 4.3.1 and 5.1.1 depend on it.",
            "invoice_amount": "Copy of `amount` under the column name of the prototype's schema.",
            "quantity": "Units billed. Control 2.1.2 compares it with the received quantity.",
            "unit_price": "Price per unit billed.",
            "currency": "`INR` for every invoice.",
            "tax_amount": "GST at 18% of `amount`.",
            "total_amount": "`amount` plus `tax_amount`.",
            "gstin": "The GSTIN printed on the invoice. Rules 3.1.1 to 3.1.3 check its form, its state code and "
                     "whether it is the vendor's registered one.",
            "po_id": "The order the invoice refers to. NULL when the invoice names none. It can name an order "
                     "that is not on record, which is why it is not a foreign key (Rule 2.1.3).",
            "grn_id": "The receipt the invoice refers to. NULL when the invoice names none (Rule 2.1.3).",
            "department": "Department the invoice is charged to.",
            "payment_terms": "`Net 30` for every invoice.",
            "payment_status": "`Unpaid` for every invoice: the audit runs before payment.",
            "approval_status": "State in the company's own approval workflow, `Approved` for every invoice: the "
                               "audit examines invoices that were approved. It is not the outcome of the audit; "
                               "that is `audit_results.workflow_status`.",
            "approved_by": "Name of the final approver, the last entry of the invoice in `approval_logs`.",
            "description": "What is billed, in words. Rule 2.1.5 compares it with the order's description.",
        },
    },
    "approval_logs": {
        "summary": "One row per step of the approval of an invoice. Most invoices have one entry, the approval. "
                   "Some have an `Escalated` entry before it: a lower role passing the invoice on to the role "
                   "that approved it.",
        "source": "`approval_logs.csv`",
        "used": "Extraction attaches the entries of an invoice, oldest first. Control 5.1.1 checks the final "
                "approver's limit; Rule 4.1.2 (Vendor Intelligence agent) reads who approved neighbouring invoices.",
        "columns": {
            "log_id": "Entry identifier: `LOG` and five digits, in order of time.",
            "transaction_id": "The invoice the entry belongs to (`invoices.invoice_id`).",
            "approver_name": "Name of the approver.",
            "approver_role": "`Manager`, `Senior Manager`, `Director` or `CFO`.",
            "timestamp": "When the approver acted.",
            "action_taken": "`Escalated` (passed on to a higher role) or `Approved` (final). Every invoice has "
                            "exactly one `Approved` entry, and it is the last.",
            "amount_limit": "The approval limit of the role as the approval system recorded it. Control 5.1.1 does "
                            "not use this column: it takes the limit of the role from the active policy, so that "
                            "a change of policy changes the decision.",
        },
    },
    "company_policies": {
        "summary": "One row per version of the policy.",
        "source": "`setup` (from `policy/policy_v<version>.json` and the text rendered from it), and "
                  "`python -m auditiq policy adopt <file.pdf>`, which reads a version from a policy document",
        "used": "The pipeline reads the active version when a run starts: the controls take their thresholds from "
                "`registry`, the agents read `markdown_content`.",
        "columns": {
            "version": "Version of the policy, for example `2.5`.",
            "policy_name": "Title of the policy.",
            "effective_date": "First day the version is in force.",
            "markdown_content": "The policy as text. This is what the agents read; it is rendered from the "
                                "registry, so a threshold appears in the text exactly as the controls apply it.",
            "registry": "The clause registry as JSON: every clause with its title, severity, kind and "
                        "parameters. The only place where thresholds are stored. A version that a model helped to "
                        "read from a document also records, under `adoption`, the model, the reviewer who "
                        "confirmed the values, the time, and which values the reviewer supplied.",
            "is_active": "1 for the version the audit applies, 0 for the others. Exactly one row has 1.",
        },
    },
    "policy_clauses": {
        "summary": "One row per clause of each policy version; the registry of `company_policies` in relational form.",
        "source": "With the policy version: `setup` or `policy adopt`",
        "used": "The dashboard and the copilot. The pipeline reads the registry itself.",
        "columns": {
            "version": "Policy version.",
            "clause_id": "Number of the clause, for example `2.1.1`. Findings cite it as \"Rule 2.1.1\".",
            "title": "Short title of the clause.",
            "severity": "`low`, `medium`, `high` or `critical`. Every clause has one severity; a finding takes the "
                        "severity of the clause it cites.",
            "kind": "`control` when a comparison of fields decides the clause, so that code checks it; `judgement` "
                    "when deciding it needs reading, so that an agent checks it.",
        },
    },
    "policy_parameters": {
        "summary": "One row per parameter of a clause: the thresholds of the policy.",
        "source": "With the policy version: `setup` or `policy adopt`",
        "used": "The dashboard shows them and compares versions. The controls read the same values from the registry.",
        "columns": {
            "version": "Policy version.",
            "clause_id": "The clause the parameter belongs to.",
            "param_name": "Name of the parameter, for example `amount_tolerance_pct` or `approval_limits`.",
            "param_value": "The value, JSON-encoded: a number, a list, or an object such as the limit of each role.",
        },
    },
    "policy_documents": {
        "summary": "One row per ingested policy document (PDF).",
        "source": "`python -m auditiq policy ingest <file.pdf>` and `policy adopt <file.pdf>`; `setup` ingests the "
                  "PDFs in `policy/pdf`",
        "used": "Citations name the document and the page of a passage.",
        "columns": {
            "doc_id": "Identifier of the document.",
            "file_name": "File name of the PDF. Ingesting a file of the same name again replaces the document.",
            "title": "Title found on the first page.",
            "version": "Policy version the document states, when it states one.",
            "pages": "Number of pages.",
            "sha256": "SHA-256 of the file, so that the exact document a citation refers to can be identified.",
            "ingested_at": "When the document was ingested.",
        },
    },
    "policy_chunks": {
        "summary": "One row per passage of a policy document: a clause, or a paragraph that is not a clause.",
        "source": "Policy ingestion and adoption; `python -m auditiq policy embed` fills the embedding columns",
        "used": "Policy search and the copilot retrieve passages; an audit pack cites the page of each clause it uses.",
        "columns": {
            "chunk_id": "Identifier of the passage.",
            "doc_id": "The document the passage comes from.",
            "version": "Policy version of the document.",
            "position": "Position of the passage in the document, from 0.",
            "kind": "`clause` for a numbered rule, `text` for any other paragraph.",
            "clause_id": "Number of the clause, for a passage of kind `clause`.",
            "section": "Heading of the section the passage stands under.",
            "page": "Page of the PDF on which the passage begins, from 1.",
            "text": "Text of the passage as extracted from the PDF.",
            "verified": "For a clause: 1 when the text extracted from the PDF equals the text of that clause in "
                        "the registry of the same version, 0 when it differs. NULL for other passages, and for "
                        "the passages a model located in a policy written in its own wording. A clause "
                        "that is not verified is reported at ingestion, because the PDF and the applied policy "
                        "then disagree.",
            "embedding": "Embedding of the passage: a vector of 32-bit floats of unit length, stored as bytes. "
                         "NULL until `policy embed` has run.",
            "embed_model": "Identifier of the model that produced the embedding.",
        },
    },
    "audit_runs": {
        "summary": "One row per run: one configuration applied to a set of invoices under one policy version.",
        "source": "`python -m auditiq run`, `audit`, and the dashboard",
        "used": "Everything that reports a result names its run, so that the configuration, the policy version, "
                "the model and the prompts behind a decision are known.",
        "columns": {
            "run_id": "Identifier of the run.",
            "configuration": "`C1` to `C5`: which stages of the pipeline ran.",
            "policy_version": "The policy version that was applied.",
            "model": "Identifier of the chat model. NULL for C1, which calls no model.",
            "prompt_hash": "Hash of the prompt templates. NULL for C1.",
            "note": "Free text given when the run was started.",
            "started_at": "When the run started.",
            "finished_at": "When the run finished. NULL while it is running or if it was interrupted.",
        },
    },
    "audit_results": {
        "summary": "One row per invoice per run: the decision of the audit.",
        "source": "The pipeline, at the end of each invoice",
        "used": "The review queue, the dashboard, the copilot.",
        "columns": {
            "result_id": "Identifier of the result.",
            "run_id": "The run that produced it.",
            "invoice_id": "The invoice that was audited.",
            "vendor_id": "Its vendor, repeated here so that results can be grouped without a join.",
            "route": "`approve` (no review), `sample` (the count-based score reaches the threshold but the "
                     "confidence-weighted score does not: a share of these is reviewed) or `escalate` (review).",
            "risk_level": "`LOW`, `MEDIUM` (score 30 or more), `HIGH` (50 or more) or `CRITICAL` (70 or more), from `rc`.",
            "r0": "Count-based risk score, 0 to 100: every finding counts fully.",
            "rc": "Confidence-weighted risk score, 0 to 100: every finding counts in proportion to its "
                  "confidence. Never above `r0`. Equal to `r0` in a configuration without confidence scoring.",
            "flag_count": "Number of findings that were kept.",
            "workflow_status": "`AUTO_APPROVED`, `PENDING_REVIEW`, `NOT_SAMPLED` (route `sample`, not drawn for "
                               "review), or after review `REVIEW_APPROVED`, `REVIEW_REJECTED`, `REVIEW_OVERRIDDEN`.",
            "llm_calls": "Number of model calls made for this invoice, including calls served from the cache.",
            "prompt_tokens": "Tokens sent to the model.",
            "completion_tokens": "Tokens the model returned.",
            "latency_ms": "Time the model took, in milliseconds.",
            "failed_stages": "Stages whose reply could not be used even after one request to repair it. A failed "
                             "stage contributes no finding; the others continue.",
            "audit_pack": "The complete result as JSON: the records examined, every finding with its evidence and "
                          "its confidence, the findings the challenger removed and why, the scores, the route, "
                          "the policy citations and, after review, the decision.",
            "created_at": "When the result was stored.",
        },
    },
    "audit_flags": {
        "summary": "One row per finding of a result, including findings the challenger removed.",
        "source": "The pipeline, with the result",
        "used": "The dashboard and the copilot; the same findings are inside `audit_results.audit_pack`.",
        "columns": {
            "flag_id": "Identifier of the finding.",
            "result_id": "The result the finding belongs to.",
            "clause": "The clause the finding cites, for example `2.1.1`.",
            "severity": "Severity of that clause.",
            "source": "`D` for a deterministic control, `L` for an agent (LLM).",
            "agent": "Name of the control or of the agent that raised the finding.",
            "status": "`kept`, or `removed` when the challenger rejected the finding.",
            "g": "Grounding, 1 or 0: every piece of evidence the finding quotes is found in the records with "
                 "that value. NULL for a control or when confidence was not computed.",
            "p": "Clause validity, 1 or 0: the cited clause exists in the active policy. NULL as for `g`.",
            "a": "Agreement, 0 to 1: the share of the agent's re-runs that cite the same clause again. NULL as for `g`.",
            "confidence": "Mean of `g`, `p` and `a`. 1 for a control and in a configuration without confidence scoring.",
            "message": "The finding in words.",
            "evidence": "JSON list of the quoted evidence: `{\"field\": \"grn.notes\", \"value\": \"...\"}`.",
            "removal_reason": "The challenger's reason, for a removed finding.",
        },
    },
    "audit_trail": {
        "summary": "One row per step taken for a result, in order: what ran, who or what did it, and what it cost.",
        "source": "The pipeline, with the result; the review adds its own entry",
        "used": "`python -m auditiq show`, the dashboard. It answers \"how was this decision reached\".",
        "columns": {
            "entry_id": "Identifier of the entry.",
            "result_id": "The result the entry belongs to.",
            "seq": "Order of the entry within the result, from 1.",
            "stage": "`extraction`, `controls`, `agent`, `challenger`, `rerun`, `scoring` or `review`.",
            "actor": "`code` for a deterministic stage, the name of the agent for a model call, the reviewer's "
                     "name for a review.",
            "detail": "What happened: the number of findings, whether the reply was valid, whether it came from "
                      "the cache, the scores and the route, or the decision.",
            "prompt_tokens": "Tokens sent, for a model call.",
            "completion_tokens": "Tokens returned, for a model call.",
            "latency_ms": "Time the call took, in milliseconds.",
        },
    },
    "review_decisions": {
        "summary": "One row per decision of a human reviewer on a result that was waiting for review.",
        "source": "`python -m auditiq decide`, and the review page of the dashboard",
        "used": "The dashboard; the decision is also written into the audit pack and the audit trail.",
        "columns": {
            "decision_id": "Identifier of the decision.",
            "result_id": "The result that was reviewed.",
            "decision": "`approve` (the invoice may be paid), `reject` (the findings stand; the invoice is not "
                        "paid) or `override` (the reviewer sets the audit's findings aside).",
            "reviewer": "Name of the reviewer. Required.",
            "justification": "The reviewer's reason. Required for an override.",
            "decided_at": "When the decision was recorded.",
        },
    },
    "benchmark_labels": {
        "summary": "Ground truth of a generated dataset, one row per invoice. **No stage of the pipeline reads this "
                   "table**, and the copilot is not allowed to query it; it exists so that the dashboard can show, "
                   "for a generated ledger, what was injected.",
        "source": "`labels.csv`",
        "used": "The evaluation scripts read `labels.csv` directly. The dashboard reads this table.",
        "columns": {
            "invoice_id": "The invoice.",
            "label": "`clean`, `hard_negative` (clean, built to resemble an anomaly) or `anomalous`.",
            "class_id": "Anomaly class of an anomalous invoice: `R1` to `R10` (decided by a control) or `J1` to "
                        "`J4` (needs judgement).",
            "clause_ids": "The clauses the invoice violates, separated by `|`.",
            "severity": "The highest severity among those clauses.",
            "group_id": "Invoices that form one case, such as the invoices of one same-day group, share a value.",
            "related_invoice_id": "For a duplicate, the invoice it copies.",
            "hard_negative_type": "Type of a hard negative, for example `HN_TOLERANCE`.",
            "note": "What was injected, in words.",
        },
    },
    "meta": {
        "summary": "Facts about the database itself.",
        "source": "`setup`",
        "used": "`python -m auditiq status` and the dashboard.",
        "columns": {
            "key": "Name of the fact. `dataset` is the name of the loaded ledger; `schema` identifies the version "
                   "of the schema the database has (on PostgreSQL also whether the copilot's read-only role has "
                   "its grants), so that a connection to an up-to-date database changes nothing.",
            "value": "Its value.",
        },
    },
}

VIEW_NOTES = {
    "v_latest_results": {
        "summary": "The most recent result of every audited invoice, with the configuration, policy version and "
                   "model of its run. This is the current state of the audit.",
        "columns": {"configuration": "`audit_runs.configuration` of the result's run.",
                    "policy_version": "`audit_runs.policy_version` of the result's run.",
                    "model": "`audit_runs.model` of the result's run."},
    },
    "v_review_queue": {
        "summary": "The results that are waiting for a reviewer (`workflow_status = 'PENDING_REVIEW'` in "
                   "`v_latest_results`), with the vendor's name and the invoice's date and amount.",
        "columns": {"vendor_name": "`vendor_master.vendor_name`.", "invoice_date": "`invoices.date`.",
                    "amount": "`invoices.amount`."},
    },
}

RELATIONS = """```mermaid
erDiagram
    vendor_master   ||--o{ purchase_orders  : "places orders with"
    vendor_master   ||--o{ invoices         : "sends"
    purchase_orders ||--o{ goods_receipts   : "received against"
    purchase_orders |o--o{ invoices         : "po_id (may be absent)"
    goods_receipts  |o--o{ invoices         : "grn_id (may be absent)"
    invoices        ||--|{ approval_logs    : "transaction_id"
    company_policies ||--|{ policy_clauses  : "version"
    policy_clauses  ||--o{ policy_parameters : "version, clause_id"
    policy_documents ||--|{ policy_chunks   : "doc_id"
    audit_runs      ||--o{ audit_results    : "run_id"
    invoices        ||--o{ audit_results    : "invoice_id"
    audit_results   ||--o{ audit_flags      : "result_id"
    audit_results   ||--|{ audit_trail      : "result_id"
    audit_results   ||--o{ review_decisions : "result_id"
    invoices        ||--o| benchmark_labels : "invoice_id"
```"""


def schema_columns(backend: str) -> dict[str, list[tuple[str, str]]]:
    """``{table: [(column, type and constraints)]}`` as declared for one backend."""
    sql = db.SCHEMA.format(**db.TYPES[backend])
    tables: dict[str, list[tuple[str, str]]] = {}
    for name, body in re.findall(r"CREATE TABLE IF NOT EXISTS (\w+) \((.*?)\);", sql, flags=re.S):
        parts = [p.strip() for p in re.split(r",\s*\n", body.strip())] if "\n" in body else \
                [p.strip() for p in body.split(",")]
        tables[name] = [tuple(p.split(None, 1)) for p in parts
                        if not p.startswith(("PRIMARY KEY", "FOREIGN KEY", "UNIQUE"))]
    return tables


def table_constraints() -> dict[str, list[str]]:
    sql = db.SCHEMA.format(**db.TYPES["postgres"])
    found: dict[str, list[str]] = {}
    for name, body in re.findall(r"CREATE TABLE IF NOT EXISTS (\w+) \((.*?)\);", sql, flags=re.S):
        found[name] = [" ".join(p.split()) for p in re.split(r",\s*\n", body.strip())
                       if p.strip().startswith(("PRIMARY KEY", "FOREIGN KEY", "UNIQUE"))]
    for table, column in re.findall(r"CREATE INDEX IF NOT EXISTS \w+ ON (\w+)\((.*?)\);", sql):
        found[table].append(f"INDEX ({column})")
    return found


def view_columns() -> dict[str, list[str]]:
    """Columns of each view, in order."""
    results = [c for c, _ in schema_columns("sqlite")["audit_results"]]
    return {"v_latest_results": results + ["configuration", "policy_version", "model"],
            "v_review_queue": ["result_id", "invoice_id", "vendor_id", "vendor_name", "invoice_date", "amount",
                               "route", "risk_level", "r0", "rc", "flag_count", "configuration", "created_at"]}


def _short(declaration: str) -> str:
    """A column declaration without the wordy identity clause."""
    return declaration.replace("BIGINT GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY", "BIGINT identity, PRIMARY KEY") \
                      .replace("INTEGER PRIMARY KEY AUTOINCREMENT", "INTEGER autoincrement, PRIMARY KEY")


def render() -> str:
    sqlite, postgres, constraints = schema_columns("sqlite"), schema_columns("postgres"), table_constraints()
    out = [
        "# Data dictionary", "",
        "Every table and column of the AuditIQ database: its type on both backends, what it means and which "
        "part of the system uses it. **This file is generated** from `auditiq/datadict.py` and the schema in "
        "`auditiq/db.py` by `python -m auditiq.datadict`; edit those, not this file.", "",
        "The five ledger tables have the same columns as the five CSV files of a dataset, and "
        "`benchmark_labels` those of `labels.csv` ([DATASETS.md](DATASETS.md) describes the datasets). "
        "`python -m auditiq export --out <folder>` writes every table as CSV.", "",
        "## Conventions", "",
        "- **Backends.** The schema is the same on SQLite and PostgreSQL, with the column types of each. Money "
        "is `NUMERIC(15,2)` on PostgreSQL and `REAL` on SQLite; dates and timestamps are `DATE` and `TIMESTAMP` "
        "on PostgreSQL and ISO text (`YYYY-MM-DD`, `YYYY-MM-DD HH:MM:SS`) on SQLite. The application reads "
        "floats and ISO strings from both, so every stage decides identically on both.",
        "- **Flags** are integers, 1 for true and 0 for false, on both backends.",
        "- **Money** is in Indian rupees, before tax unless the column says otherwise.",
        "- **Identifiers** of ledger records are text with a prefix (`VEND`, `PO`, `GRN`, `INV`, `LOG`). "
        "Identifiers of rows the application creates are integers assigned by the database.",
        "- **Audited** marks the ledger columns that the controls and agents can read. The other ledger "
        "columns are carried for the reviewer, the dashboard and the copilot; no control or agent sees them, so "
        "nothing in them can influence a decision.",
        "- **Everything is synthetic.** No vendor, person, GSTIN or invoice in a generated dataset is real.", "",
        "## Relations", "", RELATIONS, "",
        "`invoices.po_id` and `invoices.grn_id` are not declared as foreign keys: an invoice may name an order "
        "that is not on record, and finding that is the job of Rule 2.1.3.", "",
    ]
    for group, intro, names in GROUPS:
        out += [f"## {group}", ""] + ([intro, ""] if intro else [])
        for name in names:
            info = TABLES[name]
            audited = AUDITED.get(name)
            out += [f"### `{name}`", "", info["summary"], "",
                    f"- **Written by:** {info['source']}", f"- **Used by:** {info['used']}", ""]
            head = "| Column | SQLite | PostgreSQL |" + (" Audited |" if audited else "") + " Meaning |"
            out += [head, "|---|---|---|" + ("---|" if audited else "") + "---|"]
            for (column, lite), (_, pg) in zip(sqlite[name], postgres[name]):
                mark = (" yes |" if column in audited else " |") if audited else ""
                meaning = info["columns"][column].replace("|", "\\|")       # a bare pipe would end the cell
                out.append(f"| `{column}` | {_short(lite)} | {_short(pg)} |{mark} {meaning} |")
            if constraints[name]:
                out += ["", "Also: " + "; ".join(f"`{c}`" for c in constraints[name]) + "."]
            out.append("")
    out += ["## Views", "",
            "Views are read-only. The copilot's generated SQL may read the ledger tables, the policy tables, "
            "the audit tables and these views; it may not read `benchmark_labels`.", ""]
    for name, columns in view_columns().items():
        note = VIEW_NOTES[name]
        out += [f"### `{name}`", "", note["summary"], "", "| Column | Meaning |", "|---|---|"]
        for column in columns:
            meaning = note["columns"].get(column) or f"As `audit_results.{column}`."
            out.append(f"| `{column}` | {meaning} |")
        out.append("")
    return "\n".join(out)


def main() -> None:
    DOC.parent.mkdir(parents=True, exist_ok=True)
    DOC.write_text(render(), encoding="utf-8", newline="\n")
    print(f"wrote {DOC}")


if __name__ == "__main__":
    main()
