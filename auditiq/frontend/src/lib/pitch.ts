// The pitch of the architecture: a guided tour that follows one invoice through the whole platform, the hard
// problems each part solves, and the size of the code base. Shown by pages/ArchitecturePage.tsx.
import type { Health, Overview, PolicyOverview, StreamStatus } from "../api/types";
import { count, percent } from "./format";
import { short } from "./chart";
import { EDGES, GROUPS, NODES } from "./architecture";

/** Figures of the running platform, read from the API when the page opens. */
export interface LiveFacts {
  overview?: Overview;
  stream?: StreamStatus;
  health?: Health;
  policy?: PolicyOverview;
}

export interface TourStep {
  id: string;
  title: string;
  /** What happens here, in the words to say to the panel. */
  story: string;
  /** Why it is not simple: the engineering problem this part solves. */
  hard: string;
  /** The components the step is about. */
  nodes: string[];
  /** The page that shows it at work. */
  page: string;
  /** Live figures for the step, from the running platform. */
  figures: (f: LiveFacts) => string[];
}

const topics = (f: LiveFacts) => f.stream?.topics ?? [];

export const TOUR: TourStep[] = [
  {
    id: "sources",
    title: "1 · A real procure-to-pay ledger comes in",
    story: "Five linked tables (vendors, purchase orders, goods receipts, invoices and approvals), the vendors' e-mails and the company's audit procedure as a PDF. The benchmark generator writes ledgers of 5,000 to 500,000 invoices with planted frauds and an answer key the audit never sees.",
    hard: "Ground truth for every invoice, look-alike hard negatives and compound frauds, reproducible byte for byte from a seed.",
    nodes: ["erp", "mailbox", "sop", "bench", "demo"],
    page: "/",
    figures: (f) => f.overview ? [`${count(f.overview.invoices)} invoices`, `${count(f.overview.vendors)} vendors`, `ledger ${f.overview.ledger ?? "none"}`] : [],
  },
  {
    id: "streaming",
    title: "2 · Streamed through Kafka, exactly once",
    story: "The launcher starts a Kafka broker and publishes the ledger, the e-mails and the policies to four partitioned topics; invoices are keyed by vendor so a vendor's history stays in order. Stateless workers store each batch together with its offsets in one database transaction.",
    hard: "Exactly-once processing without Kafka transactions: offsets written in the same transaction as the data, and a worker that lost its partitions is fenced off so nothing is written twice.",
    nodes: ["launcher", "producer", "broker", "t-vendor", "t-invoice", "t-email", "t-compliance", "workers", "emails", "streamT", "kafkaLocal"],
    page: "/kafka",
    figures: (f) => {
      const t = topics(f);
      if (!t.length) return [];
      return [`${t.length} topics · ${t.reduce((a, x) => a + x.partitions, 0)} partitions`, `${short(t.reduce((a, x) => a + x.processed, 0))} messages processed`, `lag ${count(t.reduce((a, x) => a + x.lag, 0))}`];
    },
  },
  {
    id: "policy",
    title: "3 · The policy is data, versioned by date",
    story: "Thresholds are not in the code. They are read from the wording of the policy PDF by patterns; for free wording a model proposes values with quotes, code checks every quote is in the document, and a person confirms. A new version can be simulated over the whole ledger before it is adopted.",
    hard: "Each invoice is judged by the version in force on its own date, so adopting a policy never rewrites history; and no value a model read is applied without a verified quote and a human.",
    nodes: ["sop", "pdfIngest", "compiler", "reader", "confirm", "registry", "simulation", "policyT"],
    page: "/policy",
    figures: (f) => f.policy ? [`${f.policy.versions.length} policy versions`, `${f.policy.rules.length} rules in v${f.policy.active}`, `${f.policy.rules.filter((r) => r.kind === "judgement").length} need judgement`] : [],
  },
  {
    id: "controls",
    title: "4 · Evidence, then twelve controls as code",
    story: "For each invoice the engine joins its purchase order, goods receipt, approvals, linked e-mails and the vendor's earlier invoices. Twelve deterministic controls apply the thresholds in force: three-way match, duplicates, GSTIN, splitting, weekends, round sums, blocked vendors and approval limits.",
    hard: "A vendor-history index keeps the cost per invoice flat as the ledger grows from 20,000 to 500,000 invoices; every finding carries its evidence and the clause it breaks.",
    nodes: ["extract", "history", "controls", "ledger", "mail", "service"],
    page: "/ai",
    figures: (f) => {
      const o = f.overview;
      if (!o) return [];
      const controls = o.findings_by_rule.filter((r) => r.source === "control").reduce((a, r) => a + r.findings, 0);
      return [`${count(o.audited)} invoices audited`, `${count(controls)} control findings`, `${o.findings_by_rule.length} rules fired`];
    },
  },
  {
    id: "agents",
    title: "5 · Specialist agents, a challenger, a confidence",
    story: "A LangGraph state graph runs three specialist agents in parallel, each limited to the rules that need reading. A challenger removes findings the evidence does not support; each survivor gets a confidence from grounding, clause validity and agreement over three re-runs. Five configurations (C1 to C5) are five graphs over the same stages.",
    hard: "Hallucination is contained by construction: remits enforced by code, a challenger, quotes verified and confidence-weighted scoring, measured against a single-prompt baseline (C2).",
    nodes: ["math", "tax", "vendorint", "single", "challenger", "confidence", "chat", "cache"],
    page: "/ai",
    figures: (f) => {
      const c = f.overview?.coverage;
      return [f.health?.model ? `model ${f.health.model}` : "no model configured: C1 runs", ...(c ? [`${count(c.judgement_run)} invoices through the agents`] : [])];
    },
  },
  {
    id: "decision",
    title: "6 · Risk, routing and a person in the loop",
    story: "Findings are weighted by severity into a count-based risk R0 and a confidence-weighted risk Rc. Above the threshold an invoice is escalated to a reviewer, who approves, rejects or overrides with a justification; the rest are approved. Revisions say exactly what each control finding requires; everything lands in an audit pack and trail.",
    hard: "Every decision is explainable and traceable: score, route, reviewer, justification and the revision that would clear each finding, computed, not generated.",
    nodes: ["score", "route", "review", "corrections", "pack", "audit", "views"],
    page: "/review",
    figures: (f) => {
      const o = f.overview;
      if (!o) return [];
      return [`${count(o.routes.escalate ?? 0)} escalated`, `${count(o.routes.approve ?? 0)} approved automatically`, `${count(o.findings)} findings kept`];
    },
  },
  {
    id: "intelligence",
    title: "7 · Forensic analytics and collusion rings",
    story: "Over the audited ledger: Benford's first-digit tests, spend concentration (Gini), amounts against approval limits, and coverage against the answer key. The ring detector links vendors and approvers by shared PAN or GSTIN and by approvals of flagged invoices above their role's rate.",
    hard: "A one-sided binomial test per approver with false-discovery-rate control, so a ring is reported because the statistics say so, not because a threshold was tuned.",
    nodes: ["analytics", "rings", "labels", "ledger", "audit"],
    page: "/rings",
    figures: (f) => {
      const k = f.overview?.coverage?.answer_key;
      return k ? [`precision ${k.precision === null ? "–" : k.precision.toFixed(3)}`, `recall ${k.recall === null ? "–" : k.recall.toFixed(3)}`, `${count(k.false_alarms)} false alarms`] : [];
    },
  },
  {
    id: "knowledge",
    title: "8 · Knowledge graphs and Graph RAG",
    story: "Two knowledge graphs are built by code, never by a model: the policy graph (version, sections, clauses, parameters, the code that checks each) and the audit graph (vendors, invoices, rules broken, approvers, rings). Ask AI answers from graph facts and hybrid retrieval with citations, or writes one guarded SELECT.",
    hard: "Answers grounded in facts that can be wrong only where the data is; hybrid TF-IDF + dense retrieval fused by reciprocal rank; SQL confined to one read-only statement.",
    nodes: ["policyGraph", "caseGraph", "retrieval", "embed", "copilot", "guard", "datadict"],
    page: "/ask",
    figures: () => [],
  },
  {
    id: "serving",
    title: "9 · Served to people, securely",
    story: "A FastAPI service with role-based tokens (viewer, reviewer, admin), long work as background jobs, and security headers on every response; this React application with 3D views on top; a command line for every operation.",
    hard: "Every request opens its own connection, on SQLite or PostgreSQL 17 with the same schema; the copilot's queries run as a read-only database role.",
    nodes: ["users", "web", "api", "access", "cli", "dash", "engines"],
    page: "/pipeline",
    figures: (f) => f.health ? [`API v${f.health.version}`, `${f.health.backend} store`, f.health.auth ? "tokens required" : "open access (local)"] : [],
  },
  {
    id: "delivery",
    title: "10 · Delivered and reproducible",
    story: "One container image, a compose file with the API, the workers, Kafka and PostgreSQL, and CI that runs the tests on both databases with a live Kafka broker, the frontend checks, browser tests and the container builds. One script reproduces every number that needs no model.",
    hard: "Results are re-derivable: generated data from seeds, committed hashes, and a reproduce script that compares every figure with the committed one.",
    nodes: ["container", "compose", "ci", "kafkaLocal", "pgLocal", "reproduce"],
    page: "/results",
    figures: () => [],
  },
  {
    id: "end-to-end",
    title: "End to end: one invoice, every layer",
    story: "From the ERP record to the reviewer's screen, one invoice crosses Kafka, the workers, the store, evidence extraction, the controls, the agents, the challenger, the confidence, the score and route, a person, the audit pack and the API: every layer measured, logged and reproducible.",
    hard: `${GROUPS.length} subsystems, ${NODES.length} components and ${EDGES.length} connections, each one in the code and shown working on a page of this application.`,
    nodes: [],
    page: "/",
    figures: (f) => f.overview ? [`${count(f.overview.invoices)} invoices`, `${percent(f.overview.audited / Math.max(1, f.overview.invoices), 1)} audited`, `${count(f.overview.findings)} findings`] : [],
  },
];

/** Short live figures shown on the components, by component id. */
export function liveBadges(f: LiveFacts): Record<string, string> {
  const out: Record<string, string> = {};
  const { health: h, overview: o, stream: s, policy: p } = f;
  if (h) {
    out.api = `v${h.version} · ${h.backend}`;
    out.chat = h.model ? "configured" : "not configured";
    if (h.ledger) out.erp = h.ledger;
    if (h.policy_version) out.registry = `v${h.policy_version} active`;
  }
  if (o) {
    out.ledger = `${short(o.invoices)} invoices`;
    out.audit = `${short(o.audited)} results`;
    out.views = `${count(o.states.PENDING_REVIEW ?? 0)} waiting`;
    out.review = `${count(o.states.PENDING_REVIEW ?? 0)} waiting`;
    out.route = `${count(o.routes.escalate ?? 0)} escalated`;
    out.score = `${short(o.audited)} scored`;
    out.controls = `${count(o.findings_by_rule.filter((r) => r.source === "control").reduce((t, r) => t + r.findings, 0))} findings`;
    out.pack = `${count(o.runs.length)} runs`;
    if (o.coverage?.answer_key) out.labels = "present";
  }
  if (s) {
    const down = !s.configured ? "no broker" : s.error ? "broker down" : null;
    for (const t of s.topics) out[`t-${t.kind}`] = down ?? `${short(t.messages)} msgs`;
    out.workers = down ?? `${short(s.topics.reduce((t, x) => t + x.processed, 0))} processed`;
    if (!down && s.topics.length) out.broker = `${s.topics.reduce((t, x) => t + x.partitions, 0)} partitions`;
  }
  if (p) out.policyT = `${p.versions.length} versions`;
  return out;
}

/** The path of one invoice through the platform, drawn in the last step of the tour. */
export const INVOICE_PATH = ["erp", "producer", "t-invoice", "workers", "service", "extract", "controls", "math", "challenger", "confidence", "score", "route", "review", "pack", "audit", "views", "api"];

/** The size of the code base, counted in the repository on 21 November 2026 (git ls-files; pytest --collect-only). */
export const CODEBASE = [
  { label: "Python modules", value: "100", hint: "≈ 26,800 lines · auditiq, bench, evaluation, scripts" },
  { label: "Frontend", value: "≈ 13,100", hint: "lines of TypeScript · 21 pages · 10 3D scenes" },
  { label: "Automated tests", value: "738", hint: "652 Python (SQLite + PostgreSQL) · 74 frontend · 12 browser e2e" },
  { label: "REST API", value: "53", hint: "endpoints · roles · background jobs" },
  { label: "Database", value: "23", hint: "tables + 2 views · SQLite or PostgreSQL 17" },
];

/** What makes the project more than a demo: each a problem solved, and where to see it. */
export const HARD_PROBLEMS: { title: string; text: string; page: string }[] = [
  { title: "Exactly-once streaming", text: "Kafka offsets stored in the same transaction as the data; fenced workers; per-vendor ordering.", page: "/kafka" },
  { title: "Policy as versioned data", text: "Thresholds read from the PDF's wording; each invoice judged by the version in force on its date.", page: "/policy" },
  { title: "Controls before models", text: "Twelve rules decided by code; agents only for the four that need reading, within enforced remits.", page: "/ai" },
  { title: "Hallucination contained", text: "Challenger, verified quotes, confidence from grounding, validity and agreement; a single-prompt baseline to compare.", page: "/ai" },
  { title: "Human in the loop", text: "Escalation by risk, reviewer decisions with justification, computed revisions, a full audit trail.", page: "/review" },
  { title: "Statistics, not thresholds", text: "Benford tests, Gini concentration, binomial tests with false-discovery-rate control for collusion rings.", page: "/rings" },
  { title: "Grounded answers", text: "Two code-built knowledge graphs, hybrid retrieval with rank fusion, one read-only SELECT for data questions.", page: "/ask" },
  { title: "Measured and reproducible", text: "Seeded benchmark ledgers with answer keys, scale to 500,000 invoices, every number re-derivable by a script.", page: "/results" },
  { title: "Exact explanations", text: "A gradient-boosted risk screen explained with exact TreeSHAP, checked against the Shapley formula; counterfactuals verified by running the controls again.", page: "/explain" },
  { title: "Auditing the audit", text: "Twelve checks of the sealed record and the review: segregation of duties, rubber-stamping, overrides, rejections undone; 54 of 54 planted faults found.", page: "/investigator" },
  { title: "Payment-redirection fraud", text: "Vendor e-mails triaged by code: look-alike domains, pressure and new bank accounts; the payment held until confirmed by telephone.", page: "/mail" },
  { title: "Agents with tools", text: "An audit agent that plans calls to fifteen read-only tools, cites every step and lists any number no tool returned.", page: "/agent" },
];
