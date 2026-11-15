// The architecture of the platform as data: every component, the subsystem it belongs to, where it lives in the code,
// and what moves between components. Drawn with React Flow by components/ArchitectureDiagram.tsx.
//
// The edges follow the code: an arrow A -> B means A sends data to B, starts B, or calls B (the imports between the
// modules of auditiq/ were read to draw them). Reads from the store point from the table to the reader.

export type NodeKind = "external" | "code" | "llm" | "person" | "queue" | "store" | "serve" | "model" | "ops" | "graph";
export type EdgeKind = "data" | "control" | "model" | "config" | "variant";
export type Side = "l" | "r" | "t" | "b";

export interface ArchGroup {
  id: string;
  title: string;
  note: string;
  tone: string;
  /** Top-left corner on the canvas and the grid of its components. */
  x: number;
  y: number;
  cols: number;
  rows: number;
}

export interface ArchNode {
  id: string;
  group: string;
  /** Cell of the group's grid. */
  col: number;
  row: number;
  title: string;
  /** One short line under the title: the module or the gist. */
  sub: string;
  kind: NodeKind;
  detail: string;
  files?: string[];
  /** The pipeline stage the node stands for, to dim it under a configuration that does not run it. */
  stage?: string;
}

export interface ArchEdge {
  from: string;
  to: string;
  label: string;
  kind?: EdgeKind;
}

export const KIND_STYLE: Record<NodeKind, { color: string; label: string }> = {
  external: { color: "#64748b", label: "Outside the platform" },
  code: { color: "#0d9488", label: "Deterministic code" },
  llm: { color: "#7c3aed", label: "Language-model stage" },
  person: { color: "#d97706", label: "A person decides" },
  queue: { color: "#ea580c", label: "Kafka" },
  store: { color: "#2563eb", label: "Tables in the store" },
  graph: { color: "#4f46e5", label: "Analytics & knowledge" },
  serve: { color: "#16a34a", label: "Interface" },
  model: { color: "#c026d3", label: "Model server" },
  ops: { color: "#334155", label: "Delivery & operations" },
};

export const EDGE_STYLE: Record<EdgeKind, { color: string; label: string; dash?: string }> = {
  data: { color: "#94a3b8", label: "data written or read" },
  control: { color: "#0d9488", label: "control: starts or calls" },
  model: { color: "#c026d3", label: "call to a model", dash: "2 4" },
  config: { color: "#4f46e5", label: "policy configures", dash: "6 4" },
  variant: { color: "#94a3b8", label: "only in one configuration", dash: "3 5" },
};

/** Direction colours of a traced component: what flows in, what flows out. */
export const TRACE = { in: "#2563eb", out: "#d97706" };

// Geometry of the grid: every component has the same footprint, so the diagram reads as a calm grid.
export const NODE_W = 212;
export const NODE_H = 74;
export const GAP_X = 22;
export const GAP_Y = 18;
export const PAD_X = 16;
export const PAD_TOP = 54;
export const PAD_BOTTOM = 16;

export const GROUPS: ArchGroup[] = [
  { id: "sources", title: "Sources", note: "outside the platform", tone: "#64748b", x: 0, y: 0, cols: 1, rows: 5 },
  { id: "ingestion", title: "Ingestion", note: "batch import · Kafka 4.3 streaming", tone: "#ea580c", x: 290, y: 0, cols: 2, rows: 5 },
  { id: "engine", title: "Audit engine", note: "LangGraph StateGraph · one run per invoice · C1 to C5", tone: "#0d9488", x: 820, y: 0, cols: 3, rows: 5 },
  { id: "store", title: "Store", note: "one schema on SQLite or PostgreSQL 17", tone: "#2563eb", x: 1584, y: 0, cols: 2, rows: 5 },
  { id: "interfaces", title: "Interfaces", note: "FastAPI · React · CLI", tone: "#16a34a", x: 2114, y: 0, cols: 1, rows: 5 },
  { id: "policy", title: "Policy as data", note: "the only place thresholds live", tone: "#4f46e5", x: 290, y: 560, cols: 2, rows: 3 },
  { id: "models", title: "Models", note: "local Ollama · OpenAI-compatible", tone: "#c026d3", x: 820, y: 560, cols: 3, rows: 1 },
  { id: "delivery", title: "Delivery & operations", note: "run it anywhere, reproduce every number", tone: "#334155", x: 820, y: 760, cols: 3, rows: 2 },
  { id: "intelligence", title: "Intelligence", note: "forensic analytics · knowledge graphs · Ask AI", tone: "#4f46e5", x: 1584, y: 560, cols: 2, rows: 4 },
];

export const NODES: ArchNode[] = [
  // Sources
  { id: "erp", group: "sources", col: 0, row: 0, title: "ERP ledger", sub: "workbook · CSV zip · dataset folder", kind: "external",
    detail: "The procure-to-pay ledger: vendor master, purchase orders, goods receipts, invoices and approval logs. It arrives as an Excel workbook, a zip of CSV files or a dataset folder, or message by message through Kafka." },
  { id: "mailbox", group: "sources", col: 0, row: 1, title: "Vendor mailbox", sub: "correspondence as .mbox (MIME)", kind: "external",
    detail: "Vendor e-mails. Each message is parsed for the invoice numbers it mentions and linked to that invoice, so a reviewer sees the correspondence beside it." },
  { id: "sop", group: "sources", col: 0, row: 2, title: "Policy documents", sub: "audit SOP as PDF · one per version", kind: "external",
    detail: "The company's audit procedure as PDF files (v2.5, v2.6, variants). The thresholds the controls apply are read from their wording." },
  { id: "bench", group: "sources", col: 0, row: 3, title: "AuditIQ-Bench", sub: "auditiq_bench · synthetic ledgers", kind: "external",
    detail: "Generates the synthetic ledgers (5,000 to 500,000 invoices) with injected anomalies of every rule, look-alike hard negatives, compound frauds, approver rings, vendor correspondence and an answer key per invoice. Byte-identical from its seed.",
    files: ["auditiq_bench/generator.py", "auditiq_bench/correspondence.py", "auditiq_bench/taxonomy.py"] },
  { id: "demo", group: "sources", col: 0, row: 4, title: "Demonstration policies", sub: "policy_demo.py · five organisations", kind: "external",
    detail: "Five organisations' versions of the procurement SOP (Lean Growth, Strict Controls, Tax Compliance First, ...), written as PDFs to show how the audit changes when only the document changes.",
    files: ["auditiq/policy_demo.py", "auditiq/policy_pdf.py"] },

  // Ingestion
  { id: "importer", group: "ingestion", col: 0, row: 0, title: "Ledger import", sub: "ledger_import.py · POST /api/ledger", kind: "code",
    detail: "Loads a ledger in one batch. Every table is checked first; a ledger with any problem replaces nothing.", files: ["auditiq/ledger_import.py"] },
  { id: "launcher", group: "ingestion", col: 0, row: 1, title: "Live launcher", sub: "start.bat → scripts/live.py", kind: "code",
    detail: "The one-file run of the project: starts the Kafka broker, creates an empty store and four topics of its own, starts the workers and the web application, publishes the ledger, the e-mails and the policies, and reports progress until every message is processed.",
    files: ["start.bat", "scripts/live.py"] },
  { id: "producer", group: "ingestion", col: 0, row: 2, title: "Stream producer", sub: "stream publish · idempotent · acks=all", kind: "code",
    detail: "Publishes a ledger, a mailbox or a policy document to the topics. Idempotent producer, every replica acknowledges, lz4 compression; invoices are keyed by vendor so one vendor's history stays in order.",
    files: ["auditiq/stream.py"] },
  { id: "workers", group: "ingestion", col: 0, row: 3, title: "Stream workers", sub: "stateless consumer groups", kind: "code",
    detail: "Consume the topics and store each batch with its offsets in one database transaction (exactly once). A worker that lost its partitions is fenced off; a complete same-day group of invoices is audited as it arrives.",
    files: ["auditiq/stream.py"] },
  { id: "emails", group: "ingestion", col: 0, row: 4, title: "E-mail linker", sub: "emails.py · RFC 5322", kind: "code",
    detail: "Parses a MIME message, looks up the invoice numbers it names and links it to that invoice and vendor. An e-mail that arrives before its invoice waits and is linked when the invoice arrives.",
    files: ["auditiq/emails.py"] },
  { id: "broker", group: "ingestion", col: 1, row: 0, title: "Kafka broker", sub: "KRaft · one node · localhost:9092", kind: "queue",
    detail: "Apache Kafka in KRaft mode, without ZooKeeper. Hosts the four topics, 16 partitions in all; the partitions are the scaling lever." },
  { id: "t-vendor", group: "ingestion", col: 1, row: 1, title: "vendor", sub: "topic · vendor master records", kind: "queue",
    detail: "The vendor feed. Vendors are published first, so an invoice never arrives for an unknown vendor." },
  { id: "t-invoice", group: "ingestion", col: 1, row: 2, title: "invoice", sub: "topic · keyed by vendor", kind: "queue",
    detail: "Invoices with their purchase order, goods receipt and approvals, keyed by vendor: the topic the workers scale on." },
  { id: "t-email", group: "ingestion", col: 1, row: 3, title: "email", sub: "topic · raw MIME messages", kind: "queue",
    detail: "Vendor e-mails as they arrive, linked to invoices by the e-mail linker." },
  { id: "t-compliance", group: "ingestion", col: 1, row: 4, title: "compliance", sub: "topic · policy PDFs", kind: "queue",
    detail: "Policy documents: a new version is ingested, stored and can be applied." },

  // Audit engine
  { id: "extract", group: "engine", col: 0, row: 0, title: "Evidence extraction", sub: "extraction.py", kind: "code", stage: "extraction",
    detail: "Joins everything linked to one invoice into a transaction: its purchase order, goods receipt, approvals, linked e-mails, same-day group and the vendor's earlier invoices (only those dated before it).",
    files: ["auditiq/extraction.py"] },
  { id: "history", group: "engine", col: 1, row: 0, title: "Vendor history index", sub: "history.py · built once per vendor", kind: "code", stage: "extraction",
    detail: "An index of each vendor's invoices that rules 2.2.1 (number used before) and 4.1.1 (too many on one day) look into instead of reading the whole history; it keeps the time per invoice flat as the ledger grows.",
    files: ["auditiq/history.py"] },
  { id: "controls", group: "engine", col: 2, row: 0, title: "Deterministic controls", sub: "controls.py · 12 rules", kind: "code", stage: "controls",
    detail: "Twelve rules executed as code with the thresholds of the policy in force on the invoice's date: three-way match, duplicates, GSTIN, splitting, weekend dates, round amounts, blocked vendors and approval limits. Each finding carries its evidence and the clause it breaks.",
    files: ["auditiq/controls.py", "auditiq/policy.py"] },
  { id: "math", group: "engine", col: 0, row: 1, title: "Math & Approvals", sub: "agent · sections 2.1 and 5", kind: "llm", stage: "math_approvals",
    detail: "Specialist agent for matching and approvals; judges 2.1.4 and 2.1.5. One structured model call; a finding that cites a clause outside its remit is discarded by code.",
    files: ["auditiq/agents.py", "auditiq/prompts.py"] },
  { id: "tax", group: "engine", col: 1, row: 1, title: "Tax & Identity", sub: "agent · sections 2.2 and 3", kind: "llm", stage: "tax_identity",
    detail: "Specialist agent for duplicates and tax identity; judges near duplicates (2.2.2).", files: ["auditiq/agents.py"] },
  { id: "vendorint", group: "engine", col: 2, row: 1, title: "Vendor Intelligence", sub: "agent · section 4", kind: "llm", stage: "vendor_intelligence",
    detail: "Specialist agent for vendor behaviour; judges structuring across days (4.1.2).", files: ["auditiq/agents.py"] },
  { id: "single", group: "engine", col: 0, row: 2, title: "Single-prompt auditor", sub: "configuration C2 · baseline", kind: "llm", stage: "single_auditor",
    detail: "The baseline of configuration C2: one model call over the whole policy, with no deterministic controls and no challenger.", files: ["auditiq/agents.py"] },
  { id: "challenger", group: "engine", col: 1, row: 2, title: "Challenger", sub: "drops unsupported findings · C4, C5", kind: "llm", stage: "challenger",
    detail: "Reviews the agents' findings and removes those the evidence does not support, with its reason, which is kept in the audit pack.", files: ["auditiq/graph.py", "auditiq/prompts.py"] },
  { id: "confidence", group: "engine", col: 2, row: 2, title: "Confidence", sub: "c = (g + p + a) / 3 · C5", kind: "llm", stage: "confidence",
    detail: "Each finding gets g (grounded in evidence), p (policy clause valid) and a (agreement over three re-runs at temperature 0.7); its confidence is their mean.", files: ["auditiq/scoring.py", "auditiq/graph.py"] },
  { id: "score", group: "engine", col: 0, row: 3, title: "Risk score", sub: "R0 = Σw · Rc = Σw·c", kind: "code", stage: "risk_score",
    detail: "Weights 30 / 20 / 10 / 5 by severity. R0 counts every finding fully; Rc weights each by its confidence. A critical finding lifts the score to at least 70 and a high one to 50.", files: ["auditiq/scoring.py"] },
  { id: "route", group: "engine", col: 1, row: 3, title: "Route", sub: "Rc ≥ 50 escalate · else approve", kind: "code", stage: "risk_score",
    detail: "Escalated invoices wait for a reviewer; sampled ones are reviewed at the sampling rate; the rest are approved automatically.", files: ["auditiq/scoring.py", "auditiq/graph.py"] },
  { id: "review", group: "engine", col: 2, row: 3, title: "Human review", sub: "approve · reject · override", kind: "person", stage: "human_review",
    detail: "A reviewer decides each escalated invoice from the Review queue. An override needs a justification; the decision and the reviewer join the audit trail.", files: ["auditiq/service.py", "frontend/src/pages/InvoicePage.tsx"] },
  { id: "service", group: "engine", col: 0, row: 4, title: "Batch audit service", sub: "service.py · one run, one configuration", kind: "code",
    detail: "Audits a list of invoices with one configuration and one policy version, stores every result with its flags and trail, and queues those that need a person.", files: ["auditiq/service.py", "auditiq/graph.py"] },
  { id: "corrections", group: "engine", col: 1, row: 4, title: "Revisions", sub: "corrections.py · computed, no model", kind: "code",
    detail: "What each control finding requires, computed from its evidence and the policy: the amount the invoice may bill, the GSTIN it must carry, the role that must approve it.", files: ["auditiq/corrections.py"] },
  { id: "pack", group: "engine", col: 2, row: 4, title: "Audit pack & trail", sub: "audit_pack.py", kind: "code", stage: "audit_pack",
    detail: "The record of one audit: findings with evidence and the document page of each clause, what the challenger removed, the revisions, and every step with its cost.", files: ["auditiq/audit_pack.py"] },

  // Store
  { id: "ledger", group: "store", col: 0, row: 0, title: "Ledger", sub: "vendors · POs · GRNs · invoices · approvals", kind: "store",
    detail: "The procure-to-pay records: vendor_master, purchase_orders, goods_receipts, invoices and approval_logs." },
  { id: "mail", group: "store", col: 0, row: 1, title: "Correspondence", sub: "emails · email_mentions", kind: "store",
    detail: "Vendor e-mails and the invoices they mention." },
  { id: "policyT", group: "store", col: 0, row: 2, title: "Policy store", sub: "versions · clauses · chunks", kind: "store",
    detail: "company_policies, policy_clauses, policy_parameters, policy_documents and policy_chunks (with embeddings when a model is configured)." },
  { id: "streamT", group: "store", col: 0, row: 3, title: "Stream state", sub: "stream_offsets · stream_log", kind: "store",
    detail: "Offsets per topic partition, written in the same transaction as the data they cover: the basis of exactly-once processing." },
  { id: "access", group: "store", col: 0, row: 4, title: "Access", sub: "api_users · roles", kind: "store",
    detail: "Users with hashed tokens and their roles: viewer, reviewer or admin." },
  { id: "audit", group: "store", col: 1, row: 0, title: "Audit results", sub: "runs · results · flags · trail", kind: "store",
    detail: "audit_runs, audit_results, audit_flags, audit_trail and review_decisions: every run, result, finding, step and decision." },
  { id: "views", group: "store", col: 1, row: 1, title: "Views", sub: "v_latest_results · v_review_queue", kind: "store",
    detail: "What the pages read: the latest result of each invoice, and the invoices waiting for review." },
  { id: "labels", group: "store", col: 1, row: 2, title: "Answer key", sub: "benchmark_labels · evaluation only", kind: "store",
    detail: "The ground truth of a generated ledger. Loaded after the ledger is published; the audit never reads it, the coverage figures do." },
  { id: "engines", group: "store", col: 1, row: 3, title: "Database engines", sub: "SQLite WAL · PostgreSQL 17", kind: "store",
    detail: "The same schema on both. SQLite: write-ahead log, BEGIN IMMEDIATE, an authorizer for Ask AI. PostgreSQL: advisory locks and the read-only role auditiq_reader.",
    files: ["auditiq/db.py", "deploy/postgres/"] },

  // Policy as data
  { id: "pdfIngest", group: "policy", col: 0, row: 0, title: "PDF ingestion", sub: "policy_ingest.py · PyMuPDF", kind: "code",
    detail: "Reads each rule and paragraph with its page, and checks every rule's text against the registry of the same version.", files: ["auditiq/policy_ingest.py"] },
  { id: "compiler", group: "policy", col: 0, row: 1, title: "Pattern compiler", sub: "policy_extract.py · no model", kind: "code",
    detail: "Reads the thresholds from the wording of the rules with patterns, without a model.", files: ["auditiq/policy_extract.py"] },
  { id: "reader", group: "policy", col: 0, row: 2, title: "Model reader", sub: "policy_llm.py · quotes verified", kind: "llm",
    detail: "For free wording: the model proposes values with quotes, code checks that each quote is in the document, and a person confirms.", files: ["auditiq/policy_llm.py"] },
  { id: "confirm", group: "policy", col: 1, row: 2, title: "Confirmation", sub: "a person confirms each value", kind: "person",
    detail: "No value read by a model is applied without a person confirming it." },
  { id: "registry", group: "policy", col: 1, row: 0, title: "Clause registry", sub: "policy_v2.5.json · versioned", kind: "code",
    detail: "Severity, kind (control or judgement) and parameters of every clause. Each invoice is judged by the version in force on its date; the controls and agents read nothing else.",
    files: ["policy/policy_v2.5.json", "auditiq/policy.py"] },
  { id: "simulation", group: "policy", col: 1, row: 1, title: "Policy simulation", sub: "simulation.py · dry run", kind: "code",
    detail: "What a policy document would do to the ledger before it is adopted: every invoice re-checked by the twelve controls in memory, under the old and the new version, and compared. Nothing is stored.",
    files: ["auditiq/simulation.py"] },

  // Models
  { id: "chat", group: "models", col: 0, row: 0, title: "Chat model", sub: "qwen2.5:7b · temperature 0", kind: "model",
    detail: "A local Ollama model behind an OpenAI-compatible endpoint. Structured calls at temperature 0; re-runs at 0.7 for agreement.", files: ["auditiq/llm.py"] },
  { id: "embed", group: "models", col: 1, row: 0, title: "Embeddings", sub: "nomic-embed-text", kind: "model",
    detail: "Embeds policy passages and questions for dense and hybrid search.", files: ["auditiq/retrieval.py"] },
  { id: "cache", group: "models", col: 2, row: 0, title: "Response cache", sub: ".auditiq/llm_cache.sqlite", kind: "model",
    detail: "Every model reply is stored under a key of the whole request, so a re-run costs nothing and gives the same answer.", files: ["auditiq/llm.py"] },

  // Delivery
  { id: "container", group: "delivery", col: 0, row: 0, title: "Container image", sub: "Dockerfile · non-root", kind: "ops",
    detail: "One image with the API and the built web application, run as an unprivileged user.", files: ["Dockerfile"] },
  { id: "compose", group: "delivery", col: 1, row: 0, title: "Compose", sub: "api · workers · kafka · postgres", kind: "ops",
    detail: "The whole platform on one machine.", files: ["deploy/docker-compose.yml"] },
  { id: "ci", group: "delivery", col: 2, row: 0, title: "CI", sub: "GitHub Actions", kind: "ops",
    detail: "Python tests on SQLite and PostgreSQL with a Kafka broker, the frontend's lint, types, tests and build, browser tests, and the compose and container builds.", files: [".github/workflows/ci.yml"] },
  { id: "kafkaLocal", group: "delivery", col: 0, row: 1, title: "Local Kafka", sub: "scripts/kafka_local.py", kind: "ops",
    detail: "A one-node KRaft broker for development and tests, without Docker or a service.", files: ["scripts/kafka_local.py"] },
  { id: "pgLocal", group: "delivery", col: 1, row: 1, title: "Local PostgreSQL", sub: "scripts/pg_local.py · port 5544", kind: "ops",
    detail: "A PostgreSQL 17 cluster for development and tests, without installing a service. Writes the connection URL to .env.", files: ["scripts/pg_local.py"] },
  { id: "reproduce", group: "delivery", col: 2, row: 1, title: "Reproduce", sub: "scripts/reproduce.py", kind: "ops",
    detail: "Re-runs every result that needs no language model in a temporary folder and compares it with the committed one.", files: ["scripts/reproduce.py", "evaluation/"] },

  // Intelligence
  { id: "analytics", group: "intelligence", col: 0, row: 0, title: "Forensic analytics", sub: "analytics.py · Benford · Gini", kind: "graph",
    detail: "Computed from the store when asked: monthly volume and findings, Benford's first-digit tests, amounts against the approval limits, spend concentration, and coverage against the answer key.",
    files: ["auditiq/analytics.py"] },
  { id: "rings", group: "intelligence", col: 0, row: 1, title: "Collusion rings", sub: "rings.py · binomial test · FDR", kind: "graph",
    detail: "Vendors and approvers tied together by shared PAN or GSTIN, by another vendor's GSTIN, or by approving more flagged invoices than their role's rate (one-sided binomial test, false-discovery-rate controlled).",
    files: ["auditiq/rings.py"] },
  { id: "caseGraph", group: "intelligence", col: 0, row: 2, title: "Audit knowledge graph", sub: "case_graph.py · built by code", kind: "graph",
    detail: "What the audit found as a graph: which vendor billed which invoice, which rule it breaks and why, who approved it, which vendors share an identity and which rings they form. No model writes it.",
    files: ["auditiq/case_graph.py"] },
  { id: "copilot", group: "intelligence", col: 1, row: 0, title: "Ask AI copilot", sub: "copilot.py · answers with citations", kind: "graph",
    detail: "Answers questions about the policy (from graph facts and retrieved passages), about an invoice (from its audit pack) and about the data (one guarded SELECT written by the model).",
    files: ["auditiq/copilot.py"] },
  { id: "retrieval", group: "intelligence", col: 1, row: 1, title: "Policy retrieval", sub: "TF-IDF · dense · RRF hybrid", kind: "graph",
    detail: "Lexical, dense and hybrid (reciprocal rank fusion) ranking of policy passages; the chat model can restate a question in the policy's words first.",
    files: ["auditiq/retrieval.py"] },
  { id: "policyGraph", group: "intelligence", col: 1, row: 2, title: "Policy knowledge graph", sub: "policy_graph.py · Graph RAG", kind: "graph",
    detail: "Version → section → clause → parameter → role, and which control or agent checks each clause, built by code from the registry, the documents and the code itself.",
    files: ["auditiq/policy_graph.py"] },
  { id: "guard", group: "intelligence", col: 1, row: 3, title: "SQL guard", sub: "one SELECT · read-only role", kind: "graph",
    detail: "A data question becomes one SELECT over allowed tables, refused if it escapes, run in a read-only transaction (PostgreSQL role auditiq_reader, SQLite authorizer).",
    files: ["auditiq/copilot.py"] },
  { id: "datadict", group: "intelligence", col: 0, row: 3, title: "Data dictionary", sub: "datadict.py · every column", kind: "graph",
    detail: "What every table and column of the store means; the copilot gives it to the model before it writes a query.", files: ["auditiq/datadict.py"] },

  // Interfaces
  { id: "users", group: "interfaces", col: 0, row: 0, title: "Auditors & reviewers", sub: "viewer · reviewer · admin", kind: "external",
    detail: "The people using the platform. Every endpoint needs a role when tokens or users are configured." },
  { id: "web", group: "interfaces", col: 0, row: 1, title: "Web application", sub: "React 18 · Vite · React Three Fiber", kind: "serve",
    detail: "This application: overview, review queue, invoices, Kafka streams, agents, Ask AI, knowledge graphs, policy, analytics, rings and results, with 3D views.", files: ["frontend/src/"] },
  { id: "api", group: "interfaces", col: 0, row: 2, title: "REST API", sub: "api.py · FastAPI · bearer roles", kind: "serve",
    detail: "Every request opens its own connection; long work (audits, ledger loads, model calls) runs as a background job with progress. CSP headers on every response.",
    files: ["auditiq/api.py", "docs/API.md"] },
  { id: "cli", group: "interfaces", col: 0, row: 3, title: "Command line", sub: "python -m auditiq", kind: "serve",
    detail: "setup, run, serve, stream, policy, ledger, ask and user commands.", files: ["auditiq/cli.py"] },
  { id: "dash", group: "interfaces", col: 0, row: 4, title: "Streamlit dashboard", sub: "app/dashboard.py", kind: "serve",
    detail: "The earlier dashboard, kept for quick inspection of the store.", files: ["app/dashboard.py"] },
];

export const EDGES: ArchEdge[] = [
  // Sources into the platform
  { from: "bench", to: "erp", label: "generates ledgers" },
  { from: "bench", to: "mailbox", label: "writes correspondence" },
  { from: "bench", to: "labels", label: "answer key" },
  { from: "demo", to: "sop", label: "five demo SOPs" },
  { from: "erp", to: "importer", label: "workbook · CSV zip" },
  { from: "erp", to: "producer", label: "ledger records" },
  { from: "mailbox", to: "producer", label: "e-mails" },
  { from: "sop", to: "producer", label: "policy PDFs" },
  { from: "sop", to: "pdfIngest", label: "upload · setup" },

  // Ingestion
  { from: "launcher", to: "kafkaLocal", label: "starts the broker", kind: "control" },
  { from: "launcher", to: "producer", label: "publishes everything", kind: "control" },
  { from: "launcher", to: "workers", label: "starts the workers", kind: "control" },
  { from: "launcher", to: "api", label: "starts the web app", kind: "control" },
  { from: "kafkaLocal", to: "broker", label: "runs", kind: "control" },
  { from: "broker", to: "t-vendor", label: "hosts" },
  { from: "producer", to: "t-vendor", label: "produce" },
  { from: "producer", to: "t-invoice", label: "produce" },
  { from: "producer", to: "t-email", label: "produce" },
  { from: "producer", to: "t-compliance", label: "produce" },
  { from: "t-vendor", to: "workers", label: "consume" },
  { from: "t-invoice", to: "workers", label: "consume" },
  { from: "t-email", to: "workers", label: "consume" },
  { from: "t-compliance", to: "workers", label: "consume" },
  { from: "workers", to: "ledger", label: "batch + offsets, one transaction" },
  { from: "workers", to: "streamT", label: "offsets" },
  { from: "workers", to: "emails", label: "link e-mails", kind: "control" },
  { from: "workers", to: "pdfIngest", label: "new policy version", kind: "control" },
  { from: "workers", to: "service", label: "audit a complete group", kind: "control" },
  { from: "emails", to: "mail", label: "emails · mentions" },
  { from: "importer", to: "ledger", label: "replace the ledger" },

  // Policy as data
  { from: "pdfIngest", to: "compiler", label: "rules with pages" },
  { from: "pdfIngest", to: "reader", label: "free wording" },
  { from: "pdfIngest", to: "policyT", label: "documents · passages" },
  { from: "compiler", to: "registry", label: "thresholds" },
  { from: "reader", to: "confirm", label: "proposed values" },
  { from: "reader", to: "chat", label: "values with quotes", kind: "model" },
  { from: "confirm", to: "registry", label: "confirmed values" },
  { from: "registry", to: "policyT", label: "versioned clauses" },
  { from: "registry", to: "simulation", label: "draft version" },
  { from: "ledger", to: "simulation", label: "every invoice" },
  { from: "registry", to: "controls", label: "thresholds in force", kind: "config" },
  { from: "registry", to: "math", label: "remit · clauses", kind: "config" },
  { from: "registry", to: "tax", label: "remit · clauses", kind: "config" },
  { from: "registry", to: "vendorint", label: "remit · clauses", kind: "config" },

  // Audit engine
  { from: "service", to: "extract", label: "one graph run per invoice", kind: "control" },
  { from: "ledger", to: "extract", label: "PO · GRN · approvals" },
  { from: "mail", to: "extract", label: "linked e-mails" },
  { from: "ledger", to: "history", label: "the vendor's invoices" },
  { from: "history", to: "extract", label: "dated before" },
  { from: "history", to: "controls", label: "index for 2.2.1 · 4.1.1" },
  { from: "extract", to: "controls", label: "evidence", kind: "control" },
  { from: "extract", to: "single", label: "C2: whole policy", kind: "variant" },
  { from: "controls", to: "math", label: "evidence + findings", kind: "control" },
  { from: "controls", to: "tax", label: "evidence + findings", kind: "control" },
  { from: "controls", to: "vendorint", label: "evidence + findings", kind: "control" },
  { from: "math", to: "challenger", label: "findings", kind: "control" },
  { from: "tax", to: "challenger", label: "findings", kind: "control" },
  { from: "vendorint", to: "challenger", label: "findings", kind: "control" },
  { from: "challenger", to: "confidence", label: "kept findings", kind: "control" },
  { from: "confidence", to: "score", label: "c per finding", kind: "control" },
  { from: "controls", to: "score", label: "C1: controls only", kind: "variant" },
  { from: "single", to: "score", label: "C2 findings", kind: "variant" },
  { from: "score", to: "route", label: "R0 · Rc", kind: "control" },
  { from: "route", to: "review", label: "escalate · sample", kind: "control" },
  { from: "route", to: "pack", label: "approve", kind: "control" },
  { from: "review", to: "pack", label: "decision", kind: "control" },
  { from: "controls", to: "corrections", label: "control findings" },
  { from: "corrections", to: "pack", label: "revisions" },
  { from: "pack", to: "audit", label: "results · flags · trail" },
  { from: "review", to: "audit", label: "review_decisions" },
  { from: "math", to: "chat", label: "structured call", kind: "model" },
  { from: "tax", to: "chat", label: "structured call", kind: "model" },
  { from: "vendorint", to: "chat", label: "structured call", kind: "model" },
  { from: "single", to: "chat", label: "one prompt", kind: "model" },
  { from: "challenger", to: "chat", label: "verify", kind: "model" },
  { from: "confidence", to: "chat", label: "3 re-runs at 0.7", kind: "model" },
  { from: "chat", to: "cache", label: "replies by request" },

  // Store
  { from: "audit", to: "views", label: "latest · waiting" },
  { from: "pgLocal", to: "engines", label: "serves PostgreSQL", kind: "control" },

  // Intelligence
  { from: "ledger", to: "analytics", label: "invoices · approvals" },
  { from: "audit", to: "analytics", label: "latest results" },
  { from: "labels", to: "analytics", label: "coverage vs answer key" },
  { from: "analytics", to: "rings", label: "approver rates" },
  { from: "ledger", to: "rings", label: "PAN · GSTIN · approvals" },
  { from: "rings", to: "caseGraph", label: "rings" },
  { from: "audit", to: "caseGraph", label: "findings · messages" },
  { from: "policyGraph", to: "caseGraph", label: "rule nodes" },
  { from: "registry", to: "policyGraph", label: "clauses · parameters" },
  { from: "policyT", to: "policyGraph", label: "document pages" },
  { from: "controls", to: "policyGraph", label: "checked by (code)" },
  { from: "policyT", to: "retrieval", label: "passages" },
  { from: "retrieval", to: "embed", label: "embed", kind: "model" },
  { from: "retrieval", to: "chat", label: "question rewrite", kind: "model" },
  { from: "retrieval", to: "copilot", label: "ranked passages" },
  { from: "policyGraph", to: "copilot", label: "policy facts" },
  { from: "caseGraph", to: "copilot", label: "audit facts" },
  { from: "pack", to: "copilot", label: "invoice audit pack" },
  { from: "datadict", to: "copilot", label: "table meanings" },
  { from: "copilot", to: "guard", label: "one SELECT", kind: "control" },
  { from: "ledger", to: "guard", label: "read-only rows" },
  { from: "copilot", to: "chat", label: "answer with citations", kind: "model" },

  // Interfaces
  { from: "users", to: "web", label: "browser" },
  { from: "web", to: "api", label: "JSON over HTTP" },
  { from: "views", to: "api", label: "pages read views" },
  { from: "access", to: "api", label: "tokens · roles" },
  { from: "analytics", to: "api", label: "analytics · coverage" },
  { from: "rings", to: "api", label: "rings" },
  { from: "copilot", to: "api", label: "Ask AI" },
  { from: "simulation", to: "api", label: "what-if result" },
  { from: "api", to: "service", label: "audit jobs", kind: "control" },
  { from: "api", to: "importer", label: "POST /api/ledger", kind: "control" },
  { from: "api", to: "pdfIngest", label: "policy upload", kind: "control" },
  { from: "api", to: "review", label: "reviewer decisions", kind: "control" },
  { from: "cli", to: "service", label: "run --config", kind: "control" },
  { from: "cli", to: "producer", label: "stream publish", kind: "control" },
  { from: "views", to: "dash", label: "reads the store" },

  // Delivery
  { from: "container", to: "api", label: "API + built web app", kind: "control" },
  { from: "compose", to: "container", label: "runs", kind: "control" },
  { from: "compose", to: "broker", label: "kafka service", kind: "control" },
  { from: "ci", to: "container", label: "builds · tests", kind: "control" },
  { from: "reproduce", to: "bench", label: "regenerates ledgers", kind: "control" },
  { from: "reproduce", to: "service", label: "re-audits", kind: "control" },
];

export function groupSize(g: ArchGroup): { w: number; h: number } {
  return { w: PAD_X * 2 + g.cols * NODE_W + (g.cols - 1) * GAP_X, h: PAD_TOP + PAD_BOTTOM + g.rows * NODE_H + (g.rows - 1) * GAP_Y };
}

/** Position of a node inside its group. */
export function localPosition(n: ArchNode): { x: number; y: number } {
  return { x: PAD_X + n.col * (NODE_W + GAP_X), y: PAD_TOP + n.row * (NODE_H + GAP_Y) };
}

export function absoluteBox(n: ArchNode): { x: number; y: number; w: number; h: number } {
  const g = GROUPS.find((x) => x.id === n.group)!;
  const p = localPosition(n);
  return { x: g.x + p.x, y: g.y + p.y, w: NODE_W, h: NODE_H };
}

/** The sides an edge leaves and enters by: horizontal unless the two components are stacked. */
export function edgeSides(e: ArchEdge): { source: Side; target: Side } {
  const a = absoluteBox(NODES.find((n) => n.id === e.from)!), b = absoluteBox(NODES.find((n) => n.id === e.to)!);
  const dx = b.x + b.w / 2 - (a.x + a.w / 2), dy = b.y + b.h / 2 - (a.y + a.h / 2);
  const stacked = Math.abs(dx) < NODE_W * 0.75;
  if (stacked) return dy >= 0 ? { source: "b", target: "t" } : { source: "t", target: "b" };
  return dx >= 0 ? { source: "r", target: "l" } : { source: "l", target: "r" };
}

/** What flows into a component and what flows out of it. */
export function neighbours(id: string): { inputs: ArchEdge[]; outputs: ArchEdge[] } {
  return { inputs: EDGES.filter((e) => e.to === id), outputs: EDGES.filter((e) => e.from === id) };
}
