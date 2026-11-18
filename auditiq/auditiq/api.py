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

    AUDITIQ_API_TOKEN     a shared token that acts as an admin; with it, or with users
                          (python -m auditiq user add), every /api request except
                          /api/health and /api/pipeline needs "Authorization: Bearer
                          <token>", and each endpoint needs a role: viewer, reviewer or admin
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
from collections import Counter
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any, Literal

import httpx
import numpy as np
from fastapi import Depends, FastAPI, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import (
    __version__,
    analytics,
    audit_program,
    copilot,
    db,
    emails,
    leads,
    ledger_import,
    policy_extract,
    policy_llm,
    reliability,
    retrieval,
    rings,
    sampling,
    seal,
    service,
    simulation,
    stream,
    workpapers,
)
from .agents import AGENTS
from .case_graph import CaseGraph
from .config import load_env
from .graph import PRESETS
from .llm import LLMError, LLMSettings, OpenAIChatClient, ResponseCache
from .policy import PROJECT_ROOT
from .policy_graph import PolicyGraph
from .policy_graph import merge_passages as policy_graph_merge
from .retrieval import EndpointEmbedder, PolicyIndex
from .scoring import SEVERITIES

log = logging.getLogger(__name__)
FRONTEND = PROJECT_ROOT / "frontend" / "dist"
UPLOADS = PROJECT_ROOT / ".auditiq" / "uploads"
RESULTS = PROJECT_ROOT / "results"
MAX_UPLOAD = 20 * 1024 * 1024
MAX_LEDGER = 100 * 1024 * 1024
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
# The web application loads nothing from another site. Style attributes are allowed: the labels of the 3D
# views are placed with them. Everything else, scripts above all, comes from this server only.
CONTENT_SECURITY_POLICY = ("default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
                           "img-src 'self' data: blob:; font-src 'self' data:; connect-src 'self'; "
                           "worker-src 'self' blob:; object-src 'none'; base-uri 'self'; form-action 'self'; "
                           "frame-ancestors 'none'")
UPLOAD_ID = re.compile(r"^[0-9a-f]{16}$")
INVOICE_ID = re.compile(r"^[A-Z0-9_-]{1,40}$")


# ----------------------------------------------------------------- requests
class AuditIn(BaseModel):
    config: Literal["C1", "C2", "C3", "C4", "C5"] = "C1"


class DecisionIn(BaseModel):
    decision: Literal["approve", "reject", "override"]
    reviewer: str = Field(default="", max_length=120, description="taken from the account when signed in as a user")
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


class PublishIn(BaseModel):
    source: Literal["ledger", "mailbox", "policy"]
    name: str = Field(min_length=1, max_length=200)
    limit: int | None = Field(default=None, ge=1, le=1_000_000, description="ledger: publish only the first invoices")
    activate: bool = Field(default=False, description="policy: make the version active when it is stored")


class WorkIn(BaseModel):
    kinds: list[Literal["vendor", "invoice", "email", "compliance"]] = ["vendor", "invoice", "email", "compliance"]
    idle_exit: float = Field(default=4.0, ge=1.0, le=120.0, description="stop a topic after this many idle seconds")


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


class StoreCache:
    """Results of the read-only analyses of the store, kept until the store changes.

    The overview, the risk map, the analytics and the rings take seconds on a ledger of a few hundred thousand
    invoices. Each is kept with a fingerprint of the store: the ledger's name, the newest audit result, the
    newest review decision, the policy versions and their parameters, and the offsets of the Kafka workers.
    An audit, a decision, a loaded ledger, a policy change or a streamed batch moves the fingerprint, and the
    next request computes afresh. Reading the fingerprint costs a few index lookups.
    """

    FINGERPRINT = ("SELECT value FROM meta WHERE key = 'dataset'",
                   "SELECT MAX(result_id) FROM audit_results",
                   "SELECT MAX(decision_id) FROM review_decisions",
                   "SELECT version FROM company_policies WHERE is_active = 1",
                   "SELECT COUNT(*) FROM company_policies",
                   "SELECT COUNT(*) || ':' || COALESCE(SUM(LENGTH(param_value)), 0) FROM policy_parameters",
                   "SELECT COALESCE(CAST(MIN(effective_date) AS TEXT), '') || ':' || "
                   "COALESCE(CAST(MAX(effective_date) AS TEXT), '') FROM company_policies",
                   "SELECT COALESCE(SUM(next_offset), 0) FROM stream_offsets",
                   "SELECT value FROM meta WHERE key = 'labels_policy'")

    def __init__(self) -> None:
        self._entries: dict[str, tuple[tuple, Any]] = {}
        self._computing: dict[str, threading.Lock] = {}
        self._lock = threading.Lock()

    def fingerprint(self, conn: db.Database) -> tuple:
        return tuple(str(conn.scalar(sql)) for sql in self.FINGERPRINT)

    def get(self, key: str, conn: db.Database, compute: Callable[[], Any]) -> Any:
        mark = self.fingerprint(conn)
        with self._lock:
            kept = self._entries.get(key)
            computing = self._computing.setdefault(key, threading.Lock())
        if kept and kept[0] == mark:
            return kept[1]
        # One request computes an analysis; the others that ask for it meanwhile wait and take its result,
        # instead of each reading the whole ledger for the same answer.
        with computing:
            with self._lock:
                kept = self._entries.get(key)
            if kept and kept[0] == mark:
                return kept[1]
            value = compute()
            with self._lock:
                self._entries[key] = (mark, value)
        return value


class JobConflict(RuntimeError):
    """A job that would work on the ledger while another job changes it."""


# The jobs a job of each kind may not run beside. Loading a ledger deletes the ledger and every result, so
# nothing that audits may run with it; two audits of the whole ledger would interleave their results.
CONFLICTS = {
    "load-ledger": {"load-ledger", "apply-policy", "audit", "simulate", "stream-work"},
    "apply-policy": {"load-ledger", "apply-policy", "stream-work"},
    "stream-work": {"load-ledger", "apply-policy", "stream-work"},
    "audit": {"load-ledger"},
    "simulate": {"load-ledger"},
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
_PROBES: dict[str, tuple[float, bool, str]] = {}
_PROBE_LOCK = threading.Lock()


def model_reachable(settings: LLMSettings, ttl: float = 20.0) -> tuple[bool, str]:
    """Whether the model's endpoint answers, asked at most every ``ttl`` seconds. A model that is configured but not
    running is then reported and skipped, instead of each request waiting through the client's retries."""
    with _PROBE_LOCK:
        seen = _PROBES.get(settings.base_url)
        if seen and time.time() - seen[0] < ttl:
            return seen[1], seen[2]
    try:
        reply = httpx.get(f"{settings.base_url}/models", timeout=2.0,
                          headers={"Authorization": f"Bearer {settings.api_key}"} if settings.api_key else None)
        ok, why = reply.status_code < 500, f"HTTP {reply.status_code}"
    except httpx.HTTPError as error:
        ok, why = False, type(error).__name__
    with _PROBE_LOCK:
        _PROBES[settings.base_url] = (time.time(), ok, why)
    return ok, why


def chat_client(max_tokens: int | None = None) -> OpenAIChatClient | None:
    """The configured model, or None when none is configured or its endpoint does not answer."""
    try:
        settings = LLMSettings.from_env()
    except RuntimeError:
        return None
    if not model_reachable(settings)[0]:
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


def scalability_with_huge() -> dict | None:
    """The scalability results, with the 500,000-invoice ledger as the last ledger size once it is measured."""
    out = read_json(RESULTS / "scalability.json")
    huge = RESULTS / "huge_seed_606" / "size.json"
    if out and huge.exists():
        size = read_json(huge)
        out["by_size"] = out["by_size"] + [{k: size[k] for k in ("invoices", "seconds", "invoices_per_second",
                                                                 "microseconds_per_invoice")}]
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
def overview_of(conn: db.Database) -> dict:
    """The figures of the Overview page (see the endpoint), apart from the model, which is configuration."""
    states: dict[str, int] = {}
    routes: dict[str, int] = {}
    levels: dict[str, int] = {}
    configs: dict[str, int] = {}
    approved_with_findings = 0
    for status, route, level, config, flagged, n in conn.execute(     # one pass over the latest results
            "SELECT workflow_status, route, risk_level, configuration, CASE WHEN flag_count > 0 THEN 1 ELSE 0 END, "
            "COUNT(*) FROM v_latest_results GROUP BY workflow_status, route, risk_level, configuration, "
            "CASE WHEN flag_count > 0 THEN 1 ELSE 0 END"):
        for counts, key in ((states, status), (routes, route), (levels, level), (configs, config)):
            counts[key] = counts.get(key, 0) + int(n)
        approved_with_findings += int(n) if flagged and route == "approve" else 0
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
    activity = rows(conn.execute(                   # the newest steps of the audit trail, by its key
        "SELECT t.entry_id, r.invoice_id, r.created_at, t.stage, t.actor, t.detail FROM audit_trail t "
        "JOIN audit_results r ON r.result_id = t.result_id ORDER BY t.entry_id DESC LIMIT 14"))
    return {"ledger": conn.scalar("SELECT value FROM meta WHERE key = 'dataset'"),
            "policy_version": conn.scalar("SELECT version FROM company_policies WHERE is_active = 1"),
            "backend": conn.backend,
            "invoices": int(conn.scalar("SELECT COUNT(*) FROM invoices") or 0),
            "vendors": int(conn.scalar("SELECT COUNT(*) FROM vendor_master") or 0),
            "audited": sum(states.values()), "states": states, "routes": routes, "risk_levels": levels,
            "findings": sum(int(f["findings"]) for f in findings),
            "reviewed": sum(n for s, n in states.items() if s.startswith("REVIEW_")),
            "findings_by_rule": findings, "runs": runs, "vendors_waiting": vendors, "activity": activity,
            "coverage": analytics.coverage(conn, configs, approved_with_findings)}


def risk_map_of(conn: db.Database) -> dict:
    """One point per vendor (see the endpoint)."""
    # The invoices of each vendor and the latest results of each vendor, counted apart and joined on the
    # vendor: one pass over each instead of a join of every invoice with its result.
    vendors = rows(conn.execute(
        "SELECT v.vendor_id, v.vendor_name, v.vendor_category AS category, n.invoices, n.amount, "
        "COALESCE(l.waiting, 0) AS waiting, COALESCE(l.findings, 0) AS findings, "
        "COALESCE(l.max_risk, 0) AS max_risk, CASE WHEN v.blacklisted = 1 THEN 1 ELSE 0 END AS blacklisted "
        "FROM vendor_master v "
        "JOIN (SELECT vendor_id, COUNT(*) AS invoices, COALESCE(SUM(amount), 0) AS amount FROM invoices "
        "GROUP BY vendor_id) n ON n.vendor_id = v.vendor_id "
        "LEFT JOIN (SELECT vendor_id, SUM(CASE WHEN workflow_status = 'PENDING_REVIEW' THEN 1 ELSE 0 END) "
        "AS waiting, SUM(flag_count) AS findings, MAX(rc) AS max_risk FROM v_latest_results "
        "GROUP BY vendor_id) l ON l.vendor_id = v.vendor_id ORDER BY v.vendor_id"))
    for v in vendors:
        for key in ("invoices", "waiting", "findings", "blacklisted"):
            v[key] = int(v[key] or 0)
        v["amount"], v["max_risk"] = float(v["amount"] or 0), float(v["max_risk"] or 0)
    return {"vendors": vendors}


def integrity_of(conn: db.Database, row) -> str:
    """`intact`, `altered` or `unsealed` (stored before results were sealed): one result and its trail; `stale` when
    they are intact but the ledger no longer holds the records the result was based on."""
    if row["seal"] is None:
        return "unsealed"
    report = seal.verify(conn, result_ids=[int(row["result_id"])])
    if not report["intact"]:
        return "altered"
    if row["evidence"] is not None:
        txn = db.extract_one(conn, row["invoice_id"])
        if txn is None or seal.evidence(txn) != row["evidence"]:
            return "stale"
    return "intact"


def case_graph(app: FastAPI, conn: db.Database) -> CaseGraph:
    """The audited ledger as a graph, kept until the store changes (see StoreCache)."""
    return app.state.cache.get("case-graph", conn, lambda: CaseGraph.from_db(conn))


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
    app.state.cache = StoreCache()
    app.state.proposals = {}
    origins = cors_origins if cors_origins is not None else [
        o.strip() for o in os.environ.get("AUDITIQ_CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173").split(",")
        if o.strip()]
    app.add_middleware(CORSMiddleware, allow_origins=origins, allow_methods=["*"], allow_headers=["*"])
    # Answers of a kilobyte or more are compressed for a browser that accepts it: the 3D chunk of the web
    # application is about a megabyte as written, and the risk map of a large ledger a few hundred kilobytes.
    app.add_middleware(GZipMiddleware, minimum_size=1024)

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        """Every answer, the API's and the web application's: no type sniffing, no framing by another site,
        no address sent on to other sites."""
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        if not request.url.path.startswith("/api/"):       # the web application (the API docs load a viewer from a CDN)
            response.headers.setdefault("Content-Security-Policy", CONTENT_SECURITY_POLICY)
        if request.url.path.startswith("/assets/"):        # named by a hash of their content: kept for good
            response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
        return response

    @app.exception_handler(db.DatabaseUnavailable)
    def unavailable(_: Request, error: db.DatabaseUnavailable) -> JSONResponse:
        return JSONResponse({"detail": str(error)}, status_code=503)

    @app.exception_handler(LLMError)
    def model_failed(_: Request, error: LLMError) -> JSONResponse:
        return JSONResponse({"detail": f"the model did not answer: {error}"}, status_code=502)

    @app.exception_handler(JobConflict)
    def conflict(_: Request, error: JobConflict) -> JSONResponse:
        return JSONResponse({"detail": str(error)}, status_code=409)

    def principal(request: Request) -> dict:
        """Who is asking: a user (api_users) by the user's token, an admin by the shared token
        (AUDITIQ_API_TOKEN), or anyone, as an admin, while the server has neither."""
        expected = request.app.state.token
        supplied = request.headers.get("authorization", "")
        # compared in constant time, so that the time of a refusal says nothing about the token
        if expected and hmac.compare_digest(supplied.encode(), f"Bearer {expected}".encode()):
            return {"name": None, "role": "admin", "via": "shared token"}
        conn = db.connect(request.app.state.target)
        try:
            user = db.user_for_token(conn, supplied[7:].strip()) if supplied.startswith("Bearer ") else None
            if user:
                return {**user, "via": "account"}
            if not expected and not db.has_users(conn):
                return {"name": None, "role": "admin", "via": "open"}
        finally:
            conn.close()
        raise HTTPException(401, "a valid API token is required", headers={"WWW-Authenticate": "Bearer"})

    def require(role: str) -> Callable[[Request], dict]:
        """A dependency that lets through whoever has at least ``role``."""
        def allowed(request: Request) -> dict:
            who = principal(request)
            if db.ROLES.index(who["role"]) < db.ROLES.index(role):
                raise HTTPException(403, f"this needs the role {role}; {who['name']} has the role {who['role']}")
            request.state.principal = who
            return who
        allowed.required_role = role            # read by apidoc
        return allowed

    def connection(request: Request) -> Iterator[db.Database]:
        conn = db.connect(request.app.state.target)
        try:
            yield conn
        finally:
            conn.close()

    viewer, reviewer, admin = ([Depends(require(role))] for role in db.ROLES)

    # -- status --------------------------------------------------------------
    @app.get("/api/health", tags=["status"])
    def health(conn: db.Database = Depends(connection)) -> dict:
        """Version, backend, ledger, active policy and model; open without a token, for monitoring."""
        return {"status": "ok", "version": __version__, "backend": conn.backend,
                "ledger": conn.scalar("SELECT value FROM meta WHERE key = 'dataset'"),
                "policy_version": conn.scalar("SELECT version FROM company_policies WHERE is_active = 1"),
                "model": model_name(), "auth": bool(app.state.token) or db.has_users(conn)}

    @app.get("/api/me", tags=["status"], dependencies=viewer)
    def me(request: Request) -> dict:
        """Who the request is from: the user's name and role, or the shared token, or an open server."""
        return request.state.principal

    @app.get("/api/overview", tags=["status"], dependencies=viewer)
    def overview(request: Request, conn: db.Database = Depends(connection)) -> dict:
        """Counts by state, route and risk level; findings by rule; recent runs; the vendors with most invoices
        waiting; the newest steps of the audit trail; and the coverage of the latest results: which
        configurations produced them, what they did not check, and, on a benchmark ledger, how they compare
        with its answer key. Kept until the store changes."""
        return {**request.app.state.cache.get("overview", conn, lambda: overview_of(conn)), "model": model_name()}

    @app.get("/api/analytics", tags=["analytics"], dependencies=viewer)
    def ledger_analytics(request: Request, conn: db.Database = Depends(connection)) -> dict:
        """Forensic views of the ledger: monthly volume and findings, spend by category and month, Benford's
        first-digit and first-two-digits tests, amounts against the approval limits of the active policy,
        weekdays, findings by vendor category and rule, approvers and spend concentration. Computed from the
        store, and kept until the store changes."""
        return request.app.state.cache.get("analytics", conn, lambda: analytics.ledger_analytics(conn))

    @app.get("/api/rings", tags=["analytics"], dependencies=viewer)
    def collusion_rings(request: Request, limit: int = 40, conn: db.Database = Depends(connection)) -> dict:
        """Vendor collusion rings: vendors and approvers linked by a shared PAN or GSTIN, by invoices that carry
        another vendor's GSTIN, by concentrated approvals, or by approvals that carry more high or critical
        findings than the approver's role makes likely (one-sided binomial tests, Benjamini-Hochberg at a false
        discovery rate of 1 %). The `limit` strongest rings (1 to 200) come with their members and links, with
        the watch list of the most unusual approver-vendor pairs and the tests behind them. Kept until the store
        changes."""
        limit = max(1, min(limit, 200))
        return request.app.state.cache.get(f"rings:{limit}", conn, lambda: rings.find_rings(conn, limit=limit))

    @app.get("/api/leads", tags=["analytics"], dependencies=viewer)
    def judgement_leads(request: Request, conn: db.Database = Depends(connection)) -> dict:
        """Invoices for a reviewer under the two judgement rules the policy words most precisely, with its guide
        values: near duplicates (2.2.2: the same vendor, PO, GRN and amount as an earlier invoice under a re-keyed
        number) and structuring across days (4.1.2: invoices of one vendor and approving role within the guide
        window, each within the guide band below the role's limit, together above it). A lead is not a finding and
        changes no result. On a benchmark ledger, compared with its answer key. Kept until the store changes."""
        return request.app.state.cache.get("leads", conn, lambda: leads.judgement_leads(conn))

    @app.get("/api/sampling", tags=["analytics"], dependencies=viewer)
    def sampling_plan(confidence: float = Query(0.95, description="0.9, 0.95 or 0.99"),
                      tolerable_pct: float = Query(2.0, gt=0, le=20),
                      expected_pct: float = Query(0.0, ge=0, le=10), seed: int | None = Query(None, ge=1),
                      conn: db.Database = Depends(connection)) -> dict:
        """A monetary-unit sample (ISA 530) of the invoices approved without a person: the plan (sample size and
        sampling interval from the confidence, the tolerable and the expected misstatement, as a percentage of the
        approved amount), the random start and its seed (give the seed to draw the same sample again), and the
        invoices to examine. On a benchmark ledger, the answer key stands in for the examination: the misstatements
        the sample would find, the Stringer upper limit and whether it holds against the truth."""
        # A float Literal would refuse the query string "0.95"; the value is checked against the factors' table instead.
        if confidence not in sampling.CONFIDENCES:
            raise HTTPException(422, f"confidence must be one of {', '.join(str(c) for c in sampling.CONFIDENCES)}")
        try:
            return sampling.monetary_unit_sample(conn, confidence=float(confidence), tolerable_pct=tolerable_pct,
                                                 expected_pct=expected_pct, seed=seed)
        except ValueError as error:
            raise HTTPException(400, str(error)) from None

    @app.get("/api/reliability", tags=["analytics"], dependencies=viewer)
    def ledger_reliability(conn: db.Database = Depends(connection)) -> dict:
        """Whether the ledger can be relied on (ISA 500): references to documents not on file, approvals, the
        arithmetic of every invoice, date logic, goods received but not invoiced, gaps in the company's numbered
        series, vendor master data and audit coverage, each with its exceptions and the rule that decides them if
        one does; control totals; a SHA-256 fingerprint of every ledger table. Not cached: a change to the ledger
        must show at once."""
        return reliability.ledger_reliability(conn)

    @app.get("/api/program", tags=["analytics"], dependencies=viewer)
    def program(request: Request, conn: db.Database = Depends(connection)) -> dict:
        """The audit program: every test (the policy's rules, the leads, the analytics, the sample, the integrity
        checks) with the assertions (ISA 315) and fraud schemes (ACFE) it addresses and what it found; the
        assertions and schemes no test covers, with the scope limits; and on a benchmark ledger each scheme against
        the answer key. Kept until the store changes."""
        cache = request.app.state.cache
        found_leads = cache.get("leads", conn, lambda: leads.judgement_leads(conn))
        found_rings = cache.get("rings:40", conn, lambda: rings.find_rings(conn, limit=40))
        return cache.get("program", conn, lambda: audit_program.program(conn, leads=found_leads, rings=found_rings))

    @app.get("/api/workpapers", tags=["analytics"], dependencies=viewer, response_class=Response,
             responses={200: {"content": {XLSX: {}}, "description": "the workbook"}})
    def working_papers(seed: int | None = Query(None, ge=1), conn: db.Database = Depends(connection)) -> Response:
        """The working papers as an Excel workbook (auditiq/workpapers.py): summary, findings, review queue, leads,
        sample, reliability, audit program and integrity. The report digest, in the workbook and in the header
        X-Report-Digest, is the same whenever the store is unchanged; `python -m auditiq workpapers --check` tells
        whether a workbook still matches the store. The sample's seed comes from the digest of the sealed runs
        unless one is given."""
        report = workpapers.engagement(conn, seed)
        name = re.sub(r"[^A-Za-z0-9._-]+", "_", str(report["data"]["scope"]["ledger"] or "store"))
        return Response(workpapers.to_xlsx(report), media_type=XLSX, headers={
            "Content-Disposition": f'attachment; filename="auditiq-workpapers-{name}.xlsx"',
            "X-Report-Digest": report["digest"], "Access-Control-Expose-Headers": "X-Report-Digest"})

    @app.get("/api/trail/verify", tags=["status"], dependencies=viewer)
    def trail_verify(run: int | None = None, conn: db.Database = Depends(connection)) -> dict:
        """Whether the audit record is as it was stored: the seal of every result (its decision, findings and audit
        pack), the hash chain of every audit-trail entry, including the reviewers' decisions, and the seal of every
        finished run are computed again and compared (auditiq/seal.py). `digest` is one value over the seals of
        all finished runs, to keep outside the store. Not cached: a change made directly in the database must
        show at once. `evidence` re-performs the extraction: whether the ledger still holds the records each latest
        result was based on, and which invoices' records changed after their audit."""
        return {**seal.verify(conn, run_id=run), "evidence": seal.evidence_drift(conn, run_id=run),
                "digest": seal.run_digest(conn) if run is None else None}

    @app.get("/api/risk-map", tags=["status"], dependencies=viewer)
    def risk_map(request: Request, conn: db.Database = Depends(connection)) -> dict:
        """One point per vendor: its invoices, amount, findings and the highest risk among its latest results.
        Kept until the store changes."""
        return request.app.state.cache.get("risk-map", conn, lambda: risk_map_of(conn))

    @app.get("/api/stream", tags=["status"], dependencies=viewer)
    def stream_status(conn: db.Database = Depends(connection)) -> dict:
        """The Kafka ingestion layer: per topic, the messages in it, those the workers have processed, the lag and
        the outcomes. `configured` is false without AUDITIQ_KAFKA_BOOTSTRAP; `error` says why a broker that is
        configured does not answer."""
        try:
            settings = stream.StreamSettings.from_env()
        except stream.StreamUnavailable:
            return {"configured": False, "topics": []}
        try:
            return {"configured": True, "bootstrap": settings.bootstrap,
                    "topics": stream.status(settings, conn, timeout=3)}
        except stream.StreamUnavailable as error:
            return {"configured": True, "bootstrap": settings.bootstrap, "topics": [], "error": str(error)}

    def stream_settings() -> stream.StreamSettings:
        try:
            return stream.StreamSettings.from_env()
        except stream.StreamUnavailable as error:
            raise HTTPException(409, str(error)) from None

    @app.get("/api/stream/sources", tags=["stream"], dependencies=viewer)
    def stream_sources() -> dict:
        """What can be published from the server: the generated ledgers, the mailboxes and the policy documents."""
        return stream.sources(PROJECT_ROOT)

    @app.post("/api/stream/publish", tags=["stream"], dependencies=admin, status_code=202)
    def stream_publish(body: PublishIn, request: Request, conn: db.Database = Depends(connection)) -> dict:
        """Publish a source to the Kafka topics (a job): a ledger's vendors and invoices (each with its PO, receipt
        and approvals), a mailbox's e-mails, or a policy document. The topics are created when missing. A ledger
        that would replace invoices of the store with different ones (another ledger with the same invoice
        numbers) is refused with 409; the store's own ledger can be published again."""
        settings = stream_settings()
        try:
            path = stream.source_path(PROJECT_ROOT, body.source, body.name)
        except ValueError as error:
            raise HTTPException(404, str(error)) from None
        if body.source == "ledger" and (clash := stream.ledger_clash(conn, path, body.limit)):
            held = conn.scalar("SELECT value FROM meta WHERE key = 'dataset'") or "the invoices streamed so far"
            raise HTTPException(409, f"This store holds {held}. Publishing {body.name} would replace {clash:,} of its "
                                     "invoices with different ones under the same invoice numbers. Publish the store's "
                                     f"own ledger, or load {body.name} into a store of its own.")

        def work(job: Job) -> dict:
            stream.ensure_topics(settings)
            publisher = stream.Publisher(settings)
            if body.source == "ledger":
                stream.publish_ledger(publisher, path, body.limit)
            elif body.source == "mailbox":
                stream.publish_mailbox(publisher, path)
            else:
                stream.publish_policy(publisher, path, activate=body.activate)
            sent = publisher.close()                  # raises, failing the job, when a message is not delivered
            return {"source": body.source, "name": body.name, "sent": {kind: n for kind, n in sent.items() if n}}

        return request.app.state.jobs.start("stream-publish", work).public()

    @app.post("/api/stream/work", tags=["stream"], dependencies=admin, status_code=202)
    def stream_work(body: WorkIn, request: Request) -> dict:
        """Run the stream workers until each topic has been idle for `idle_exit` seconds (a job): vendors, then
        invoices (audited with the controls as they arrive), e-mails (linked to their invoices) and policies."""
        settings, target = stream_settings(), request.app.state.target
        kinds = [k for k in ("vendor", "invoice", "email", "compliance") if k in body.kinds]

        def work(job: Job) -> dict:
            conn = db.connect(target)
            counts: dict[str, dict] = {}
            job.total = len(kinds)
            try:
                for kind in kinds:
                    counts[kind] = stream.Worker(settings, conn, kind).run(idle_exit=body.idle_exit)
                    job.done += 1
            finally:
                conn.close()
            return {"counts": counts}

        return request.app.state.jobs.start("stream-work", work).public()

    @app.get("/api/stream/log", tags=["stream"], dependencies=viewer)
    def stream_log(limit: int = 60, topic: str | None = None, conn: db.Database = Depends(connection)) -> dict:
        """The newest messages the workers processed: topic, partition, offset, key, outcome, detail, the result
        it produced and how long after it was produced it was processed."""
        return {"messages": stream.recent_log(conn, max(1, min(limit, 500)), topic)}

    @app.get("/api/stream/peek", tags=["stream"], dependencies=viewer)
    def stream_peek(kind: Literal["vendor", "invoice", "email", "compliance"], n: int = 10) -> dict:
        """The newest messages of a topic as they sit in Kafka, with the fields that identify each."""
        settings = stream_settings()
        try:
            return {"topic": settings.topic(kind), "messages": stream.peek(settings, kind, max(1, min(n, 50)), timeout=3)}
        except stream.StreamUnavailable as error:
            raise HTTPException(503, str(error)) from None

    @app.get("/api/system", tags=["status"], dependencies=viewer)
    def system(conn: db.Database = Depends(connection)) -> dict:
        """What is running: the store, the Kafka broker, the chat model (asked whether it answers), the embedding
        model and the active policy."""
        out: dict = {"store": {"backend": conn.backend, "ledger": conn.scalar("SELECT value FROM meta WHERE key = 'dataset'")},
                     "policy_version": conn.scalar("SELECT version FROM company_policies WHERE is_active = 1")}
        try:
            settings = stream.StreamSettings.from_env()
            try:
                stream._cluster_topics(settings, timeout=2)
                out["kafka"] = {"configured": True, "connected": True, "bootstrap": settings.bootstrap, "prefix": settings.prefix}
            except stream.StreamUnavailable as error:
                out["kafka"] = {"configured": True, "connected": False, "bootstrap": settings.bootstrap, "error": str(error)}
        except stream.StreamUnavailable:
            out["kafka"] = {"configured": False, "connected": False}
        try:
            llm = LLMSettings.from_env()
            reachable, why = model_reachable(llm)
            out["model"] = {"configured": True, "name": llm.model, "reachable": reachable, "status": why,
                            "endpoint": re.sub(r"^https?://", "", llm.base_url).split("/")[0]}
        except RuntimeError:
            out["model"] = {"configured": False, "reachable": False}
        embedder = EndpointEmbedder.from_env()
        embedded = conn.scalar("SELECT COUNT(*) FROM policy_chunks WHERE embed_model = ?", (embedder.name,)) if embedder else 0
        out["embeddings"] = {"configured": embedder is not None, "model": embedder.name if embedder else None,
                             "embedded": int(embedded or 0), "passages": int(conn.scalar("SELECT COUNT(*) FROM policy_chunks") or 0)}
        return out

    @app.get("/api/rag/trace", tags=["policy"], dependencies=viewer)
    def rag_trace(q: str, k: int = 5, conn: db.Database = Depends(connection)) -> dict:
        """Every step retrieval takes for a question, laid open: what the policy graph recognises and the facts it
        derives, each passage's lexical and dense score and rank, their reciprocal-rank fusion, the context Ask AI
        would give the model, and the passages and the question in the embedding space (three principal
        components)."""
        question = q.strip()
        if not question:
            raise HTTPException(400, "empty question")
        k = max(1, min(k, 10))
        try:
            graph = PolicyGraph.from_db(conn)
            index = PolicyIndex.from_db(conn, version=graph.version, embedder=EndpointEmbedder.from_env())
        except ValueError as error:
            raise HTTPException(409, str(error)) from None
        dense_error = None
        try:
            steps = retrieval.trace(index, question)
        except Exception as error:                    # the embedding model does not answer: wording alone
            dense_error = f"{type(error).__name__}: {error}"[:300]
            index._dense = None
            steps = retrieval.trace(index, question)
        linked = graph.query(question, index)
        mode = index.default_mode() if steps["dense"] is not None else "lexical"
        best = steps[mode + "_rank"] if mode != "lexical" else steps["lexical_rank"]
        retrieved = [index.chunks[i] for i in np.argsort(best, kind="stable")[:k]]
        hits = [retrieval.Hit(c["chunk_id"], c["file_name"], c["version"], c["kind"], c["clause_id"], c["section"],
                              c["page"], c["text"], 1.0, 0) for c in retrieved]
        context = policy_graph_merge(linked.passages, hits, k)
        from_graph = {h.chunk_id for h in linked.passages}
        coords, query_point, explained = (None, None, [])
        if steps["dense"] is not None:
            coords, projected, explained = retrieval.projection(index._dense, steps["query_vector"])
            query_point = [round(float(x), 4) for x in projected[0]]
        passages = []
        for i, c in enumerate(index.chunks):
            row = {"chunk_id": c["chunk_id"], "document": c["file_name"], "version": c["version"], "kind": c["kind"],
                   "clause_id": c["clause_id"], "section": c["section"], "page": c["page"], "text": c["text"],
                   "lexical": round(float(steps["lexical"][i]), 5), "lexical_rank": int(steps["lexical_rank"][i])}
            if steps["dense"] is not None:
                row.update(dense=round(float(steps["dense"][i]), 5), dense_rank=int(steps["dense_rank"][i]),
                           hybrid=round(float(steps["hybrid"][i]), 6), hybrid_rank=int(steps["hybrid_rank"][i]),
                           point=[round(float(x), 4) for x in coords[i]])
            passages.append(row)
        return {"question": question, "mode": mode, "k": k, "rrf_k": retrieval.RRF_K,
                "embedding_model": index.embedder.name if steps["dense"] is not None else None, "dense_error": dense_error,
                "recognised": linked.recognised, "facts": [f.public() for f in linked.facts],
                "context": [{**hit_dict(h), "from": "graph" if h.chunk_id in from_graph else "retrieval"} for h in context],
                "passages": passages, "query_point": query_point, "explained": explained}

    @app.get("/api/knowledge", tags=["policy"], dependencies=viewer)
    def knowledge(conn: db.Database = Depends(connection)) -> dict:
        """The knowledge layer: the ingested documents, every passage with its page, kind, rule and whether it
        matches the registry, the registry of every version, and the passages in the embedding space."""
        documents = rows(conn.execute(
            "SELECT d.doc_id, d.file_name, d.title, d.version, d.pages, d.ingested_at, COUNT(c.chunk_id) AS passages "
            "FROM policy_documents d LEFT JOIN policy_chunks c ON c.doc_id = d.doc_id "
            "GROUP BY d.doc_id, d.file_name, d.title, d.version, d.pages, d.ingested_at ORDER BY d.doc_id"))
        chunks = conn.execute(
            "SELECT c.chunk_id, c.version, c.kind, c.clause_id, c.section, c.page, c.verified, c.text, c.embed_model, "
            "c.embedding, d.file_name FROM policy_chunks c JOIN policy_documents d ON d.doc_id = c.doc_id "
            "ORDER BY d.doc_id, c.position").fetchall()
        passages = [{"chunk_id": c["chunk_id"], "document": c["file_name"], "version": c["version"], "kind": c["kind"],
                     "clause_id": c["clause_id"], "section": c["section"], "page": c["page"],
                     "verified": None if c["verified"] is None else bool(c["verified"]), "text": c["text"],
                     "embed_model": c["embed_model"]} for c in chunks]
        # The map shows one model's vectors: the configured embedder's, or else the model most passages have.
        models = Counter(c["embed_model"] for c in chunks if c["embedding"] and c["embed_model"])
        embedder = EndpointEmbedder.from_env()
        mapped = embedder.name if embedder and embedder.name in models else (models.most_common(1)[0][0] if models else None)
        explained: list[float] = []
        chosen = [i for i, c in enumerate(chunks) if mapped and c["embed_model"] == mapped and c["embedding"]]
        vectors = [np.frombuffer(chunks[i]["embedding"], dtype=np.float32) for i in chosen]
        if vectors and len({len(v) for v in vectors}) == 1:
            coords, _, explained = retrieval.projection(np.vstack(vectors))
            for i, point in zip(chosen, coords):
                passages[i]["point"] = [round(float(x), 4) for x in point]
        registry = {}
        for version, clause, title, severity, kind in conn.execute(
                "SELECT version, clause_id, title, severity, kind FROM policy_clauses ORDER BY version, clause_id"):
            registry.setdefault(version, {})[clause] = {"title": title, "severity": severity, "kind": kind, "params": {}}
        for version, clause, name, value in conn.execute("SELECT version, clause_id, param_name, param_value FROM policy_parameters"):
            if clause in registry.get(version, {}):
                registry[version][clause]["params"][name] = json.loads(value) if isinstance(value, str) else value
        versions = rows(conn.execute("SELECT version, policy_name, effective_date, is_active FROM company_policies ORDER BY effective_date"))
        return {"documents": documents, "passages": passages, "explained": explained, "embedding_model": mapped, "registry": registry,
                "versions": [{**v, "effective_date": str(v["effective_date"] or ""), "is_active": bool(v["is_active"])} for v in versions]}

    @app.get("/api/ai", tags=["status"], dependencies=viewer)
    def ai_layer(conn: db.Database = Depends(connection)) -> dict:
        """The AI layer: the agents and their remits under the active policy, the configurations, what every stage
        of the audit trail has cost (calls, tokens, time), and the invoices whose latest result was audited by
        the agents, to replay."""
        version = conn.scalar("SELECT version FROM company_policies WHERE is_active = 1")
        judgement = [r[0] for r in conn.execute(
            "SELECT clause_id FROM policy_clauses WHERE version = ? AND kind = 'judgement' ORDER BY clause_id", (version,))]
        agents = [{"name": a.name, "title": a.title, "sections": [x.rstrip(".") for x in a.sections],
                   "judges": [c for c in judgement if c.startswith(a.sections)], "records": list(a.records),
                   "history_rules": list(a.history_rules)} for a in AGENTS.values()]
        configs = {name: {"controls": c.controls, "agents": c.agents, "challenger": c.challenger,
                          "confidence": c.confidence, "reruns": c.reruns, "temperature": c.temperature,
                          "rerun_temperature": c.rerun_temperature} for name, c in PRESETS.items()}
        stages = rows(conn.execute(
            "SELECT t.stage, t.actor, COUNT(*) AS steps, SUM(COALESCE(t.prompt_tokens, 0)) AS prompt_tokens, "
            "SUM(COALESCE(t.completion_tokens, 0)) AS completion_tokens, AVG(t.latency_ms) AS mean_latency_ms, "
            "SUM(CASE WHEN t.latency_ms IS NOT NULL THEN 1 ELSE 0 END) AS model_calls "
            "FROM audit_trail t JOIN latest_results m ON m.result_id = t.result_id "
            "GROUP BY t.stage, t.actor ORDER BY MIN(t.seq), t.stage, t.actor"))
        for row in stages:
            row["mean_latency_ms"] = None if row["mean_latency_ms"] is None else round(float(row["mean_latency_ms"]), 1)
        traced = rows(conn.execute(
            "SELECT invoice_id, configuration, route, risk_level, rc, flag_count, llm_calls, prompt_tokens, "
            "completion_tokens, latency_ms, created_at FROM v_latest_results WHERE configuration <> 'C1' "
            "ORDER BY llm_calls DESC, invoice_id LIMIT 200"))
        return {"policy_version": version, "model": model_name(), "agents": agents, "configurations": configs,
                "stages": stages, "traced": traced}

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
            {"id": "confidence", "label": "Confidence", "kind": "llm"},      # re-runs each agent that found something
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
    @app.get("/api/queue", tags=["review"], dependencies=viewer)
    def queue(request: Request, limit: int = 200, level: Literal["CRITICAL", "HIGH", "MEDIUM", "LOW"] | None = None,
              conn: db.Database = Depends(connection)) -> dict:
        """Invoices waiting for review, highest weighted risk first (at most 2,000), of one risk level or of every
        level. Each item lists the rules its kept findings break, the most severe first; `rules` gives the title of
        each rule in the active policy; `total` counts the invoices waiting at the level asked; `levels` counts the
        whole queue per risk level, with the amount at stake, whatever the list holds. Kept until the store changes
        (a decision changes it)."""
        limit = max(1, min(limit, 2000))
        return request.app.state.cache.get(f"queue:{limit}:{level}", conn, lambda: queue_of(conn, limit, level))

    def queue_of(conn: db.Database, limit: int, level: str | None) -> dict:
        where, params = ("WHERE risk_level = ? ", [level]) if level else ("", [])
        top = f"SELECT result_id FROM v_review_queue {where}ORDER BY rc DESC, invoice_id LIMIT {limit}"
        items = rows(conn.execute(top.replace("SELECT result_id", "SELECT *", 1), params))
        broken: dict[int, list[tuple[int, str]]] = {}
        for result_id, clause, severity in conn.execute(
                f"SELECT result_id, clause, severity FROM audit_flags WHERE status = 'kept' AND result_id IN ({top})",
                params):
            rank = SEVERITIES.index(severity) if severity in SEVERITIES else len(SEVERITIES)
            broken.setdefault(int(result_id), []).append((rank, clause or "?"))
        for item in items:
            item["rules"] = list(dict.fromkeys(c for _, c in sorted(broken.get(int(item["result_id"]), []))))
        present = {c for item in items for c in item["rules"]}
        titles = {clause: title for clause, title in conn.execute(
            "SELECT clause_id, title FROM policy_clauses WHERE version = "
            "(SELECT version FROM company_policies WHERE is_active = 1)") if clause in present}
        levels = {lv: {"invoices": int(n), "amount": round(float(amount or 0), 2)} for lv, n, amount in conn.execute(
            "SELECT risk_level, COUNT(*), SUM(amount) FROM v_review_queue GROUP BY risk_level")}
        return {"total": int(conn.scalar(f"SELECT COUNT(*) FROM v_review_queue {where}", params) or 0), "items": items,
                "rules": {c: titles.get(c) for c in sorted(present)}, "levels": levels}

    @app.get("/api/invoices", tags=["review"], dependencies=viewer)
    def invoices(q: str = "", limit: int = 50, conn: db.Database = Depends(connection)) -> dict:
        """Search invoices by id or vendor name, with their latest audit outcome."""
        limit = max(1, min(limit, 500))
        like = f"%{q.strip()}%"
        # The matching invoices first, then the latest result of each of them only.
        items = rows(conn.execute(
            "SELECT i.invoice_id, i.vendor_id, i.vendor_name, i.date, i.amount, r.route, r.risk_level, r.rc, "
            "r.workflow_status FROM (SELECT i.invoice_id, i.vendor_id, v.vendor_name, i.date, i.amount "
            "FROM invoices i JOIN vendor_master v ON v.vendor_id = i.vendor_id "
            f"WHERE i.invoice_id LIKE ? OR v.vendor_name LIKE ? ORDER BY i.invoice_id LIMIT {limit}) i "
            "LEFT JOIN latest_results m ON m.invoice_id = i.invoice_id "
            "LEFT JOIN audit_results r ON r.result_id = m.result_id ORDER BY i.invoice_id", (like, like)))
        return {"items": items}

    @app.get("/api/invoices/{invoice_id}", tags=["review"], dependencies=viewer)
    def invoice(invoice_id: str, with_label: bool = False, conn: db.Database = Depends(connection)) -> dict:
        """The records of an invoice, its vendor's last 40 other invoices, the vendor e-mails that name it, and its
        latest result with the audit pack and trail; with_label adds the benchmark label."""
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
            result.update(pack=json.loads(row["audit_pack"]), trail=trail, integrity=integrity_of(conn, row))
        history = txn.pop("vendor_history")
        out = {"records": txn, "history": {"total": len(history), "items": history[-40:]}, "result": result,
               "emails": emails.for_invoice(conn, invoice_id)}
        if with_label:
            label = conn.execute("SELECT label, class_id, clause_ids, hard_negative_type, note FROM benchmark_labels "
                                 "WHERE invoice_id = ?", (invoice_id,)).fetchone()
            out["benchmark_label"] = dict(zip(label.keys(), label)) if label else None
        return out

    @app.post("/api/results/{result_id}/decision", tags=["review"], dependencies=reviewer)
    def decide(result_id: int, body: DecisionIn, request: Request, conn: db.Database = Depends(connection)) -> dict:
        """Record a reviewer's decision on a result: approve, reject or override (an override needs a
        justification). Signed in with a user's token, the decision carries that user's name."""
        who = request.state.principal
        reviewer_name = who["name"] if who["via"] == "account" else body.reviewer
        try:
            db.record_decision(conn, result_id, body.decision, reviewer_name, body.justification)
        except KeyError as error:
            raise HTTPException(404, str(error).strip("'")) from None
        except ValueError as error:
            raise HTTPException(400, str(error)) from None
        row = conn.execute("SELECT invoice_id, workflow_status FROM audit_results WHERE result_id = ?",
                           (result_id,)).fetchone()
        return {"result_id": result_id, "invoice_id": row["invoice_id"], "workflow_status": row["workflow_status"]}

    @app.post("/api/invoices/{invoice_id}/audit", tags=["review"], dependencies=reviewer, status_code=202)
    def audit(invoice_id: str, body: AuditIn, request: Request) -> dict:
        """Audit one invoice again under a configuration (a background job), with the policy version in force on
        the invoice's date; C2 to C5 need a model."""
        invoice_id = invoice_id.strip().upper()
        config = PRESETS[body.config]
        client = chat_client() if config.agents != "none" else None
        if config.agents != "none" and client is None:
            raise HTTPException(400, f"{body.config} needs a model; none is configured or it does not answer "
                                     "(see .env.example)")
        target = request.app.state.target

        def work(job: Job) -> dict:
            conn = db.connect(target)
            try:
                if db.extract_one(conn, invoice_id) is None:
                    raise KeyError(f"{invoice_id} is not in the ledger")
                job.total = 1
                version = db.versions_in_force(conn, [invoice_id])[invoice_id]
                run_id = service.audit_invoices(conn, config, db.read_policy(conn, version), client, [invoice_id],
                                                note="audited from the web frontend")
                job.done = 1
                row = db.latest_result(conn, invoice_id)
                return {"run_id": run_id, "invoice_id": invoice_id, "policy_version": version, "route": row["route"],
                        "workflow_status": row["workflow_status"]}
            finally:
                conn.close()

        return request.app.state.jobs.start("audit", work).public()

    # -- policy --------------------------------------------------------------
    @app.get("/api/policy", tags=["policy"], dependencies=viewer)
    def policy(request: Request, conn: db.Database = Depends(connection)) -> dict:
        """The stored policy versions and how each was adopted, the rules of the active one, the ingested
        documents, and the timeline: which version governs the invoices of which dates (each invoice is judged by
        the version in force on its date), how many invoices of the ledger each governs and how many of those were
        last audited under another version."""
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
        timeline = request.app.state.cache.get("timeline", conn, lambda: db.timeline_summary(conn))
        return {"active": active, "versions": versions, "rules": rules, "documents": documents, "timeline": timeline,
                "under_other_version": sum(t["under_other_version"] for t in timeline),
                "unaudited": sum(t["unaudited"] for t in timeline)}

    @app.post("/api/policy/activate", tags=["policy"], dependencies=admin)
    def activate(body: VersionIn, conn: db.Database = Depends(connection)) -> dict:
        """Make a stored policy version the active one. It governs the invoices dated from its effective date on;
        the invoices before that date stay under the versions in force then."""
        try:
            db.set_active_policy(conn, body.version)
        except KeyError as error:
            raise HTTPException(404, str(error).strip("'")) from None
        return {"active": body.version}

    @app.post("/api/policy/preview", tags=["policy"], dependencies=admin)
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

    @app.post("/api/policy/adopt", tags=["policy"], dependencies=admin)
    def adopt(body: AdoptIn, conn: db.Database = Depends(connection)) -> dict:
        """Adopt a previewed policy document as a new version; refused with the problems if it cannot be executed."""
        report = policy_extract.adopt(conn, upload_path(body.upload_id), activate=body.activate, replace=body.replace)
        if not report["adopted"]:
            raise HTTPException(422, {"message": "the document was not adopted", "problems": report["problems"]})
        return report

    @app.post("/api/policy/simulate", tags=["policy"], dependencies=admin, status_code=202)
    def simulate(body: AdoptIn, request: Request, conn: db.Database = Depends(connection)) -> dict:
        """What a previewed policy document would do to the ledger before it is adopted: every invoice audited by
        the controls under the active policy and under the document, in memory (a job); nothing is stored."""
        found = policy_extract.build(upload_path(body.upload_id), db.read_policy(conn).registry)
        if not found.usable:
            raise HTTPException(422, {"message": "the document cannot be executed", "problems": found.problems})
        target, registry = request.app.state.target, found.registry

        def work(job: Job) -> dict:
            store = db.connect(target)
            try:
                return simulation.simulate(store, registry)
            finally:
                store.close()

        return request.app.state.jobs.start("simulate", work).public()

    @app.post("/api/policy/propose", tags=["policy"], dependencies=admin, status_code=202)
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

    @app.post("/api/policy/confirm", tags=["policy"], dependencies=admin)
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

    @app.post("/api/policy/apply", tags=["policy"], dependencies=admin, status_code=202)
    def apply(request: Request) -> dict:
        """Bring the audit results in line with the policy timeline (a background job): every invoice the active
        version governs, and every invoice last audited under a version that does not govern it, is audited again
        with the controls under the version in force on its date. An invoice approved under the rules of its day
        is not judged by a version that took effect after it; the other invoices keep their results."""
        target = request.app.state.target

        def work(job: Job) -> dict:
            conn = db.connect(target)
            try:
                active = db.read_policy(conn)
                ids, unchanged = service.out_of_line(conn)
                job.total = len(ids)

                def progress(done: int, total: int) -> None:
                    job.done, job.total = done, total

                runs = service.audit_in_force(conn, PRESETS["C1"], None, ids, progress=progress,
                                              note=f"policy version {active.version} applied from the web frontend")
                return {**service.runs_summary(conn, runs), "unchanged": unchanged, "timeline": db.timeline_summary(conn)}
            finally:
                conn.close()

        return request.app.state.jobs.start("apply-policy", work).public()

    # -- ledger --------------------------------------------------------------
    @app.post("/api/ledger", tags=["ledger"], dependencies=admin, status_code=202)
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

    @app.get("/api/search", tags=["policy"], dependencies=viewer)
    def search(q: str, k: int = 4, conn: db.Database = Depends(connection)) -> dict:
        """Search the policy documents. With a chat model the question is first restated in the documents'
        vocabulary and ranked by the hybrid ranker, the best measured setting (RESULTS.md, Section 8); without
        one, by meaning (embeddings) or by wording."""
        question = q.strip()
        if not question:
            raise HTTPException(400, "empty question")
        try:
            index = PolicyIndex.from_db(conn, embedder=EndpointEmbedder.from_env())
        except ValueError as error:
            raise HTTPException(409, str(error)) from None
        client = chat_client()
        restated = index.rewrite(question, client) if client else None
        mode = index.default_mode(restated=client is not None)
        hits = index.search(restated or question, k=max(1, min(k, 10)), mode=mode)
        added = restated[len(question):].strip() if restated else ""
        return {"mode": mode, "restated": added or None, "hits": [hit_dict(h) for h in hits]}

    @app.get("/api/policy/graph", tags=["policy"], dependencies=viewer)
    def policy_graph(version: str | None = None, conn: db.Database = Depends(connection)) -> dict:
        """The policy as a knowledge graph, built by code from the clause registry, the ingested documents and
        the code that checks each rule: the version (default: the active one), its sections, rules,
        parameters, the roles of the approval limits, the control functions and agents that check the rules,
        the pages that state them, and what the other stored versions change (docs/POLICY_GRAPH.md)."""
        try:
            return PolicyGraph.from_db(conn, version).public()
        except ValueError as error:
            raise HTTPException(404, str(error)) from None

    @app.get("/api/policy/graph/ask", tags=["policy"], dependencies=viewer)
    def ask_graph(q: str, version: str | None = None, conn: db.Database = Depends(connection)) -> dict:
        """Ask the policy graph: what the question names (rules, versions, roles, amounts, agents, severities),
        the facts that follow from the graph with the passage each cites, the passages, and the nodes used."""
        question = q.strip()
        if not question:
            raise HTTPException(400, "empty question")
        try:
            graph = PolicyGraph.from_db(conn, version)
        except ValueError as error:
            raise HTTPException(404, str(error)) from None
        try:
            index = PolicyIndex.from_db(conn, version=graph.version)
        except ValueError:
            index = None                                       # no document ingested: the registry alone
        found = graph.query(question, index)
        return {"question": question, "version": graph.version, "recognised": found.recognised,
                "facts": [f.public() for f in found.facts], "passages": [hit_dict(h) for h in found.passages],
                "nodes": found.nodes}

    # -- the ledger as a graph -----------------------------------------------
    @app.get("/api/case-graph", tags=["analytics"], dependencies=viewer)
    def case_graph_view(focus: str | None = None, limit: int = 250, conn: db.Database = Depends(connection)) -> dict:
        """The audited ledger as a knowledge graph (docs/CASE_GRAPH.md): vendors, invoices with findings, the rules they
        break, approvers and rings. Without `focus` the rings of the ledger; with it the neighbourhood of a vendor, an
        invoice, an approver, a ring or a rule, by id or name. Built by code from the audit; nothing is stored."""
        graph = case_graph(app, conn)
        if focus and graph.resolve(focus) is None:
            raise HTTPException(404, f"nothing in the graph is named {focus!r}")
        return graph.public(focus, max(10, min(limit, 600)))

    @app.get("/api/case-graph/ask", tags=["analytics"], dependencies=viewer)
    def ask_case_graph(q: str, conn: db.Database = Depends(connection)) -> dict:
        """Ask the ledger graph: what the question names (invoices, vendors, approvers, rules, kinds of fraud), the
        facts that follow from the graph with the numbers they rest on, and the nodes used. No model is involved."""
        question = q.strip()
        if not question:
            raise HTTPException(400, "empty question")
        found = case_graph(app, conn).query(question)
        return {"question": question, "recognised": found.recognised, "facts": [f.public() for f in found.facts],
                "nodes": found.nodes}

    # -- copilot -------------------------------------------------------------
    @app.post("/api/copilot/ask", tags=["copilot"], dependencies=viewer, status_code=202)
    def ask(body: AskIn, request: Request) -> dict:
        """A question about the policy or an audited invoice, answered from the passages and the facts of the
        policy graph, with citations (a job)."""
        target, client = request.app.state.target, chat_client()

        def work(job: Job) -> dict:
            conn = db.connect(target)
            try:
                index = PolicyIndex.from_db(conn, embedder=EndpointEmbedder.from_env())
                out = copilot.answer(body.question, conn, index, client,
                                     invoice_id=(body.invoice_id or "").strip().upper() or None,
                                     graph=PolicyGraph.from_db(conn), cases=case_graph(request.app, conn))
            finally:
                conn.close()
            return {"answer": out["answer"], "invoice_id": out["invoice_id"], "model": model_name() if client else None,
                    "passages": [hit_dict(h) for h in out["passages"]], "sources": [hit_dict(h) for h in out["sources"]],
                    "facts": [f.public() for f in out["facts"]], "graph_nodes": out["graph_nodes"],
                    "case_facts": [f.public() for f in out["case_facts"]], "case_nodes": out["case_nodes"]}

        return request.app.state.jobs.start("copilot", work).public()

    @app.post("/api/copilot/data", tags=["copilot"], dependencies=viewer, status_code=202)
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
    @app.get("/api/jobs/{job_id}", tags=["status"], dependencies=viewer)
    def job(job_id: str, request: Request) -> dict:
        """The state of a background job: queued, running, done (with its result) or failed (with the reason)."""
        found = request.app.state.jobs.get(job_id)
        if found is None:
            raise HTTPException(404, "no such job")
        return found.public()

    @app.get("/api/results", tags=["results"], dependencies=viewer)
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
        # The pilots on the development ledger, then the samples of benchmark ledgers 101 and 202.
        pilots = {}
        for pattern in ("pilot_seed_909/*.meta.json", "bench_seed_101/*-sample34.meta.json",
                        "bench_seed_202/*-igpu90.meta.json"):
            for meta in sorted(RESULTS.glob(pattern)):
                m = read_json(meta)
                pilots[meta.name.removesuffix(".meta.json")] = {"model": m["model"], "dataset": m.get("dataset"),
                                                                 "summary": m["summary"], "started": m["started"],
                                                                 "finished": m["finished"]}
        return {"benchmark": benchmark, "policy_swap": policy_swap, "policy_change": read_json(RESULTS / "policy_change.json"),
                "scalability": scalability_with_huge(),
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
            # The page itself is checked every time, so that a new build reaches the browser at once.
            return FileResponse(frontend / "index.html", headers={"Cache-Control": "no-cache"})

    return app


def serve(host: str = "127.0.0.1", port: int = 8000, target: str | None = None) -> None:
    import uvicorn
    uvicorn.run(create_app(target), host=host, port=port, log_level="info")
