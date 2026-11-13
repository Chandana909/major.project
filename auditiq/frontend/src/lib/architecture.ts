// The architecture of the platform as data: every component, where it lives in the code, and the data that
// moves between them; and the geometry that turns it into paths. Drawn by components/ArchitectureDiagram.tsx.

export type NodeKind = "external" | "code" | "llm" | "person" | "queue" | "store" | "serve" | "model" | "ops";
export type Side = "l" | "r" | "t" | "b";
export type Point = [number, number];

export interface ArchNode {
  id: string;
  x: number;
  y: number;
  w: number;
  h: number;
  title: string;
  kind: NodeKind;
  lines?: string[];
  chips?: { label: string; tone?: string; title?: string }[];
  detail: string;
  files?: string[];
  /** The pipeline stage the node stands for, to dim it under a configuration that does not run it. */
  stage?: string;
}

export interface Cluster {
  id: string;
  x: number;
  y: number;
  w: number;
  h: number;
  title: string;
  note?: string;
  tone: string;
}

export interface ArchEdge {
  from: string;
  to: string;
  label?: string;
  kind?: "data" | "control" | "model" | "dashed";
  fromSide?: Side;
  toSide?: Side;
  /** Offset of the anchor along its side, from -0.5 to 0.5 of the side. */
  fromAt?: number;
  toAt?: number;
  /** Corners of the path between the two anchors. */
  via?: Point[];
  labelAt?: Point;
}

export const KIND_STYLE: Record<NodeKind, { color: string; label: string }> = {
  external: { color: "#475569", label: "Outside the platform" },
  code: { color: "#0f766e", label: "Deterministic code" },
  llm: { color: "#7c3aed", label: "Language model stage" },
  person: { color: "#d97706", label: "A person decides" },
  queue: { color: "#ea580c", label: "Kafka topic" },
  store: { color: "#2563eb", label: "Tables" },
  serve: { color: "#15803d", label: "Interface" },
  model: { color: "#a21caf", label: "Model server" },
  ops: { color: "#334155", label: "Delivery" },
};

export const EDGE_COLOR = { data: "#64748b", control: "#0f766e", model: "#a21caf", dashed: "#94a3b8" };

export const CLUSTERS: Cluster[] = [
  { id: "sources", x: 16, y: 40, w: 236, h: 380, title: "Sources", note: "outside the platform", tone: "#475569" },
  { id: "ingestion", x: 272, y: 40, w: 300, h: 660, title: "Ingestion", note: "batch and streaming", tone: "#ea580c" },
  { id: "kafka", x: 288, y: 272, w: 268, h: 262, title: "Kafka 4.3.2 · KRaft", note: "4 topics · keyed by vendor", tone: "#ea580c" },
  { id: "engine", x: 592, y: 40, w: 640, h: 660, title: "Audit engine · LangGraph StateGraph", note: "one graph run per invoice · configurations C1 to C5", tone: "#0f766e" },
  { id: "agents", x: 608, y: 236, w: 608, h: 132, title: "Specialist agents", note: "judgement clauses · remits by policy section", tone: "#7c3aed" },
  { id: "serving", x: 1252, y: 40, w: 372, h: 660, title: "Serving & interfaces", note: "FastAPI · React", tone: "#15803d" },
  { id: "policy", x: 16, y: 720, w: 556, h: 440, title: "Policy as data", note: "the only place thresholds live", tone: "#0f766e" },
  { id: "store", x: 592, y: 720, w: 640, h: 440, title: "Store · SQLite or PostgreSQL 17", note: "one schema · one connection per request", tone: "#2563eb" },
  { id: "models", x: 1252, y: 720, w: 372, h: 200, title: "Models · Ollama", note: "local · OpenAI-compatible", tone: "#a21caf" },
  { id: "delivery", x: 1252, y: 940, w: 372, h: 220, title: "Delivery & operations", tone: "#334155" },
];

const RULE_IDS = ["2.1.1", "2.1.2", "2.1.3", "2.2.1", "3.1.1", "3.1.2", "3.1.3", "4.1.1", "4.2.1", "4.3.1", "4.4.1", "5.1.1"];
const PAGES = ["Overview", "Review", "Invoices", "Analytics", "Rings", "Policy", "Ask AI", "Pipeline", "Results"];

export const NODES: ArchNode[] = [
  // Sources
  { id: "erp", x: 32, y: 84, w: 204, h: 96, title: "ERP ledger", kind: "external", lines: ["Excel workbook or zip of CSVs", "vendors · POs · GRNs", "invoices · approval logs"],
    detail: "The procure-to-pay ledger: vendor master, purchase orders, goods receipts, invoices and approval logs. It arrives as a workbook or a zip of CSV files, or message by message through Kafka." },
  { id: "mailbox", x: 32, y: 196, w: 204, h: 80, title: "Vendor mailbox", kind: "external", lines: ["correspondence as .mbox", "invoice numbers in the text"],
    detail: "Vendor correspondence. Each e-mail is parsed for invoice numbers and linked to the latest invoice dated on or before it." },
  { id: "bench", x: 32, y: 292, w: 204, h: 112, title: "Benchmark generator", kind: "external", lines: ["auditiq_bench · six ledgers", "5,000 to 500,000 invoices", "anomalies, hard negatives", "and an answer key"],
    detail: "Generates the synthetic ledgers used for evaluation: injected anomalies of every rule, look-alike hard negatives and an answer key per invoice.", files: ["auditiq_bench/"] },

  // Ingestion
  { id: "importer", x: 288, y: 84, w: 268, h: 80, title: "Ledger import", kind: "code", lines: ["ledger_import.py · POST /api/ledger", "every table checked before anything is replaced"],
    detail: "Loads a ledger from a workbook or a zip of CSVs. All tables are checked first; a ledger with any problem replaces nothing.", files: ["auditiq/ledger_import.py"] },
  { id: "producer", x: 288, y: 180, w: 268, h: 76, title: "Stream producer", kind: "code", lines: ["python -m auditiq stream publish", "idempotent · acks=all · lz4"],
    detail: "Publishes a ledger, a mailbox or a policy to the topics. Idempotent producer, all replicas acknowledge, lz4 compression; invoices are keyed by vendor so one vendor's history stays in order.", files: ["auditiq/stream.py"] },
  { id: "t-vendor", x: 300, y: 312, w: 244, h: 44, title: "auditiq.vendor", kind: "queue", detail: "Vendor master records." },
  { id: "t-invoice", x: 300, y: 364, w: 244, h: 44, title: "auditiq.invoice", kind: "queue", detail: "Invoices with their PO, GRN and approvals, keyed by vendor: the topic the workers scale on." },
  { id: "t-email", x: 300, y: 416, w: 244, h: 44, title: "auditiq.email", kind: "queue", detail: "Vendor e-mails, linked to invoices when they arrive." },
  { id: "t-compliance", x: 300, y: 468, w: 244, h: 44, title: "auditiq.compliance", kind: "queue", detail: "Policy versions: a new version is stored and can be applied." },
  { id: "workers", x: 288, y: 550, w: 268, h: 136, title: "Stream workers", kind: "code",
    lines: ["consumer group · stateless", "offsets stored in the same DB transaction", "fencing: a worker that lost its partitions", "cannot write them twice", "SQLite BEGIN IMMEDIATE · PG advisory lock"],
    detail: "Consume the topics, store each batch and its offsets in one database transaction (exactly once), audit a same-day group when it is complete, and link e-mails to invoices under an advisory lock.", files: ["auditiq/stream.py", "auditiq/emails.py"] },

  // Engine
  { id: "extract", x: 608, y: 84, w: 290, h: 92, title: "Evidence extraction", kind: "code", stage: "extraction", lines: ["extraction.py · history.py", "PO, GRN, approvals, vendor history", "same-day groups · linked e-mails"],
    detail: "Builds the evidence of one invoice: its purchase order, goods receipt, approvals and the vendor's earlier invoices (history limited to invoices dated before it).", files: ["auditiq/extraction.py", "auditiq/history.py"] },
  { id: "controls", x: 926, y: 84, w: 290, h: 140, title: "Deterministic controls", kind: "code", stage: "controls", lines: ["controls.py · 12 rules, thresholds from the registry"],
    chips: RULE_IDS.map((r) => ({ label: r })),
    detail: "Twelve rules executed as code with the thresholds of the active policy: three-way match, duplicates, GSTIN, splitting, weekend dates, round amounts, blocked vendors and approval limits. Each finding carries its evidence and the clause it breaks.", files: ["auditiq/controls.py", "auditiq/policy.py"] },
  { id: "math", x: 620, y: 274, w: 186, h: 82, title: "Math & Approvals", kind: "llm", stage: "math_approvals", lines: ["sections 2.1 and 5", "judges 2.1.4 · 2.1.5"],
    detail: "Specialist agent for matching and approvals. One structured model call; a finding that cites a clause outside its remit is discarded by code.", files: ["auditiq/agents.py", "auditiq/prompts.py"] },
  { id: "tax", x: 818, y: 274, w: 186, h: 82, title: "Tax & Identity", kind: "llm", stage: "tax_identity", lines: ["sections 2.2 and 3", "judges 2.2.2"],
    detail: "Specialist agent for duplicates and tax identity; judges near duplicates (2.2.2).", files: ["auditiq/agents.py"] },
  { id: "vendorint", x: 1016, y: 274, w: 188, h: 82, title: "Vendor Intelligence", kind: "llm", stage: "vendor_intelligence", lines: ["section 4", "judges 4.1.2"],
    detail: "Specialist agent for vendor behaviour; judges structuring across days (4.1.2).", files: ["auditiq/agents.py"] },
  { id: "single", x: 608, y: 392, w: 190, h: 80, title: "Single-prompt auditor", kind: "llm", stage: "single_auditor", lines: ["configuration C2", "the whole policy, one prompt"],
    detail: "The baseline of configuration C2: one model call with the whole policy and no deterministic controls.", files: ["auditiq/agents.py"] },
  { id: "challenger", x: 818, y: 392, w: 186, h: 80, title: "Challenger", kind: "llm", stage: "challenger", lines: ["drops findings without evidence", "C4 · C5"],
    detail: "Reviews the agents' findings and removes those the evidence does not support, with its reason (kept in the audit pack).", files: ["auditiq/graph.py", "auditiq/prompts.py"] },
  { id: "confidence", x: 1024, y: 392, w: 192, h: 80, title: "Confidence", kind: "llm", stage: "confidence", lines: ["c = (g + p + a) / 3", "m = 3 re-runs at T 0.7 · C5"],
    detail: "Each finding gets g (grounded in evidence), p (policy clause valid) and a (agreement over m = 3 re-runs at temperature 0.7); its confidence is their mean.", files: ["auditiq/scoring.py", "auditiq/graph.py"] },
  { id: "score", x: 608, y: 496, w: 290, h: 92, title: "Risk score", kind: "code", stage: "risk_score", lines: ["scoring.py · weights 30 / 20 / 10 / 5", "R0 = Σ w   ·   Rc = Σ w · c", "floors: critical 70 · high 50 (c ≥ 2/3)"],
    detail: "R0 counts every finding fully; Rc weights each by its confidence. A critical finding lifts a score to at least 70 and a high one to 50, in Rc only when its confidence is at least 2/3.", files: ["auditiq/scoring.py"] },
  { id: "route", x: 926, y: 496, w: 290, h: 92, title: "Route", kind: "code", stage: "risk_score", lines: ["Rc ≥ τ = 50  →  escalate", "R0 ≥ τ  →  sampled review", "otherwise approve"],
    detail: "Escalated invoices wait for a reviewer; sampled ones are reviewed at the sampling rate; the rest are approved automatically.", files: ["auditiq/scoring.py", "auditiq/graph.py"] },
  { id: "review", x: 608, y: 612, w: 290, h: 76, title: "Human review", kind: "person", stage: "human_review", lines: ["approve · reject · override", "an override needs a justification"],
    detail: "A reviewer decides each escalated invoice from the Review queue; the decision, the reviewer and the justification join the audit trail.", files: ["auditiq/service.py", "frontend/src/pages/InvoicePage.tsx"] },
  { id: "pack", x: 926, y: 612, w: 290, h: 76, title: "Audit pack & trail", kind: "code", stage: "audit_pack", lines: ["audit_pack.py · corrections.py", "evidence · citations · revisions"],
    detail: "The record of each audit: findings with evidence and the document page of each clause, what the challenger removed, the revision that would resolve each finding, and every step with its cost.", files: ["auditiq/audit_pack.py", "auditiq/corrections.py"] },

  // Serving
  { id: "users", x: 1268, y: 84, w: 340, h: 60, title: "Auditors & reviewers", kind: "external", lines: ["browser · viewer, reviewer or admin"], detail: "People using the web application; every endpoint needs a role when tokens or users are configured." },
  { id: "web", x: 1268, y: 160, w: 340, h: 128, title: "Web application", kind: "serve", lines: ["React 18 · TypeScript · Vite · React Three Fiber"],
    chips: PAGES.map((p) => ({ label: p })), detail: "This application: nine pages, 3D views in React Three Fiber, served by the API from frontend/dist.", files: ["frontend/src/"] },
  { id: "api", x: 1268, y: 304, w: 340, h: 112, title: "REST API", kind: "serve", lines: ["api.py · FastAPI · 27 endpoints", "bearer tokens · viewer / reviewer / admin", "jobs: 202 then /api/jobs/{id} · CSP headers"],
    detail: "Every request opens its own connection; long work (audits, ledger loads, model calls) runs as a background job with progress.", files: ["auditiq/api.py", "docs/API.md"] },
  { id: "ask", x: 1268, y: 432, w: 340, h: 92, title: "Ask AI", kind: "serve", lines: ["copilot.py · policy_graph.py · citations", "policy facts from the knowledge graph", "invoice and data questions"],
    detail: "Answers questions about the policy from the facts of the policy knowledge graph (built by code from the registry, the documents and the code that checks each rule) and from retrieved passages, about an invoice from its audit pack, and about the data with one guarded SELECT written by the model.", files: ["auditiq/copilot.py", "auditiq/policy_graph.py", "docs/POLICY_GRAPH.md"] },
  { id: "search", x: 1268, y: 540, w: 164, h: 72, title: "Policy search", kind: "code", lines: ["TF-IDF · dense · RRF", "question rewriting"],
    detail: "Lexical, dense and hybrid (reciprocal rank fusion) ranking of policy passages; the model can restate a question in the policy's terms first.", files: ["auditiq/retrieval.py"] },
  { id: "guard", x: 1444, y: 540, w: 164, h: 72, title: "SQL guard", kind: "code", lines: ["one SELECT · allow-list", "read-only role"],
    detail: "A data question becomes one SELECT over allowed tables, refused if it escapes; it runs in a read-only transaction (PostgreSQL role auditiq_reader, SQLite authorizer).", files: ["auditiq/copilot.py"] },
  { id: "cli", x: 1268, y: 626, w: 164, h: 62, title: "Command line", kind: "serve", lines: ["python -m auditiq"], detail: "setup, run, serve, stream, policy, ledger and user commands.", files: ["auditiq/cli.py"] },
  { id: "dash", x: 1444, y: 626, w: 164, h: 62, title: "Streamlit dashboard", kind: "serve", lines: ["app/dashboard.py"], detail: "The earlier dashboard, kept for quick inspection.", files: ["app/dashboard.py"] },

  // Policy
  { id: "sop", x: 32, y: 764, w: 160, h: 84, title: "Policy documents", kind: "external", lines: ["audit SOP as PDF", "v2.5 · v2.6 · variants"], detail: "The company's audit procedure as PDF, one per version." },
  { id: "ingest", x: 210, y: 764, w: 166, h: 84, title: "PDF ingestion", kind: "code", lines: ["policy_ingest.py · PyMuPDF", "passages with their pages"],
    detail: "Reads each rule and paragraph with its page, and checks every rule's text against the registry of the same version.", files: ["auditiq/policy_ingest.py"] },
  { id: "compiler", x: 394, y: 764, w: 162, h: 84, title: "Pattern compiler", kind: "code", lines: ["policy_extract.py", "values from the wording"],
    detail: "Reads thresholds from the wording of the rules with patterns, no model.", files: ["auditiq/policy_extract.py"] },
  { id: "reader", x: 32, y: 866, w: 160, h: 84, title: "Model reader", kind: "llm", lines: ["policy_llm.py", "quotes verified in the text"],
    detail: "For free wording: the model proposes values with quotes; code checks each quote is in the document; a person confirms.", files: ["auditiq/policy_llm.py"] },
  { id: "confirm", x: 210, y: 866, w: 166, h: 84, title: "Confirmation", kind: "person", lines: ["a person confirms", "each proposed value"], detail: "No value read by a model is applied without a person confirming it." },
  { id: "registry", x: 394, y: 866, w: 162, h: 84, title: "Clause registry", kind: "code", lines: ["policy_v2.5.json", "16 clauses · versioned"],
    detail: "Severity, kind (control or judgement) and parameters of every clause; the controls and agents read nothing else.", files: ["policy/policy_v2.5.json", "auditiq/policy.py"] },
  { id: "rules", x: 32, y: 968, w: 524, h: 176, title: "Clauses of the active policy", kind: "code", detail: "Every clause of the active version, coloured by severity; J marks a judgement clause, read by the agents." },

  // Store
  { id: "audit", x: 608, y: 764, w: 408, h: 92, title: "Audit", kind: "store", lines: ["audit_runs · audit_results · audit_flags", "audit_trail · review_decisions · latest_results"], detail: "Every run, result, finding and step; latest_results points at the newest result of each invoice." },
  { id: "views", x: 1028, y: 764, w: 188, h: 92, title: "Views", kind: "store", lines: ["v_latest_results", "v_review_queue"], detail: "What the pages read: the latest result of each invoice and the invoices waiting for review." },
  { id: "policyT", x: 608, y: 872, w: 198, h: 92, title: "Policy", kind: "store", lines: ["company_policies · policy_clauses", "policy_parameters · documents", "policy_chunks + embeddings"], detail: "Versions, clauses, parameters, documents and their passages (with embeddings when a model is configured)." },
  { id: "ledger", x: 818, y: 872, w: 198, h: 92, title: "Ledger", kind: "store", lines: ["vendor_master · purchase_orders", "goods_receipts · invoices", "approval_logs"], detail: "The procure-to-pay records." },
  { id: "mail", x: 1028, y: 872, w: 188, h: 92, title: "Correspondence", kind: "store", lines: ["emails · email_mentions"], detail: "E-mails and the invoices they mention." },
  { id: "streamT", x: 608, y: 980, w: 198, h: 80, title: "Stream state", kind: "store", lines: ["stream_offsets · stream_log"], detail: "Offsets per partition, written with the data they cover." },
  { id: "labels", x: 818, y: 980, w: 198, h: 80, title: "Answer key", kind: "store", lines: ["benchmark_labels", "evaluation only"], detail: "Benchmark labels of a generated ledger, used by the evaluation and the coverage figures." },
  { id: "access", x: 1028, y: 980, w: 188, h: 80, title: "Access", kind: "store", lines: ["api_users · roles"], detail: "Users with hashed tokens and their roles." },
  { id: "engines", x: 608, y: 1076, w: 608, h: 68, title: "Engines", kind: "store", lines: ["SQLite: WAL · BEGIN IMMEDIATE · authorizer for Ask AI", "PostgreSQL 17: advisory locks · read-only role auditiq_reader"], detail: "The same schema on both; tests run on both." },

  // Models
  { id: "chat", x: 1268, y: 762, w: 166, h: 140, title: "Chat model", kind: "model", lines: ["qwen2.5:7b-ctx12k", "temperature 0", "re-runs at 0.7", "response cache"], detail: "Local Ollama model behind an OpenAI-compatible endpoint; replies are cached by prompt." },
  { id: "embed", x: 1444, y: 762, w: 164, h: 140, title: "Embeddings", kind: "model", lines: ["nomic-embed-text", "policy passages", "dense search"], detail: "Embeds policy passages and questions for dense and hybrid search." },

  // Delivery
  { id: "image", x: 1268, y: 982, w: 108, h: 160, title: "Container", kind: "ops", lines: ["Dockerfile", "API + web app", "non-root user"], detail: "One image with the API and the built web application.", files: ["Dockerfile"] },
  { id: "compose", x: 1386, y: 982, w: 108, h: 160, title: "Compose", kind: "ops", lines: ["api", "workers", "kafka", "postgres"], detail: "The whole platform on one machine.", files: ["deploy/docker-compose.yml"] },
  { id: "ci", x: 1504, y: 982, w: 104, h: 160, title: "CI", kind: "ops", lines: ["GitHub Actions", "test · frontend", "e2e · compose", "container"], detail: "Python tests on SQLite and PostgreSQL with a Kafka broker, frontend lint/type/test/build, browser tests, compose and container builds.", files: [".github/workflows/ci.yml"] },
];

export const EDGES: ArchEdge[] = [
  { from: "erp", to: "importer", label: "workbook" },
  { from: "erp", to: "producer", label: "records" },
  { from: "mailbox", to: "producer", label: "e-mails" },
  { from: "bench", to: "erp", fromSide: "t", toSide: "b", label: "writes" },
  { from: "producer", to: "kafka", fromSide: "b", toSide: "t", label: "produce" },
  { from: "kafka", to: "workers", fromSide: "b", toSide: "t", label: "consume" },
  { from: "importer", to: "store", fromSide: "r", toSide: "l", fromAt: 0.25, via: [[576, 144], [576, 742]], toAt: -0.45, label: "replace ledger", labelAt: [576, 690] },
  { from: "workers", to: "store", fromSide: "b", toSide: "t", via: [[422, 708], [656, 708]], toAt: -0.4, label: "batch + offsets, one transaction", labelAt: [520, 708] },
  { from: "workers", to: "extract", fromSide: "r", toSide: "l", via: [[581, 618], [581, 148]], toAt: 0.2, kind: "control", label: "audit a complete group", labelAt: [581, 520] },
  { from: "store", to: "extract", fromSide: "l", toSide: "l", fromAt: -0.4, via: [[586, 764], [586, 107]], toAt: -0.25, label: "ledger · history", labelAt: [586, 300] },
  { from: "extract", to: "controls", kind: "control", label: "evidence" },
  { from: "controls", to: "agents", fromSide: "b", toSide: "t", fromAt: 0.25, toAt: 0.27, kind: "control" },
  { from: "extract", to: "single", fromSide: "l", toSide: "l", fromAt: 0.35, via: [[600, 162], [600, 432]], kind: "dashed", label: "C2", labelAt: [600, 384] },
  { from: "agents", to: "challenger", fromSide: "b", toSide: "t", kind: "control", label: "findings" },
  { from: "single", to: "challenger", kind: "control" },
  { from: "challenger", to: "confidence", kind: "control", label: "kept" },
  { from: "confidence", to: "score", fromSide: "b", toSide: "t", via: [[1120, 484], [753, 484]], kind: "control" },
  { from: "controls", to: "score", fromSide: "r", toSide: "t", fromAt: 0.1, via: [[1225, 168], [1225, 484], [700, 484]], toAt: -0.18, kind: "dashed", label: "C1: controls only", labelAt: [1225, 230] },
  { from: "score", to: "route", kind: "control", label: "R0 · Rc" },
  { from: "route", to: "review", fromSide: "b", toSide: "t", fromAt: -0.25, via: [[998, 600], [753, 600]], kind: "control", label: "escalate · sample", labelAt: [860, 600] },
  { from: "route", to: "pack", fromSide: "b", toSide: "t", fromAt: 0.3, kind: "control", label: "approve" },
  { from: "review", to: "pack", kind: "control", label: "decision" },
  { from: "review", to: "audit", fromSide: "b", toSide: "t", fromAt: -0.2, toAt: -0.3, label: "review_decisions" },
  { from: "pack", to: "audit", fromSide: "b", toSide: "t", fromAt: -0.2, via: [[1013, 706], [967, 706]], toAt: 0.38, label: "results · flags · trail", labelAt: [1090, 706] },
  { from: "agents", to: "chat", fromSide: "r", toSide: "l", fromAt: 0.1, via: [[1246, 315], [1246, 800]], toAt: -0.23, kind: "model", label: "structured calls", labelAt: [1246, 560] },
  { from: "confidence", to: "chat", fromSide: "r", toSide: "l", via: [[1246, 432], [1246, 800]], toAt: -0.23, kind: "model" },
  { from: "users", to: "web", fromSide: "b", toSide: "t" },
  { from: "web", to: "api", fromSide: "b", toSide: "t", label: "JSON over HTTPS" },
  { from: "api", to: "ask", fromSide: "b", toSide: "t" },
  { from: "ask", to: "search", fromSide: "b", toSide: "t", fromAt: -0.26 },
  { from: "ask", to: "guard", fromSide: "b", toSide: "t", fromAt: 0.26 },
  { from: "api", to: "store", fromSide: "l", toSide: "r", fromAt: 0.2, via: [[1240, 382], [1240, 918]], toAt: -0.05, label: "SQL", labelAt: [1240, 700] },
  { from: "cli", to: "store", fromSide: "l", toSide: "r", via: [[1236, 657], [1236, 997]], toAt: 0.13 },
  { from: "ask", to: "embed", fromSide: "r", toSide: "r", via: [[1632, 478], [1632, 832]], kind: "model", label: "embed · chat", labelAt: [1632, 650] },
  { from: "sop", to: "ingest" },
  { from: "ingest", to: "compiler" },
  { from: "ingest", to: "reader", fromSide: "b", toSide: "t", via: [[293, 857], [112, 857]], kind: "model" },
  { from: "reader", to: "confirm", label: "proposals" },
  { from: "confirm", to: "registry" },
  { from: "compiler", to: "registry", fromSide: "b", toSide: "t", label: "values" },
  { from: "registry", to: "policyT", fromSide: "r", toSide: "l", fromAt: 0.2, label: "stored" },
  { from: "registry", to: "controls", fromSide: "r", toSide: "b", fromAt: -0.15, via: [[590, 895], [590, 230], [950, 230]], toAt: -0.42, kind: "control", label: "thresholds", labelAt: [760, 230] },
  { from: "registry", to: "agents", fromSide: "r", toSide: "l", fromAt: -0.15, via: [[590, 895], [590, 330]], toAt: 0.2, kind: "control" },
];

export function rect(id: string): { x: number; y: number; w: number; h: number } | undefined {
  return NODES.find((n) => n.id === id) ?? CLUSTERS.find((c) => c.id === id);
}

export function anchor(id: string, side: Side, at = 0): Point {
  const r = rect(id)!;
  switch (side) {
    case "l":
      return [r.x, r.y + r.h / 2 + at * r.h];
    case "r":
      return [r.x + r.w, r.y + r.h / 2 + at * r.h];
    case "t":
      return [r.x + r.w / 2 + at * r.w, r.y];
    default:
      return [r.x + r.w / 2 + at * r.w, r.y + r.h];
  }
}

/** Rounded orthogonal path through the points: straight runs joined by quarter curves, React Flow "smoothstep" style. */
export function smoothPath(points: Point[], radius = 9): string {
  if (points.length < 2) return "";
  let d = `M${points[0][0]},${points[0][1]}`;
  for (let i = 1; i < points.length - 1; i++) {
    const [px, py] = points[i - 1], [x, y] = points[i], [nx, ny] = points[i + 1];
    const r = Math.min(radius, Math.hypot(x - px, y - py) / 2, Math.hypot(nx - x, ny - y) / 2);
    const a: Point = [x - Math.sign(x - px) * r, y - Math.sign(y - py) * r];
    const b: Point = [x + Math.sign(nx - x) * r, y + Math.sign(ny - y) * r];
    d += ` L${a[0]},${a[1]} Q${x},${y} ${b[0]},${b[1]}`;
  }
  const last = points[points.length - 1];
  return `${d} L${last[0]},${last[1]}`;
}

export function edgePoints(e: ArchEdge): Point[] {
  const a = rect(e.from)!, b = rect(e.to)!;
  const right = b.x >= a.x + a.w, below = b.y >= a.y + a.h;
  const fromSide = e.fromSide ?? (right ? "r" : below ? "b" : "l");
  const toSide = e.toSide ?? (right ? "l" : below ? "t" : "r");
  const s = anchor(e.from, fromSide, e.fromAt ?? 0);
  const t = anchor(e.to, toSide, e.toAt ?? 0);
  if (e.via) return [s, ...e.via, t];
  if ((fromSide === "r" || fromSide === "l") && (toSide === "l" || toSide === "r")) {
    if (Math.abs(s[1] - t[1]) < 1) return [s, t];
    const mx = (s[0] + t[0]) / 2;
    return [s, [mx, s[1]], [mx, t[1]], t];
  }
  if (Math.abs(s[0] - t[0]) < 1) return [s, t];
  const my = (s[1] + t[1]) / 2;
  return [s, [s[0], my], [t[0], my], t];
}

export function midpoint(points: Point[]): Point {
  const lengths = points.slice(1).map((p, i) => Math.hypot(p[0] - points[i][0], p[1] - points[i][1]));
  let half = lengths.reduce((t, l) => t + l, 0) / 2;
  for (let i = 0; i < lengths.length; i++) {
    if (half <= lengths[i]) {
      const f = lengths[i] ? half / lengths[i] : 0;
      return [points[i][0] + (points[i + 1][0] - points[i][0]) * f, points[i][1] + (points[i + 1][1] - points[i][1]) * f];
    }
    half -= lengths[i];
  }
  return points[0];
}
