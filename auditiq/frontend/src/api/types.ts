// Shapes of the AuditIQ REST API (auditiq/api.py). Values are as the API returns them.

export type Route = "approve" | "sample" | "escalate";
export type RiskLevel = "LOW" | "MEDIUM" | "HIGH" | "CRITICAL";
export type Severity = "low" | "medium" | "high" | "critical";
export type ConfigName = "C1" | "C2" | "C3" | "C4" | "C5";

/** Who the API sees: a user's account, the shared token, or anyone on an open server (GET /api/me). */
export interface Me {
  name: string | null;
  role: "viewer" | "reviewer" | "admin";
  via: "account" | "shared token" | "open";
}

export interface Health {
  status: string;
  version: string;
  backend: "sqlite" | "postgres";
  ledger: string | null;
  policy_version: string | null;
  model: string | null;
  auth: boolean;
}

export interface RuleFindings {
  rule: string;
  title: string;
  severity: Severity;
  source: "control" | "agent";
  findings: number;
}

export interface RunRow {
  run_id: number;
  configuration: ConfigName;
  policy_version: string;
  model: string | null;
  note: string | null;
  started_at: string | null;
  finished_at: string | null;
  invoices: number;
}

export interface VendorWaiting {
  vendor_id: string;
  vendor_name: string;
  waiting: number;
  amount: number;
}

export interface Overview {
  ledger: string | null;
  policy_version: string | null;
  backend: string;
  model: string | null;
  invoices: number;
  vendors: number;
  audited: number;
  states: Record<string, number>;
  routes: Partial<Record<Route, number>>;
  risk_levels: Partial<Record<RiskLevel, number>>;
  findings: number;
  reviewed: number;
  findings_by_rule: RuleFindings[];
  runs: RunRow[];
  vendors_waiting: VendorWaiting[];
  /** The newest steps of the audit trail. */
  activity?: ActivityRow[];
  coverage?: Coverage;
}

export interface ActivityRow {
  entry_id: number;
  invoice_id: string;
  created_at: string | null;
  stage: string;
  actor: string;
  detail: string | null;
}

/** Results against the benchmark's answer key: an anomaly is found when its invoice has any kept finding. */
export interface KeySummary {
  found: number;
  false_alarms: number;
  missed: number;
  /** Anomalies of a rule the configuration could not evaluate (a judgement rule without agents). */
  not_checked: number;
  passed: number;
  precision: number | null;
  recall: number | null;
}

export interface AnswerKey extends KeySummary {
  hard_negatives_flagged: number;
  /** The policy version the labels were written for; results under another version are not scored. */
  policy_version: string;
  other_policy: number;
  by_configuration: Record<string, KeySummary>;
}

/** What produced the latest results and what they did not check (GET /api/overview). */
export interface Coverage {
  configurations: Record<string, number>;
  controls_run: number;
  judgement_run: number;
  judgement_clauses: string[];
  approved_with_findings: number;
  answer_key: AnswerKey | null;
}

export interface VendorPoint {
  vendor_id: string;
  vendor_name: string;
  category: string;
  invoices: number;
  amount: number;
  waiting: number;
  findings: number;
  max_risk: number;
  blacklisted: number;
}

export interface Stage {
  id: string;
  label: string;
  kind: "code" | "llm" | "person";
  feature?: boolean;
}

export interface Pipeline {
  stages: Stage[];
  configurations: Record<ConfigName, string[]>;
}

export interface QueueItem {
  result_id: number;
  invoice_id: string;
  vendor_id: string;
  vendor_name: string;
  invoice_date: string;
  amount: number;
  route: Route;
  risk_level: RiskLevel;
  r0: number;
  rc: number;
  flag_count: number;
  configuration: ConfigName;
  created_at: string;
  /** The rules its kept findings break, the most severe first. */
  rules: string[];
}

export interface InvoiceRow {
  invoice_id: string;
  vendor_id: string;
  vendor_name: string;
  date: string;
  amount: number;
  route: Route | null;
  risk_level: RiskLevel | null;
  rc: number | null;
  workflow_status: string | null;
}

export interface Evidence {
  field: string;
  value: unknown;
}

export interface PackFlag {
  clause: string;
  title: string;
  severity: Severity;
  source: string;
  confidence: number | null;
  evidence: Evidence[];
  message: string;
  confidence_terms?: { g: number | null; p: number | null; a: number | null };
  citation?: { document: string; page: number };
  revision?: Revision;
}

/** What a control finding requires, computed from its evidence and the policy (auditiq/corrections.py). */
export interface Revision {
  clause: string;
  kind: "amend" | "reapprove" | "consolidate" | "reject" | "hold" | "obtain" | "verify";
  action: string;
  changes: { field: string; from: unknown; to: unknown }[];
  amount_at_issue: number | null;
}

/** What a policy document would do to the ledger before it is adopted (POST /api/policy/simulate). */
export interface Simulation {
  active_version: string;
  new_version: string | null;
  /** The versions in force on the invoices' dates, which the document is compared with, and how many each governs. */
  baseline: Record<string, number>;
  effective_date: string | null;
  /** Adopted, the document governs only the invoices dated from its effective date: this many of the ledger's. */
  governs_if_adopted: number;
  invoices: number;
  decisions_moved: number;
  newly_flagged: number;
  cleared: number;
  routes: { before: Record<string, number>; after: Record<string, number> };
  route_changes: Record<string, number>;
  findings_by_rule: { rule: string; before: number; after: number }[];
  amount_newly_held: number;
  examples: { invoice_id: string; amount: number; before: string[]; after: string[]; route_before: string; route_after: string }[];
}

export interface AuditPack {
  invoice_id: string;
  vendor_id: string;
  vendor_name: string | null;
  policy_version: string;
  configuration: ConfigName;
  model: string | null;
  route: Route;
  risk_level: RiskLevel;
  count_based_risk: number;
  weighted_risk: number;
  threshold: number;
  flags: PackFlag[];
  removed_by_challenger: { clause: string; agent: string | null; message: string; reason: string }[];
  review: { queue: string; decision: string; reviewer: string; justification: string; decided_at: string } | null;
  recommended_action: string;
}

export interface TrailEntry {
  seq: number;
  stage: string;
  actor: string | null;
  detail: string | null;
  prompt_tokens: number | null;
  completion_tokens: number | null;
  latency_ms: number | null;
}

export interface InvoiceResult {
  result_id: number;
  run_id: number;
  route: Route;
  risk_level: RiskLevel;
  r0: number;
  rc: number;
  workflow_status: string;
  configuration: ConfigName;
  model: string | null;
  policy_version: string;
  created_at: string;
  pack: AuditPack;
  trail: TrailEntry[];
  /** Whether the result and its trail still match their seals, and the ledger the records the result was based on. */
  integrity?: "intact" | "altered" | "unsealed" | "stale";
}

export interface EvidenceDrift {
  checked: number;
  fingerprinted: number;
  without_fingerprint: number;
  unchanged: number;
  changed: number;
  changed_by_record: Record<string, number>;
  missing: number;
  changed_invoices: { invoice_id: string; changed: string[] }[];
  current: boolean;
}

export interface ReliabilityCheck {
  id: string;
  title: string;
  assertion: string;
  exceptions: number;
  examples: string[];
  decided_by: string | null;
  note: string;
}

export interface Reliability {
  ledger: string | null;
  totals: { table: string; records: number; amount: number | null }[];
  fingerprint: { tables: Record<string, string>; ledger: string };
  checks: ReliabilityCheck[];
  summary: { checks: number; without_exceptions: number; open: string[]; decided_by_rules: string[]; coverage: string[]; reliable: boolean; conclusion: string };
}

export interface ProgramTest {
  id: string;
  title: string;
  how: string;
  assertions: string[];
  schemes: string[];
  in_policy: boolean | null;
  found: number | null;
  listed: number | null;
  ran: boolean;
}

export interface AuditProgram {
  policy_version: string | null;
  assertions: Record<string, string>;
  schemes: Record<string, string>;
  tests: ProgramTest[];
  by_assertion: Record<string, string[]>;
  by_scheme: Record<string, string[]>;
  untested: { assertions: string[]; schemes: string[] };
  limits: Record<string, string>;
  agents_ran: number;
  answer_key: { policy_version: string; compared: boolean; schemes?: Record<string, { labelled: number; found: number; lead_only: number; missed: number; reached: number | null }> } | null;
}

export type RecordMap = Record<string, unknown>;

// ---- assurance: the sealed record, judgement-rule leads, monetary-unit sampling

export interface TrailCheck {
  intact: boolean;
  results: { checked: number; sealed: number; unsealed: number; altered: number; altered_ids: number[]; review_inconsistent: number; review_inconsistent_ids: number[] };
  entries: { checked: number; broken: number; broken_ids: number[]; unsealed: number };
  runs: { sealed: number; open: number; unsealed: number; altered: number; altered_ids: number[] };
  evidence?: EvidenceDrift;
  digest: string | null;
}

export interface DuplicateLead {
  invoice_id: string;
  original_id: string;
  vendor_id: string;
  vendor_name: string;
  number: string;
  original_number: string;
  date: string;
  original_date: string;
  amount: number;
  po_id: string;
  grn_id: string;
  reason: string;
}

export interface StructuringLead {
  vendor_id: string;
  vendor_name: string;
  role: string;
  limit: number;
  invoices: string[];
  first: string;
  last: string;
  total: number;
  amounts: number[];
  descriptions: string[];
  same_description: boolean;
}

export interface LeadOutcome {
  clause: string;
  count: number;
  invoices: number;
  amount: number;
  approved: number;
  to_a_person: number;
  unaudited: number;
  configurations: Record<string, number>;
}

export interface LeadKey {
  labelled: number;
  listed: number;
  listed_labelled: number;
  recall: number | null;
  precision: number | null;
  listed_otherwise: Record<string, number>;
}

export interface Leads {
  policy_version: string | null;
  guide: { window_days: number; band_pct: number; limits: Record<string, number> };
  near_duplicates: LeadOutcome & { pairs: DuplicateLead[] };
  structuring: LeadOutcome & { groups: StructuringLead[] };
  answer_key: ({ policy_version: string; compared: boolean } & Partial<Record<"2.2.2" | "4.1.2", LeadKey>>) | null;
}

export interface SamplePlan {
  book_value: number;
  items: number;
  confidence: number;
  tolerable_pct: number;
  tolerable: number;
  expected_pct: number;
  expected: number;
  reliability_factor: number;
  expansion_factor: number;
  size: number;
  interval: number;
}

export interface SampledInvoice {
  invoice_id: string;
  amount: number;
  vendor_name: string | null;
  findings: number;
  date: string | null;
  units: number;
  certain: boolean;
}

export interface MonetaryUnitSample {
  plan: SamplePlan;
  seed: number;
  start: number;
  drawn: number;
  certain: number;
  sample: SampledInvoice[];
  answer_key: {
    misstatements: number;
    top_stratum_actual: number;
    projected: number;
    basic_precision: number;
    upper_limit: number;
    true_misstatement: number;
    bound_holds: boolean;
    conclusion: string;
    sampled_anomalous: string[];
  } | null;
}

/** A vendor e-mail that names an invoice; it arrived through the Kafka topic of e-mails. */
export interface VendorEmail {
  message_id: string;
  sender: string;
  subject: string;
  sent_at: string | null;
  body: string;
}

/** One topic of the Kafka ingestion layer, as the workers see it. */
export interface StreamTopic {
  kind: "invoice" | "email" | "vendor" | "compliance";
  topic: string;
  partitions: number;
  messages: number;
  processed: number;
  lag: number;
  outcomes: Record<string, number>;
}

export interface StreamStatus {
  configured: boolean;
  bootstrap?: string;
  topics: StreamTopic[];
  error?: string;
}

export interface InvoiceDetail {
  records: {
    invoice: RecordMap;
    po: RecordMap | null;
    grn: RecordMap | null;
    vendor: RecordMap | null;
    approvals: RecordMap[];
  };
  history: { total: number; items: RecordMap[] };
  result: InvoiceResult | null;
  emails?: VendorEmail[];
  benchmark_label?: { label: string; class_id: string; clause_ids: string; hard_negative_type: string; note: string } | null;
}

/** The outcome of loading a ledger: with any problem, nothing was replaced. */
export interface LedgerLoad {
  loaded: boolean;
  ledger: string;
  problems: string[];
  counts: Record<string, number>;
}

export interface Job<T = unknown> {
  id: string;
  kind: string;
  status: "queued" | "running" | "done" | "failed";
  done: number;
  total: number;
  result: T | null;
  error: string | null;
  seconds: number;
}

export interface PolicyVersion {
  version: string;
  policy_name: string | null;
  effective_date: string | null;
  active: boolean;
  adoption: { model: string; confirmed_by: string; confirmed_at: string; values_supplied_by_the_person: string[] } | null;
}

export interface PolicyRule {
  rule: string;
  title: string;
  severity: Severity;
  kind: "control" | "judgement";
  params: Record<string, unknown>;
}

export interface PolicyDocument {
  file_name: string;
  title: string | null;
  version: string | null;
  pages: number;
  ingested_at: string | null;
  passages: number;
  rules: number;
}

/** A period of the policy timeline: the version that governs the invoices dated from `from` until `until`. */
export interface PolicyPeriod {
  version: string;
  from: string | null;
  until: string | null;
  invoices: number;
  /** Invoices of the period last audited under another version: their result does not follow the policy of their date. */
  under_other_version: number;
  unaudited: number;
}

export interface PolicyOverview {
  active: string | null;
  versions: PolicyVersion[];
  rules: PolicyRule[];
  documents: PolicyDocument[];
  /** Each invoice is judged by the version in force on its date, not by whatever version is active now. */
  timeline: PolicyPeriod[];
  under_other_version: number;
  unaudited: number;
}

/** What applying the policy did: the invoices audited again, one run per version in force. */
export interface ApplySummary {
  invoices: number;
  flags: number;
  states: Record<string, number>;
  unchanged: number;
  runs: { run_id: number; policy_version: string | null; invoices: number }[];
}

export interface Change {
  clause: string;
  parameter: string;
  from: unknown;
  to: unknown;
}

export interface Preview {
  upload_id: string;
  file: string;
  title: string;
  version: string | null;
  pages: number;
  usable: boolean;
  problems: string[];
  changes: Change[];
}

export interface ProposalItem {
  clause: string;
  parameter: string;
  value: unknown;
  reference: unknown;
  status: "verified" | "needs attention" | "missing";
  reason: string;
  quote: string;
  page: number | null;
}

export interface Proposal {
  file: string;
  title: string;
  version: string | null;
  pages: number;
  model: string;
  problems: string[];
  usage: Record<string, unknown>;
  rules: Record<string, { located: boolean; quotes: { text: string; page: number }[]; by_person: boolean }>;
  items: ProposalItem[];
}

export interface Hit {
  chunk_id: number;
  document: string;
  version: string | null;
  kind: string;
  clause_id: string | null;
  section: string;
  page: number;
  text: string;
  score: number;
  source: string;
}

export interface CopilotAnswer {
  answer: string | null;
  invoice_id: string | null;
  model: string | null;
  passages: Hit[];
  sources: Hit[];
  /** Facts of the policy graph given to the model with the passages, and the graph nodes they come from. */
  facts?: GraphFact[];
  graph_nodes?: string[];
  /** Facts of the ledger graph (vendors, invoices, approvers, rings): computed by code from the audit. */
  case_facts?: GraphFact[];
  case_nodes?: string[];
}

export interface DataAnswer {
  sql: string | null;
  columns: string[];
  rows: unknown[][];
  explanation: string;
  error: string | null;
}

export interface Interval {
  value: number | null;
  ci_low?: number | null;
  ci_high?: number | null;
}

export interface BenchmarkLedger {
  n_invoices: number;
  metrics: Record<string, Record<string, Interval>>;
  per_class: Record<string, Record<string, Interval>>;
  construction_checks: Record<string, Record<string, boolean>>;
}

export interface PolicyVariant {
  version: string;
  name: string;
  change: string;
  parameters: number;
  parameters_read_correctly: number;
  rules: number;
  rules_read_word_for_word: number;
  affected: number;
  driven: { invoices: number; exact: number };
  frozen: { invoices: number; exact: number; stale_findings: number; missed_exceptions: number; needless_escalations: number; missed_escalations: number };
}

export interface Results {
  benchmark: Record<string, BenchmarkLedger>;
  policy_swap: { metrics: Record<string, Record<string, Interval | number>> } | null;
  policy_change: { invoices: number; audits: number; audit_seconds: number; variants: PolicyVariant[]; produced: string } | null;
  scalability: {
    produced: string;
    logical_cpus: number;
    by_workers: { workers: number; audits: number; seconds: number; invoices_per_second: number; findings: number }[];
    by_size: { invoices: number; seconds: number; invoices_per_second: number; microseconds_per_invoice: number }[];
  } | null;
  policy_reading: {
    produced: string;
    model: string;
    total: Record<string, number>;
    documents: { file: string; style: string; policy: string; counts: Record<string, number | boolean>; usage: { seconds: number } }[];
  } | null;
  pilots: Record<string, { model: string | null; dataset?: string | null; summary: Record<string, unknown>; started: string; finished: string }>;
}

// ------------------------------------------------------------------ analytics (GET /api/analytics)
export interface BenfordDigit {
  digit: number;
  count: number;
  observed: number;
  expected: number;
  z: number;
  significant: boolean;
}

export interface BenfordTest {
  digits: BenfordDigit[];
  mad: number;
  chi2: number;
  dof: number;
  conformity: string;
  thresholds: number[];
}

export interface MonthRow {
  month: string;
  invoices: number;
  amount: number;
  flagged: number;
  escalated: number;
  findings: number;
}

export interface LimitBand {
  role: string;
  limit: number;
  below: number;
  above: number;
}

export interface ApproverRow {
  approver: string;
  role: string | null;
  limit: number | null;
  invoices: number;
  amount: number;
  flagged: number;
  flagged_amount: number;
  over_limit: number;
  vendors: number;
}

export interface Analytics {
  invoices: number;
  policy_version: string | null;
  monthly: MonthRow[];
  skyline: { months: string[]; categories: string[]; amounts: number[][] };
  benford: { n: number; first: BenfordTest; first_two: BenfordTest };
  amounts: { bins: { low: number; high: number; invoices: number; flagged: number }[]; limits: LimitBand[]; near?: number };
  weekdays: { weekday: string; invoices: number; amount: number; flagged: number }[];
  categories: { rules: string[]; rows: { category: string; invoices: number; amount: number; flagged: number; findings: number[] }[] };
  approvers: { total: number; top: ApproverRow[] };
  concentration: {
    vendors: number;
    gini: number | null;
    lorenz: [number, number][];
    top10_share: number | null;
    hhi: number | null;
    top: { vendor_id: string; vendor_name: string; amount: number; share: number }[];
  };
}

// ------------------------------------------------------------------ collusion rings (GET /api/rings)
export interface RingNode {
  id: string;
  kind: "vendor" | "approver";
  ring: number;
  label: string | null;
  vendor_id?: string;
  category?: string | null;
  blacklisted?: boolean;
  invoices?: number;
  amount?: number;
  flagged?: number;
  max_risk?: number;
  top_approver_share?: number | null;
  role?: string | null;
  limit?: number | null;
}

export interface RingEdge {
  source: string;
  target: string;
  ring: number;
  kinds: string[];
  invoices: number;
  amount: number;
  rules: Record<string, number>;
}

export interface Ring {
  id: number;
  vendors: string[];
  vendor_names: string[];
  approvers: string[];
  approver_roles: (string | null)[];
  links: number;
  link_kinds: Record<string, number>;
  rules: Record<string, number>;
  flagged_invoices: number;
  flagged_amount: number;
  amount: number;
  blacklisted: number;
  waiting: number;
  max_risk: number;
}

export interface RingPair {
  vendor_id: string;
  vendor_name: string | null;
  approvers: string[];
  roles: (string | null)[];
  link_kinds: Record<string, number>;
  rules: Record<string, number>;
  flagged_invoices: number;
  flagged_amount: number;
  max_risk: number;
}

/** An approver-vendor pair on the watch list: its findings against what the approver's role makes likely. */
export interface WatchPair {
  approver: string;
  role: string | null;
  vendor_id: string;
  vendor_name: string | null;
  flagged: number;
  invoices: number;
  expected: number;
  p: number;
  q: number;
  significant: boolean;
  amount: number;
  rules: Record<string, number>;
}

export interface RingTests {
  fdr: number;
  repeated: number;
  pairs_tested: number;
  pairs_with_findings: number;
  pairs_significant: number;
  approvers_tested: number;
  hotspots: number;
  min_q_pair: number | null;
  min_q_approver: number | null;
  role_rates: { role: string | null; invoices: number; flagged: number; rate: number }[];
}

export interface Rings {
  rings: Ring[];
  total_rings: number;
  pairs: RingPair[];
  total_pairs: number;
  nodes: RingNode[];
  edges: RingEdge[];
  /** The most unusual pairs, significant or not, and the same pairs grouped for drawing. */
  watch: WatchPair[];
  leads: { groups: Ring[]; nodes: RingNode[]; edges: RingEdge[] };
  tests: RingTests;
  identity: { vendors: number; shared_pan: number; shared_gstin: number; another_vendors_gstin: number; gstin_mismatches: number; approvers: number };
  method: { concentration_share: number; concentration_min: number; repeated: number; fdr: number; limit_clause: string | null; links: string[] };
}

// ------------------------------------------------------------------ policy graph (GET /api/policy/graph)
export type GraphNodeKind = "version" | "section" | "clause" | "parameter" | "role" | "checker" | "page";

export interface GraphNode {
  id: string;
  kind: GraphNodeKind;
  label: string;
  title?: string;
  severity?: Severity;
  clause_kind?: "control" | "judgement";
  findings?: number;
  value?: unknown;
  clause?: string;
  limit?: number;
  checker_kind?: "agent" | "control";
  document?: string;
  page?: number;
  active?: boolean;
  effective?: string;
  other?: boolean;
}

export interface GraphEdge {
  source: string;
  target: string;
  kind: string;
  label: string;
}

export interface PolicyGraphData {
  version: string;
  versions: { version: string; policy_name: string | null; effective_date: string; is_active: boolean }[];
  nodes: GraphNode[];
  edges: GraphEdge[];
  counts: Record<string, number>;
}

/** A fact of the policy graph, with the rule and version it rests on and the passage that states it. */
export interface GraphFact {
  text: string;
  kind: string;
  version: string;
  clause: string | null;
  source: string | null;
  chunk_id: number | null;
  data: Record<string, unknown>;
}

export interface GraphAnswer {
  question: string;
  version: string;
  recognised: Record<string, unknown>;
  facts: GraphFact[];
  passages: Hit[];
  nodes: string[];
}

// ------------------------------------------------------------------ the console (GET /api/system, /api/stream/*, /api/rag/trace, /api/knowledge, /api/ai)
export interface SystemStatus {
  store: { backend: string; ledger: string | null };
  policy_version: string | null;
  kafka: { configured: boolean; connected: boolean; bootstrap?: string; prefix?: string; error?: string };
  model: { configured: boolean; name?: string; reachable: boolean; status?: string; endpoint?: string };
  embeddings: { configured: boolean; model: string | null; embedded: number; passages: number };
}

export interface StreamSources {
  ledgers: { name: string; invoices: number | null; vendors: number | null }[];
  mailboxes: { name: string; bytes: number }[];
  policies: { name: string; bytes: number }[];
}

export interface StreamLogRow {
  topic: string;
  partition_no: number;
  kafka_offset: number;
  doc_key: string | null;
  produced_ms: number | null;
  processed_ms: number | null;
  outcome: string;
  detail: string | null;
  result_id: number | null;
  latency_ms: number | null;
}

export interface PeekMessage {
  partition: number;
  offset: number;
  key: string;
  timestamp: number | null;
  bytes: number;
  preview: Record<string, unknown>;
}

export interface RagPassage {
  chunk_id: number;
  document: string;
  version: string | null;
  kind: string;
  clause_id: string | null;
  section: string;
  page: number;
  text: string;
  lexical: number;
  lexical_rank: number;
  dense?: number;
  dense_rank?: number;
  hybrid?: number;
  hybrid_rank?: number;
  point?: [number, number, number];
}

export interface RagTrace {
  question: string;
  mode: string;
  k: number;
  rrf_k: number;
  embedding_model: string | null;
  dense_error: string | null;
  recognised: Record<string, unknown>;
  facts: GraphFact[];
  context: (Hit & { from: "graph" | "retrieval" })[];
  passages: RagPassage[];
  query_point: [number, number, number] | null;
  explained: number[];
}

export interface KnowledgePassage {
  chunk_id: number;
  document: string;
  version: string | null;
  kind: string;
  clause_id: string | null;
  section: string;
  page: number;
  verified: boolean | null;
  text: string;
  embed_model: string | null;
  point?: [number, number, number];
}

export interface KnowledgeLayer {
  documents: { doc_id: number; file_name: string; title: string | null; version: string | null; pages: number; ingested_at: string; passages: number }[];
  passages: KnowledgePassage[];
  explained: number[];
  /** The model whose vectors the map shows (null when no passage is embedded). */
  embedding_model: string | null;
  registry: Record<string, Record<string, { title: string; severity: Severity; kind: "control" | "judgement"; params: Record<string, unknown> }>>;
  versions: { version: string; policy_name: string | null; effective_date: string; is_active: boolean }[];
}

export interface AiLayer {
  policy_version: string | null;
  model: string | null;
  agents: { name: string; title: string; sections: string[]; judges: string[]; records: string[]; history_rules: string[] }[];
  configurations: Record<string, { controls: boolean; agents: string; challenger: boolean; confidence: boolean; reruns: number; temperature: number; rerun_temperature: number }>;
  stages: { stage: string; actor: string | null; steps: number; prompt_tokens: number; completion_tokens: number; mean_latency_ms: number | null; model_calls: number }[];
  traced: { invoice_id: string; configuration: string; route: string; risk_level: string; rc: number; flag_count: number; llm_calls: number; prompt_tokens: number; completion_tokens: number; latency_ms: number; created_at: string }[];
}

// ------------------------------------------------------------------ the ledger as a graph
export type CaseNodeKind = "vendor" | "invoice" | "rule" | "approver" | "ring";

export interface CaseNode {
  id: string;
  kind: CaseNodeKind;
  label: string;
  /** The highest risk score among the node's invoices; invoices carry their own score. */
  risk?: number;
  amount?: number;
  category?: string;
  blacklisted?: boolean;
  invoices?: number;
  flagged?: number;
  role?: string;
  limit?: number | null;
  approvals?: number;
  over_limit?: number;
  severity?: Severity;
  level?: string;
  route?: string;
  date?: string;
  vendors?: number;
  approvers?: number;
  link_kinds?: Record<string, number>;
}

export interface CaseEdge {
  source: string;
  target: string;
  kind: string;
  count?: number;
  severity?: string;
}

export interface CaseGraphView {
  focus: string | null;
  focus_kind: CaseNodeKind | null;
  nodes: CaseNode[];
  edges: CaseEdge[];
  counts: Record<string, number>;
  policy_version: string;
  truncated: boolean;
}

export interface CaseAnswer {
  question: string;
  recognised: Record<string, unknown>;
  facts: GraphFact[];
  nodes: string[];
}
