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
}

export type RecordMap = Record<string, unknown>;

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

export interface PolicyOverview {
  active: string | null;
  versions: PolicyVersion[];
  rules: PolicyRule[];
  documents: PolicyDocument[];
  results_under_other_versions: number;
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
