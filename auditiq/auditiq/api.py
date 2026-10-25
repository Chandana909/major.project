"""The REST API of the platform, used by the web frontend.

    python -m auditiq serve                       http://127.0.0.1:8000
    python -m auditiq serve --host 0.0.0.0 --port 8080

The API is under /api; its OpenAPI description is at /api/docs. When the
frontend has been built (`npm run build` in frontend/), it is served at /.

Every request opens its own database connection, so the API serves SQLite and
PostgreSQL alike and holds no state between requests. Work that takes long
(an audit with a model, re-auditing a ledger, loading a new ledger, a copilot
answer, reading a policy with a model) runs as a background job: the request returns a job id
at once, and GET /api/jobs/{id} reports progress and the result.

Settings (environment or .env):

    AUDITIQ_API_TOKEN     when set, every /api request except /api/health needs
                          the header "Authorization: Bearer <token>"
    AUDITIQ_CORS_ORIGINS  comma-separated origins allowed to call the API from a
                          browser (default: the Vite development server)
"""
from __future__ import annotations

import dataclasses
import hashlib
import hmac
import json
import logging
import os
import re
import threading
import time
import uuid
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any, Literal

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import __version__, copilot, db, ledger_import, policy_extract, policy_llm, service
from .config import load_env
from .graph import PRESETS
from .llm import LLMSettings, OpenAIChatClient, ResponseCache
from .policy import PROJECT_ROOT
from .retrieval import EndpointEmbedder, PolicyIndex

log = logging.getLogger(__name__)
FRONTEND = PROJECT_ROOT / "frontend" / "dist"
UPLOADS = PROJECT_ROOT / ".auditiq" / "uploads"
RESULTS = PROJECT_ROOT / "results"
MAX_UPLOAD = 20 * 1024 * 1024
MAX_LEDGER = 100 * 1024 * 1024
UPLOAD_ID = re.compile(r"^[0-9a-f]{16}$")
INVOICE_ID = re.compile(r"^[A-Z0-9_-]{1,40}$")


# ----------------------------------------------------------------- requests
class AuditIn(BaseModel):
    config: Literal["C1", "C2", "C3", "C4", "C5"] = "C1"


class DecisionIn(BaseModel):
    decision: Literal["approve", "reject", "override"]
    reviewer: str = Field(min_length=1, max_length=120)
    justification: str = Field(default="", max_length=4000)


class VersionIn(BaseModel):
    version: str = Field(min_length=1, max_length=40)


class AdoptIn(BaseModel):
    upload_id: str
    activate: bool = True
    replace: bool = False


class ConfirmIn(BaseModel):
    upload_id: str
    reviewer: str = Field(default="", max_length=120)
    accept_verified: bool = False
    values: dict[str, Any] = Field(default_factory=dict, description='{"<rule>.<parameter>": <value>}')
    passages: dict[str, str] = Field(default_factory=dict, description='{"<rule>": "<passage of the document>"}')
    version: str | None = None
    activate: bool = True
    replace: bool = False


class AskIn(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    invoice_id: str | None = None


class DataQuestionIn(BaseModel):
    question: str = Field(min_length=1, max_length=2000)


# --------------------------------------------------------------------- jobs
@dataclasses.dataclass
class Job:
    id: str
    kind: str
    status: str = "queued"           # queued, running, done, failed
    done: int = 0
    total: int = 0
    result: Any = None
    error: str | None = None
    started: float = dataclasses.field(default_factory=time.time)
    finished: float | None = None

    def public(self) -> dict:
        return {"id": self.id, "kind": self.kind, "status": self.status, "done": self.done, "total": self.total,
                "result": self.result, "error": self.error, "seconds": round((self.finished or time.time()) - self.started, 1)}


class JobConflict(RuntimeError):
    """A job that would work on the ledger while another job changes it."""


# The jobs a job of each kind may not run beside. Loading a ledger deletes the ledger and every result, so
# nothing that audits may run with it; two audits of the whole ledger would interleave their results.
CONFLICTS = {
    "load-ledger": {"load-ledger", "apply-policy", "audit"},
    "apply-policy": {"load-ledger", "apply-policy"},
    "audit": {"load-ledger"},
}


class Jobs:
    """Background jobs, each on its own thread with its own database connection."""

    def __init__(self, keep: int = 200):
        self._jobs: dict[str, Job] = {}
        self._lock = threading.Lock()
        self._keep = keep

    def start(self, kind: str, work: Callable[[Job], Any]) -> Job:
        job = Job(id=uuid.uuid4().hex[:12], kind=kind)
        with self._lock:
            busy = [j for j in self._jobs.values() if j.status in ("queued", "running")]
            clash = next((j for j in busy if j.kind in CONFLICTS.get(kind, ())), None)
            if clash is not None:
                raise JobConflict(f"the {clash.kind} job {clash.id} is still running; wait for it to finish")
            self._jobs[job.id] = job
            finished = [i for i, j in self._jobs.items() if j.status in ("done", "failed")]
            for old in finished[:max(0, len(self._jobs) - self._keep)]:     # a running job is never forgotten
                self._jobs.pop(old, None)

        def run() -> None:
            job.status = "running"
            try:
                job.result = work(job)
                job.status = "done"
            except Exception as error:                         # reported to the client, not raised
                log.exception("job %s (%s) failed", job.id, kind)
                job.status, job.error = "failed", f"{type(error).__name__}: {error}"
            job.finished = time.time()

        threading.Thread(target=run, name=f"job-{kind}-{job.id}", daemon=True).start()
        return job

    def get(self, job_id: str) -> Job | None:
        return self._jobs.get(job_id)


# ------------------------------------------------------------------ helpers
def chat_client(max_tokens: int | None = None) -> OpenAIChatClient | None:
    """The configured model, or None."""
    try:
        settings = LLMSettings.from_env()
    except RuntimeError:
        return None
    if max_tokens:
        settings = dataclasses.replace(settings, max_tokens=max_tokens)
    return OpenAIChatClient(settings, ResponseCache())


def model_name() -> str | None:
    try:
        return LLMSettings.from_env().model
    except RuntimeError:
        return None


def rows(cursor) -> list[dict]:
    return [dict(zip(r.keys(), r)) for r in cursor.fetchall()]


def hit_dict(hit) -> dict:
    out = dataclasses.asdict(hit)
    out["source"] = hit.source
    return out


def upload_path(upload_id: str) -> Path:
    if not UPLOAD_ID.match(upload_id or ""):
        raise HTTPException(400, "not an upload id")
    found = sorted(UPLOADS.glob(f"{upload_id}_*.pdf"))
    if not found:
        raise HTTPException(404, "no upload with this id; upload the document again")
    return found[0]


def proposal_dict(p: policy_llm.Proposal) -> dict:
    return {"file": p.file, "title": p.title, "version": p.version, "pages": p.pages, "model": p.model,
            "problems": p.problems, "usage": p.usage,
            "rules": {k: {"located": v["located"], "quotes": [{"text": q, "page": page} for q, page in v["quotes"]],
                          "by_person": bool(v.get("by_person"))} for k, v in p.rules.items()},
            "items": [{k: i[k] for k in ("clause", "parameter", "value", "reference", "status", "reason", "quote", "page")}
                      for i in p.items]}


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


# --------------------------------------------------------------------- app
def create_app(target: str | None = None, token: str | None = None, frontend: Path | None = FRONTEND,
               cors_origins: list[str] | None = None) -> FastAPI:
    """The application. ``target`` is a SQLite path or a PostgreSQL URL (default: the configured database)."""
    load_env()
    app = FastAPI(title="AuditIQ API", version=__version__, docs_url="/api/docs", openapi_url="/api/openapi.json",
                  redoc_url=None, description="Forensic audit of procurement transactions: ledger, policy, audit "
                                              "results, review and copilot.")
    app.state.target = target or db.default_target()
    app.state.token = token if token is not None else os.environ.get("AUDITIQ_API_TOKEN") or None
    app.state.jobs = Jobs()
    app.state.proposals = {}
    origins = cors_origins if cors_origins is not None else [
        o.strip() for o in os.environ.get("AUDITIQ_CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173").split(",")
        if o.strip()]
    app.add_middleware(CORSMiddleware, allow_origins=origins, allow_methods=["*"], allow_headers=["*"])

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        """Every answer, the API's and the web application's: no type sniffing, no framing by another site,
        no address sent on to other sites."""
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        return response

    @app.exception_handler(db.DatabaseUnavailable)
    def unavailable(_: Request, error: db.DatabaseUnavailable) -> JSONResponse:
        return JSONResponse({"detail": str(error)}, status_code=503)

    @app.exception_handler(JobConflict)
    def conflict(_: Request, error: JobConflict) -> JSONResponse:
        return JSONResponse({"detail": str(error)}, status_code=409)

    def authorised(request: Request) -> None:
        expected = request.app.state.token
        supplied = request.headers.get("authorization", "")
        # compared in constant time, so that the time of a refusal says nothing about the token
        if expected and not hmac.compare_digest(supplied.encode(), f"Bearer {expected}".encode()):
            raise HTTPException(401, "a valid API token is required", headers={"WWW-Authenticate": "Bearer"})

    def connection(request: Request) -> Iterator[db.Database]:
        conn = db.connect(request.app.state.target)
        try:
            yield conn
        finally:
            conn.close()

    protected = [Depends(authorised)]

    # -- status --------------------------------------------------------------
    @app.get("/api/health", tags=["status"])
    def health(conn: db.Database = Depends(connection)) -> dict:
        """Version, backend, ledger, active policy and model; open without a token, for monitoring."""
        return {"status": "ok", "version": __version__, "backend": conn.backend,
                "ledger": conn.scalar("SELECT value FROM meta WHERE key = 'dataset'"),
                "policy_version": conn.scalar("SELECT version FROM company_policies WHERE is_active = 1"),
                "model": model_name(), "auth": bool(app.state.token)}

    @app.get("/api/overview", tags=["status"], dependencies=protected)
    def overview(conn: db.Database = Depends(connection)) -> dict:
        """Counts by state, route and risk level; findings by rule; recent runs; the vendors with most invoices
        waiting."""
        states = {r[0]: int(r[1]) for r in conn.execute(
            "SELECT workflow_status, COUNT(*) FROM v_latest_results GROUP BY workflow_status")}
        routes = {r[0]: int(r[1]) for r in conn.execute("SELECT route, COUNT(*) FROM v_latest_results GROUP BY route")}
        levels = {r[0]: int(r[1]) for r in conn.execute(
            "SELECT risk_level, COUNT(*) FROM v_latest_results GROUP BY risk_level")}
        findings = rows(conn.execute(
            "SELECT f.clause AS rule, COALESCE(c.title, 'not in the policy') AS title, f.severity, "
            "CASE f.source WHEN 'D' THEN 'control' ELSE 'agent' END AS source, COUNT(*) AS findings "
            "FROM audit_flags f JOIN v_latest_results l ON l.result_id = f.result_id "
            "LEFT JOIN policy_clauses c ON c.version = l.policy_version AND c.clause_id = f.clause "
            "WHERE f.status = 'kept' GROUP BY f.clause, c.title, f.severity, f.source ORDER BY findings DESC, rule"))
        runs = rows(conn.execute(
            "SELECT u.run_id, u.configuration, u.policy_version, u.model, u.note, u.started_at, u.finished_at, "
            "COUNT(r.result_id) AS invoices FROM audit_runs u LEFT JOIN audit_results r ON r.run_id = u.run_id "
            "GROUP BY u.run_id, u.configuration, u.policy_version, u.model, u.note, u.started_at, u.finished_at "
            "ORDER BY u.run_id DESC LIMIT 10"))
        vendors = rows(conn.execute(
            "SELECT vendor_id, vendor_name, COUNT(*) AS waiting, SUM(amount) AS amount FROM v_review_queue "
            "GROUP BY vendor_id, vendor_name ORDER BY waiting DESC, amount DESC LIMIT 10"))
        return {"ledger": conn.scalar("SELECT value FROM meta WHERE key = 'dataset'"),
                "policy_version": conn.scalar("SELECT version FROM company_policies WHERE is_active = 1"),
                "backend": conn.backend, "model": model_name(),
                "invoices": int(conn.scalar("SELECT COUNT(*) FROM invoices") or 0),
                "vendors": int(conn.scalar("SELECT COUNT(*) FROM vendor_master") or 0),
                "audited": sum(states.values()), "states": states, "routes": routes, "risk_levels": levels,
                "findings": sum(int(f["findings"]) for f in findings),
                "reviewed": sum(n for s, n in states.items() if s.startswith("REVIEW_")),
                "findings_by_rule": findings, "runs": runs, "vendors_waiting": vendors}

    @app.get("/api/risk-map", tags=["status"], dependencies=protected)
    def risk_map(conn: db.Database = Depends(connection)) -> dict:
        """One point per vendor: its invoices, amount, findings and the highest risk among its latest results."""
        vendors = rows(conn.execute(
            "SELECT v.vendor_id, v.vendor_name, v.vendor_category AS category, COUNT(i.invoice_id) AS invoices, "
            "COALESCE(SUM(i.amount), 0) AS amount, "
            "SUM(CASE WHEN l.workflow_status = 'PENDING_REVIEW' THEN 1 ELSE 0 END) AS waiting, "
            "COALESCE(SUM(l.flag_count), 0) AS findings, COALESCE(MAX(l.rc), 0) AS max_risk, "
            "MAX(CASE WHEN v.blacklisted = 1 THEN 1 ELSE 0 END) AS blacklisted "
            "FROM vendor_master v JOIN invoices i ON i.vendor_id = v.vendor_id "
            "LEFT JOIN v_latest_results l ON l.invoice_id = i.invoice_id "
            "GROUP BY v.vendor_id, v.vendor_name, v.vendor_category ORDER BY v.vendor_id"))
        for v in vendors:
            for key in ("invoices", "waiting", "findings", "blacklisted"):
                v[key] = int(v[key] or 0)
            v["amount"], v["max_risk"] = float(v["amount"] or 0), float(v["max_risk"] or 0)
        return {"vendors": vendors}

    @app.get("/api/pipeline", tags=["status"])
    def pipeline() -> dict:
        """The stages of the pipeline and which configuration runs which: for the diagram of the frontend."""
        stages = [
            {"id": "extraction", "label": "Evidence extraction", "kind": "code"},
            {"id": "controls", "label": "Deterministic controls", "kind": "code", "feature": True},
            {"id": "math_approvals", "label": "Math & Approvals agent", "kind": "llm"},
            {"id": "tax_identity", "label": "Tax & Identity agent", "kind": "llm"},
            {"id": "vendor_intelligence", "label": "Vendor Intelligence agent", "kind": "llm"},
            {"id": "single_auditor", "label": "Single-prompt auditor", "kind": "llm"},
            {"id": "challenger", "label": "Challenger", "kind": "llm"},
            {"id": "confidence", "label": "Confidence", "kind": "code"},
            {"id": "risk_score", "label": "Risk score & route", "kind": "code"},
            {"id": "human_review", "label": "Human review", "kind": "person"},
            {"id": "audit_pack", "label": "Audit pack & trail", "kind": "code"},
        ]
        configs = {}
        for name, c in PRESETS.items():
            use = ["extraction"] + (["controls"] if c.controls else [])
            use += {"specialists": ["math_approvals", "tax_identity", "vendor_intelligence"],
                    "single": ["single_auditor"], "none": []}[c.agents]
            use += (["challenger"] if c.challenger else []) + (["confidence"] if c.confidence else [])
            configs[name] = use + ["risk_score", "human_review", "audit_pack"]
        return {"stages": stages, "configurations": configs}

    # -- review --------------------------------------------------------------
    @app.get("/api/queue", tags=["review"], dependencies=protected)
    def queue(limit: int = 200, conn: db.Database = Depends(connection)) -> dict:
        """Invoices waiting for review, highest weighted risk first (at most 2,000)."""
        limit = max(1, min(limit, 2000))
        items = rows(conn.execute(f"SELECT * FROM v_review_queue ORDER BY rc DESC, invoice_id LIMIT {limit}"))
        return {"total": int(conn.scalar("SELECT COUNT(*) FROM v_review_queue") or 0), "items": items}

    @app.get("/api/invoices", tags=["review"], dependencies=protected)
    def invoices(q: str = "", limit: int = 50, conn: db.Database = Depends(connection)) -> dict:
        """Search invoices by id or vendor name, with their latest audit outcome."""
        limit = max(1, min(limit, 500))
        like = f"%{q.strip()}%"
        items = rows(conn.execute(
            "SELECT i.invoice_id, i.vendor_id, v.vendor_name, i.date, i.amount, l.route, l.risk_level, l.rc, "
            "l.workflow_status FROM invoices i JOIN vendor_master v ON v.vendor_id = i.vendor_id "
            "LEFT JOIN v_latest_results l ON l.invoice_id = i.invoice_id "
            f"WHERE i.invoice_id LIKE ? OR v.vendor_name LIKE ? ORDER BY i.invoice_id LIMIT {limit}", (like, like)))
        return {"items": items}

    @app.get("/api/invoices/{invoice_id}", tags=["review"], dependencies=protected)
    def invoice(invoice_id: str, with_label: bool = False, conn: db.Database = Depends(connection)) -> dict:
        """The records of an invoice, its vendor's last 40 other invoices, and its latest result with the audit
        pack and trail; with_label adds the benchmark label."""
        invoice_id = invoice_id.strip().upper()
        if not INVOICE_ID.match(invoice_id):
            raise HTTPException(400, "not an invoice id")
        txn = db.extract_one(conn, invoice_id)
        if txn is None:
            raise HTTPException(404, f"{invoice_id} is not in the ledger")
        row = db.latest_result(conn, invoice_id)
        result = None
        if row is not None:
            trail = rows(conn.execute("SELECT seq, stage, actor, detail, prompt_tokens, completion_tokens, latency_ms "
                                      "FROM audit_trail WHERE result_id = ? ORDER BY seq", (row["result_id"],)))
            result = {k: row[k] for k in ("result_id", "run_id", "route", "risk_level", "r0", "rc", "workflow_status",
                                          "configuration", "model", "policy_version", "created_at")}
            result.update(pack=json.loads(row["audit_pack"]), trail=trail)
        history = txn.pop("vendor_history")
        out = {"records": txn, "history": {"total": len(history), "items": history[-40:]}, "result": result}
        if with_label:
            label = conn.execute("SELECT label, class_id, clause_ids, hard_negative_type, note FROM benchmark_labels "
                                 "WHERE invoice_id = ?", (invoice_id,)).fetchone()
            out["benchmark_label"] = dict(zip(label.keys(), label)) if label else None
        return out

    @app.post("/api/results/{result_id}/decision", tags=["review"], dependencies=protected)
    def decide(result_id: int, body: DecisionIn, conn: db.Database = Depends(connection)) -> dict:
        """Record a reviewer's decision on a result: approve, reject or override (an override needs a
        justification)."""
        try:
            db.record_decision(conn, result_id, body.decision, body.reviewer, body.justification)
        except KeyError as error:
            raise HTTPException(404, str(error).strip("'")) from None
        except ValueError as error:
            raise HTTPException(400, str(error)) from None
        row = conn.execute("SELECT invoice_id, workflow_status FROM audit_results WHERE result_id = ?",
                           (result_id,)).fetchone()
        return {"result_id": result_id, "invoice_id": row["invoice_id"], "workflow_status": row["workflow_status"]}

    @app.post("/api/invoices/{invoice_id}/audit", tags=["review"], dependencies=protected, status_code=202)
    def audit(invoice_id: str, body: AuditIn, request: Request) -> dict:
        """Audit one invoice again under a configuration (a background job); C2 to C5 need a model."""
        invoice_id = invoice_id.strip().upper()
        config = PRESETS[body.config]
        client = chat_client() if config.agents != "none" else None
        if config.agents != "none" and client is None:
            raise HTTPException(400, f"{body.config} needs a model; configure one (see .env.example)")
        target = request.app.state.target

        def work(job: Job) -> dict:
            conn = db.connect(target)
            try:
                if db.extract_one(conn, invoice_id) is None:
                    raise KeyError(f"{invoice_id} is not in the ledger")
                job.total = 1
                run_id = service.audit_invoices(conn, config, db.read_policy(conn), client, [invoice_id],
                                                note="audited from the web frontend")
                job.done = 1
                row = db.latest_result(conn, invoice_id)
                return {"run_id": run_id, "invoice_id": invoice_id, "route": row["route"],
                        "workflow_status": row["workflow_status"]}
            finally:
                conn.close()

        return request.app.state.jobs.start("audit", work).public()

    # -- policy --------------------------------------------------------------
    @app.get("/api/policy", tags=["policy"], dependencies=protected)
    def policy(conn: db.Database = Depends(connection)) -> dict:
        """The stored policy versions and how each was adopted, the rules of the active one, the ingested
        documents."""
        versions = []
        for r in conn.execute("SELECT version, policy_name, effective_date, is_active, registry FROM company_policies "
                              "ORDER BY version").fetchall():
            registry = json.loads(r["registry"])
            versions.append({"version": r["version"], "policy_name": r["policy_name"], "effective_date": r["effective_date"],
                             "active": bool(r["is_active"]), "adoption": registry.get("adoption")})
        active = next((v["version"] for v in versions if v["active"]), None)
        rules = []
        if active:
            for clause_id, c in db.read_policy(conn, active).clauses.items():
                rules.append({"rule": clause_id, "title": c["title"], "severity": c["severity"], "kind": c["kind"],
                              "params": c["params"]})
        documents = rows(conn.execute(
            "SELECT d.file_name, d.title, d.version, d.pages, d.ingested_at, COUNT(c.chunk_id) AS passages, "
            "SUM(CASE WHEN c.kind = 'clause' THEN 1 ELSE 0 END) AS rules FROM policy_documents d "
            "LEFT JOIN policy_chunks c ON c.doc_id = d.doc_id "
            "GROUP BY d.doc_id, d.file_name, d.title, d.version, d.pages, d.ingested_at ORDER BY d.file_name"))
        stale = conn.scalar("SELECT COUNT(*) FROM v_latest_results WHERE policy_version <> ?", (active,)) if active else 0
        return {"active": active, "versions": versions, "rules": rules, "documents": documents,
                "results_under_other_versions": int(stale or 0)}

    @app.post("/api/policy/activate", tags=["policy"], dependencies=protected)
    def activate(body: VersionIn, conn: db.Database = Depends(connection)) -> dict:
        """Make a stored policy version the active one; later audits use it."""
        try:
            db.set_active_policy(conn, body.version)
        except KeyError as error:
            raise HTTPException(404, str(error).strip("'")) from None
        return {"active": body.version}

    @app.post("/api/policy/preview", tags=["policy"], dependencies=protected)
    async def preview(file: UploadFile = File(...), conn: db.Database = Depends(connection)) -> dict:
        """Read a policy PDF without storing anything: what it states and how it differs from the active version."""
        data = await file.read(MAX_UPLOAD + 1)
        if len(data) > MAX_UPLOAD:
            raise HTTPException(413, "the document is larger than 20 MB")
        if not data.startswith(b"%PDF"):
            raise HTTPException(415, "the document is not a PDF")
        upload_id = hashlib.sha256(data).hexdigest()[:16]
        name = re.sub(r"[^A-Za-z0-9._-]+", "_", Path(file.filename or "policy.pdf").name)[:80]
        if not name.lower().endswith(".pdf"):
            name += ".pdf"
        UPLOADS.mkdir(parents=True, exist_ok=True)
        path = UPLOADS / f"{upload_id}_{name}"
        path.write_bytes(data)
        found = policy_extract.build(path, db.read_policy(conn).registry)
        return {"upload_id": upload_id, "file": name, "title": found.title, "version": found.version,
                "pages": found.pages, "usable": found.usable, "problems": found.problems, "changes": found.changes}

    @app.post("/api/policy/adopt", tags=["policy"], dependencies=protected)
    def adopt(body: AdoptIn, conn: db.Database = Depends(connection)) -> dict:
        """Adopt a previewed policy document as a new version; refused with the problems if it cannot be executed."""
        report = policy_extract.adopt(conn, upload_path(body.upload_id), activate=body.activate, replace=body.replace)
        if not report["adopted"]:
            raise HTTPException(422, {"message": "the document was not adopted", "problems": report["problems"]})
        return report

    @app.post("/api/policy/propose", tags=["policy"], dependencies=protected, status_code=202)
    def propose(body: AdoptIn, request: Request) -> dict:
        """Let the model read a policy in its own wording (a background job); the result waits for confirmation."""
        path = upload_path(body.upload_id)
        client = chat_client(max_tokens=2500)
        if client is None:
            raise HTTPException(400, "reading a policy in its own wording needs a model; configure one")
        target, proposals = request.app.state.target, request.app.state.proposals

        def work(job: Job) -> dict:
            conn = db.connect(target)
            try:
                proposal = policy_llm.propose(path, db.read_policy(conn).registry, client)
            finally:
                conn.close()
            proposals[body.upload_id] = proposal
            return proposal_dict(proposal)

        return request.app.state.jobs.start("policy-reading", work).public()

    @app.post("/api/policy/confirm", tags=["policy"], dependencies=protected)
    def confirm(body: ConfirmIn, request: Request, conn: db.Database = Depends(connection)) -> dict:
        """Adopt a model's proposal after the reviewer's confirmation, corrections and quoted passages."""
        path = upload_path(body.upload_id)
        proposal = request.app.state.proposals.get(body.upload_id)
        if proposal is None:
            raise HTTPException(404, "no proposal for this document; let the model read it first")
        not_found = policy_llm.add_passages(proposal, {k: v for k, v in body.passages.items() if v.strip()})
        try:
            overrides = {tuple(key.rsplit(".", 1)): value for key, value in body.values.items()}
            values, still_open = policy_llm.decide(proposal, accept_verified=body.accept_verified, overrides=overrides)
        except (ValueError, StopIteration) as error:
            raise HTTPException(400, f"a value could not be used: {error}") from None
        problems = [f"the passage given for rule {c} is not in the document" for c in not_found] + still_open
        if problems:
            raise HTTPException(422, {"message": "not adopted", "problems": problems + proposal.problems,
                                      "proposal": proposal_dict(proposal)})
        report = policy_llm.adopt(conn, path, proposal, db.read_policy(conn).registry, values, body.reviewer,
                                  version=body.version, activate=body.activate, replace=body.replace)
        if not report["adopted"]:
            raise HTTPException(422, {"message": "not adopted", "problems": report["problems"]})
        request.app.state.proposals.pop(body.upload_id, None)
        return report

    @app.post("/api/policy/apply", tags=["policy"], dependencies=protected, status_code=202)
    def apply(request: Request) -> dict:
        """Audit every invoice again with the controls under the active policy (a background job)."""
        target = request.app.state.target

        def work(job: Job) -> dict:
            conn = db.connect(target)
            try:
                ids = db.invoice_ids(conn)
                job.total = len(ids)

                def progress(done: int, total: int) -> None:
                    job.done, job.total = done, total

                active = db.read_policy(conn)
                run_id = service.audit_invoices(conn, PRESETS["C1"], active, None, ids, progress=progress,
                                                note=f"policy version {active.version} applied from the web frontend")
                return service.run_summary(conn, run_id)
            finally:
                conn.close()

        return request.app.state.jobs.start("apply-policy", work).public()

    # -- ledger --------------------------------------------------------------
    @app.post("/api/ledger", tags=["ledger"], dependencies=protected, status_code=202)
    async def load_ledger(request: Request, file: UploadFile = File(...), replace: bool = Form(False)) -> dict:
        """Replace the ledger with an uploaded one: an .xlsx workbook with one sheet per table, or a .zip
        archive of the CSV files (a background job). The ledger is checked first; with any problem nothing is
        replaced. Loading removes the previous ledger with every audit result and review decision, so the
        request must say replace=true."""
        if not replace:
            raise HTTPException(400, "loading a ledger replaces the current ledger with its audit results and "
                                     "review decisions; send replace=true")
        suffix = Path(file.filename or "").suffix.lower()
        if suffix not in (".xlsx", ".zip"):
            raise HTTPException(415, "give an .xlsx workbook or a .zip archive of CSV files")
        data = await file.read(MAX_LEDGER + 1)
        if len(data) > MAX_LEDGER:
            raise HTTPException(413, "the ledger is larger than 100 MB")
        if not data.startswith(b"PK"):                    # both formats are zip containers
            raise HTTPException(415, "the file is not an .xlsx workbook or a .zip archive")
        name = re.sub(r"[^A-Za-z0-9._-]+", "_", Path(file.filename or "ledger").stem)[:60] or "ledger"
        UPLOADS.mkdir(parents=True, exist_ok=True)
        path = UPLOADS / f"ledger_{hashlib.sha256(data).hexdigest()[:16]}{suffix}"
        path.write_bytes(data)
        target = request.app.state.target

        def work(job: Job) -> dict:
            conn = db.connect(target)
            try:
                ledger = ledger_import.read(path, conn)
                ledger.name = name
                if not ledger.usable:
                    return {"loaded": False, "ledger": name, "problems": ledger.problems, "counts": ledger.counts()}
                return {"loaded": True, "ledger": name, "problems": [], "counts": ledger_import.load(conn, ledger)}
            finally:
                conn.close()
                path.unlink(missing_ok=True)

        return request.app.state.jobs.start("load-ledger", work).public()

    @app.get("/api/search", tags=["policy"], dependencies=protected)
    def search(q: str, k: int = 4, conn: db.Database = Depends(connection)) -> dict:
        """Search the policy documents: hybrid when an embedding model is configured, lexical otherwise."""
        if not q.strip():
            raise HTTPException(400, "empty question")
        try:
            index = PolicyIndex.from_db(conn, embedder=EndpointEmbedder.from_env())
        except ValueError as error:
            raise HTTPException(409, str(error)) from None
        mode = index.default_mode()
        return {"mode": mode, "hits": [hit_dict(h) for h in index.search(q.strip(), k=max(1, min(k, 10)))]}

    # -- copilot -------------------------------------------------------------
    @app.post("/api/copilot/ask", tags=["copilot"], dependencies=protected, status_code=202)
    def ask(body: AskIn, request: Request) -> dict:
        """A question about the policy or an audited invoice, answered from the passages with citations (a job)."""
        target, client = request.app.state.target, chat_client()

        def work(job: Job) -> dict:
            conn = db.connect(target)
            try:
                index = PolicyIndex.from_db(conn, embedder=EndpointEmbedder.from_env())
                out = copilot.answer(body.question, conn, index, client,
                                     invoice_id=(body.invoice_id or "").strip().upper() or None)
            finally:
                conn.close()
            return {"answer": out["answer"], "invoice_id": out["invoice_id"], "model": model_name() if client else None,
                    "passages": [hit_dict(h) for h in out["passages"]], "sources": [hit_dict(h) for h in out["sources"]]}

        return request.app.state.jobs.start("copilot", work).public()

    @app.post("/api/copilot/data", tags=["copilot"], dependencies=protected, status_code=202)
    def data_question(body: DataQuestionIn, request: Request) -> dict:
        """A question about the data, answered by one checked, read-only SELECT the model writes (a job)."""
        client = chat_client()
        if client is None:
            raise HTTPException(400, "data questions need a model; configure one")
        target = request.app.state.target

        def work(job: Job) -> dict:
            out = copilot.data_question(body.question, target, client)
            return {k: out[k] for k in ("sql", "columns", "rows", "explanation", "error")}

        return request.app.state.jobs.start("data-question", work).public()

    # -- jobs and results ----------------------------------------------------
    @app.get("/api/jobs/{job_id}", tags=["status"], dependencies=protected)
    def job(job_id: str, request: Request) -> dict:
        """The state of a background job: queued, running, done (with its result) or failed (with the reason)."""
        found = request.app.state.jobs.get(job_id)
        if found is None:
            raise HTTPException(404, "no such job")
        return found.public()

    @app.get("/api/results", tags=["results"], dependencies=protected)
    def results() -> dict:
        """The measured results of the evaluation, as the scripts wrote them."""
        benchmark, policy_swap = {}, None
        for path in sorted(RESULTS.glob("*/metrics.json")):
            m = read_json(path)
            if "construction_checks" not in m:                  # the policy-swap ledger has its own measures
                policy_swap = m
                continue
            benchmark[m["dataset"]] = {
                "n_invoices": m["n_invoices"],
                "metrics": {name: {k: v for k, v in values.items() if ":" not in k}
                            for name, values in m["metrics"].items()},
                "per_class": {name: {k.split(":", 1)[1]: v for k, v in values.items() if k.startswith("detected:")}
                              for name, values in m["metrics"].items()},
                "construction_checks": m["construction_checks"]}
        # The pilots on the development ledger, then the sample of benchmark ledger 101.
        pilots = {}
        for pattern in ("pilot_seed_909/*.meta.json", "bench_seed_101/*-sample34.meta.json"):
            for meta in sorted(RESULTS.glob(pattern)):
                m = read_json(meta)
                pilots[meta.name.removesuffix(".meta.json")] = {"model": m["model"], "dataset": m.get("dataset"),
                                                                 "summary": m["summary"], "started": m["started"],
                                                                 "finished": m["finished"]}
        return {"benchmark": benchmark, "policy_swap": policy_swap, "policy_change": read_json(RESULTS / "policy_change.json"),
                "scalability": read_json(RESULTS / "scalability.json"),
                "policy_reading": read_json(RESULTS / "policy_llm.json"), "pilots": pilots}

    # -- the frontend --------------------------------------------------------
    if frontend is not None and (frontend / "index.html").exists():
        app.mount("/assets", StaticFiles(directory=frontend / "assets"), name="assets")

        @app.get("/{path:path}", include_in_schema=False)
        def spa(path: str) -> FileResponse:
            if path.startswith("api/"):
                raise HTTPException(404, "no such endpoint")
            candidate = (frontend / path).resolve()
            if path and candidate.is_file() and frontend.resolve() in candidate.parents:
                return FileResponse(candidate)
            return FileResponse(frontend / "index.html")

    return app


def serve(host: str = "127.0.0.1", port: int = 8000, target: str | None = None) -> None:
    import uvicorn
    uvicorn.run(create_app(target), host=host, port=port, log_level="info")
