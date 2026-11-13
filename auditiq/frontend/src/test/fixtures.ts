// Responses of the API used by the page tests, shaped as auditiq/api.py returns them.
import type { AiLayer, Analytics, GraphAnswer, Health, InvoiceDetail, KnowledgeLayer, Overview, PolicyGraphData, PolicyOverview, Preview, RagTrace, Results, Rings, StreamSources, StreamStatus, SystemStatus, CaseAnswer, CaseGraphView } from "../api/types";

export const health: Health = {
  status: "ok", version: "0.4.0", backend: "sqlite", ledger: "small_seed_7", policy_version: "2.5", model: null, auth: false,
};

export const overview: Overview = {
  ledger: "small_seed_7", policy_version: "2.5", backend: "sqlite", model: null, invoices: 1200, vendors: 60, audited: 60,
  states: { PENDING_REVIEW: 40, AUTO_APPROVED: 20 }, routes: { escalate: 40, approve: 20 }, risk_levels: { CRITICAL: 20, HIGH: 20, LOW: 20 },
  findings: 60, reviewed: 0,
  findings_by_rule: [
    { rule: "5.1.1", title: "Approval limit", severity: "critical", source: "control", findings: 20 },
    { rule: "2.1.1", title: "Amount match", severity: "high", source: "control", findings: 20 },
  ],
  runs: [{ run_id: 1, configuration: "C1", policy_version: "2.5", model: null, note: "", started_at: "2026-10-14 10:00:00", finished_at: "2026-10-14 10:00:01", invoices: 60 }],
  vendors_waiting: [{ vendor_id: "VEND1001", vendor_name: "Kurian LLC", waiting: 3, amount: 450000 }],
  activity: [
    { entry_id: 9, invoice_id: "INV40237", created_at: "2026-10-14 10:00:01", stage: "scoring", actor: "code", detail: "count-based 70.0, weighted 70.0, route escalate" },
    { entry_id: 8, invoice_id: "INV40237", created_at: "2026-10-14 10:00:01", stage: "controls", actor: "code", detail: "1 finding: 5.1.1" },
  ],
  coverage: {
    configurations: { C1: 55, C5: 5 }, controls_run: 60, judgement_run: 5, judgement_clauses: ["2.1.4", "2.1.5", "2.2.2", "4.1.2"], approved_with_findings: 4,
    answer_key: {
      found: 38, false_alarms: 2, missed: 1, not_checked: 3, passed: 16, precision: 0.95, recall: 0.905, hard_negatives_flagged: 2, policy_version: "2.5", other_policy: 0,
      by_configuration: {
        C1: { found: 36, false_alarms: 0, missed: 0, not_checked: 3, passed: 16, precision: 1, recall: 0.923 },
        C5: { found: 2, false_alarms: 2, missed: 1, not_checked: 0, passed: 0, precision: 0.5, recall: 0.667 },
      },
    },
  },
};

const digits = (n: number, from: number, special: number) =>
  Array.from({ length: n }, (_, i) => {
    const d = from + i;
    const expected = Math.log10(1 + 1 / d);
    return { digit: d, count: d === special ? 90 : 10, observed: d === special ? 0.45 : expected, expected, z: d === special ? 6.2 : 0.3, significant: d === special };
  });

export const analytics: Analytics = {
  invoices: 1200,
  policy_version: "2.5",
  monthly: [
    { month: "2025-04", invoices: 600, amount: 9.5e7, flagged: 30, escalated: 20, findings: 31 },
    { month: "2025-05", invoices: 600, amount: 8.1e7, flagged: 30, escalated: 20, findings: 30 },
  ],
  skyline: { months: ["2025-04", "2025-05"], categories: ["MRO", "Logistics"], amounts: [[5e7, 4e7], [4.5e7, 4.1e7]] },
  benford: {
    n: 1200,
    first: { digits: digits(9, 1, 9), mad: 0.0173, chi2: 48.2, dof: 8, conformity: "nonconformity", thresholds: [0.006, 0.012, 0.015] },
    first_two: { digits: digits(90, 10, 49), mad: 0.0011, chi2: 95.1, dof: 89, conformity: "close conformity", thresholds: [0.0012, 0.0018, 0.0022] },
  },
  amounts: {
    bins: [
      { low: 10000, high: 17782.8, invoices: 300, flagged: 5 },
      { low: 17782.8, high: 31622.8, invoices: 500, flagged: 15 },
      { low: 31622.8, high: 56234.1, invoices: 250, flagged: 20 },
      { low: 56234.1, high: 100000, invoices: 150, flagged: 20 },
    ],
    limits: [{ role: "Manager", limit: 100000, below: 96, above: 31 }],
    near: 0.1,
  },
  weekdays: ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"].map((weekday, i) => ({ weekday, invoices: i < 5 ? 230 : 25, amount: 1e6, flagged: i < 5 ? 10 : 5 })),
  categories: { rules: ["2.1.1", "5.1.1"], rows: [{ category: "MRO", invoices: 700, amount: 9e7, flagged: 35, findings: [20, 15] }, { category: "Logistics", invoices: 500, amount: 8.6e7, flagged: 25, findings: [0, 25] }] },
  approvers: { total: 17, top: [{ approver: "Janya Biswas", role: "Director", limit: 2500000, invoices: 116, amount: 8.9e7, flagged: 10, flagged_amount: 1.45e7, over_limit: 2, vendors: 40 }] },
  concentration: { vendors: 60, gini: 0.41, lorenz: [[0, 0], [0.5, 0.25], [1, 1]], top10_share: 0.31, hhi: 260, top: [{ vendor_id: "VEND1001", vendor_name: "Kurian LLC", amount: 1.2e7, share: 0.07 }] },
};

export const rings: Rings = {
  rings: [
    { id: 1, vendors: ["VEND1001", "VEND1002"], vendor_names: ["Kurian LLC", "Rajan Inc"], approvers: ["Janya Biswas"], approver_roles: ["Director"], links: 2,
      link_kinds: { "above own limit": 2 }, rules: { "5.1.1": 2 }, flagged_invoices: 2, flagged_amount: 8205120, amount: 3.1e7, blacklisted: 0, waiting: 2, max_risk: 70 },
  ],
  total_rings: 1,
  pairs: [{ vendor_id: "VEND1003", vendor_name: "Shah Traders", approvers: ["Neel Shroff"], roles: ["Manager"], link_kinds: { "repeated findings": 1 }, rules: { "2.1.1": 2 }, flagged_invoices: 2, flagged_amount: 310000, max_risk: 50 }],
  total_pairs: 1,
  nodes: [
    { id: "v:VEND1001", kind: "vendor", ring: 1, label: "Kurian LLC", vendor_id: "VEND1001", category: "MRO", blacklisted: false, invoices: 20, amount: 1.6e7, flagged: 1, max_risk: 70, top_approver_share: 0.2 },
    { id: "v:VEND1002", kind: "vendor", ring: 1, label: "Rajan Inc", vendor_id: "VEND1002", category: "IT Services", blacklisted: false, invoices: 18, amount: 1.5e7, flagged: 1, max_risk: 70, top_approver_share: 0.15 },
    { id: "a:Janya Biswas", kind: "approver", ring: 1, label: "Janya Biswas", role: "Director", limit: 2500000 },
  ],
  edges: [
    { source: "a:Janya Biswas", target: "v:VEND1001", ring: 1, kinds: ["above own limit"], invoices: 1, amount: 4396685.58, rules: { "5.1.1": 1 } },
    { source: "a:Janya Biswas", target: "v:VEND1002", ring: 1, kinds: ["above own limit"], invoices: 1, amount: 3808434.42, rules: { "5.1.1": 1 } },
  ],
  watch: [
    { approver: "Saksham Nagarajan", role: "Manager", vendor_id: "VEND1044", vendor_name: "Mammen Inc", flagged: 4, invoices: 5, expected: 0.26, p: 3.5e-5, q: 0.041, significant: false, amount: 1250000, rules: { "2.1.1": 3, "4.1.1": 1 } },
    { approver: "Janya Biswas", role: "Director", vendor_id: "VEND1001", vendor_name: "Kurian LLC", flagged: 2, invoices: 2, expected: 0.13, p: 0.0045, q: 0.94, significant: false, amount: 8205120, rules: { "5.1.1": 2 } },
  ],
  leads: {
    groups: [
      { id: 1, vendors: ["VEND1044"], vendor_names: ["Mammen Inc"], approvers: ["Saksham Nagarajan"], approver_roles: ["Manager"], links: 1,
        link_kinds: { "unusual approvals": 1 }, rules: { "2.1.1": 3, "4.1.1": 1 }, flagged_invoices: 4, flagged_amount: 1250000, amount: 4.1e6, blacklisted: 0, waiting: 4, max_risk: 50 },
    ],
    nodes: [
      { id: "v:VEND1044", kind: "vendor", ring: 1, label: "Mammen Inc", vendor_id: "VEND1044", category: "MRO", blacklisted: false, invoices: 21, amount: 4.1e6, flagged: 4, max_risk: 50, top_approver_share: 0.24 },
      { id: "a:Saksham Nagarajan", kind: "approver", ring: 1, label: "Saksham Nagarajan", role: "Manager", limit: 100000 },
    ],
    edges: [{ source: "a:Saksham Nagarajan", target: "v:VEND1044", ring: 1, kinds: ["unusual approvals"], invoices: 4, amount: 1250000, rules: { "2.1.1": 3, "4.1.1": 1 } }],
  },
  tests: {
    fdr: 0.01, repeated: 2, pairs_tested: 1152, pairs_with_findings: 13, pairs_significant: 1, approvers_tested: 34, hotspots: 0, min_q_pair: 0.008, min_q_approver: 0.87,
    role_rates: [{ role: "Director", invoices: 680, flagged: 46, rate: 0.0676 }, { role: "Manager", invoices: 2760, flagged: 144, rate: 0.0522 }],
  },
  identity: { vendors: 60, shared_pan: 0, shared_gstin: 0, another_vendors_gstin: 0, gstin_mismatches: 12, approvers: 17 },
  method: { concentration_share: 0.4, concentration_min: 10, repeated: 2, fdr: 0.01, limit_clause: "5.1.1", links: ["shared PAN", "shared GSTIN", "another vendor's GSTIN", "repeated findings", "above own limit", "approver hotspot", "concentrated approvals"] },
};

/** The same ledger where no link passes the tests: only the watch list and its leads. */
export const noRings: Rings = {
  ...rings, rings: [], total_rings: 0, pairs: [], total_pairs: 0, nodes: [], edges: [],
  tests: { ...rings.tests, pairs_significant: 0, min_q_pair: 0.041 },
};

export const queue = {
  total: 2,
  items: [
    { result_id: 7, invoice_id: "INV40237", vendor_id: "VEND1001", vendor_name: "Kurian LLC", invoice_date: "2025-04-03", amount: 694181.12, route: "escalate", risk_level: "CRITICAL", r0: 70, rc: 70, flag_count: 1, configuration: "C1", created_at: "2026-10-14", rules: ["5.1.1"] },
    { result_id: 8, invoice_id: "INV40666", vendor_id: "VEND1002", vendor_name: "Rajan Inc", invoice_date: "2025-04-14", amount: 180287.69, route: "escalate", risk_level: "HIGH", r0: 50, rc: 50, flag_count: 1, configuration: "C1", created_at: "2026-10-14", rules: ["2.1.1"] },
  ],
  rules: { "2.1.1": "Amount match", "5.1.1": "Approval limit" },
};

export const invoice: InvoiceDetail = {
  records: {
    invoice: { invoice_id: "INV40237", vendor_id: "VEND1001", invoice_number: "KUR/001", date: "2025-04-03", amount: 694181.12 },
    po: { po_id: "PO20001", amount: 694181.12 },
    grn: null,
    vendor: { vendor_id: "VEND1001", vendor_name: "Kurian LLC" },
    approvals: [{ log_id: "LOG1", approver_role: "Senior Manager", action_taken: "Approved" }],
  },
  history: { total: 1, items: [{ invoice_id: "INV40001", amount: 1000 }] },
  result: {
    result_id: 7, run_id: 1, route: "escalate", risk_level: "CRITICAL", r0: 70, rc: 70, workflow_status: "PENDING_REVIEW",
    configuration: "C1", model: null, policy_version: "2.5", created_at: "2026-10-14 10:00:00",
    pack: {
      invoice_id: "INV40237", vendor_id: "VEND1001", vendor_name: "Kurian LLC", policy_version: "2.5", configuration: "C1", model: null,
      route: "escalate", risk_level: "CRITICAL", count_based_risk: 70, weighted_risk: 70, threshold: 50,
      flags: [{
        clause: "5.1.1", title: "Approval limit", severity: "critical", source: "control", confidence: 1,
        evidence: [{ field: "invoice.amount", value: 694181.12 }], message: "Invoice amount exceeds the Senior Manager approval limit of 500000.",
        citation: { document: "Procurement_Audit_SOP_v2.5.pdf", page: 2 },
        revision: {
          clause: "5.1.1", kind: "reapprove", action: "Obtain approval from a Director (limit 2500000) before payment.",
          changes: [{ field: "approval.approver_role", from: "Senior Manager", to: "Director" }], amount_at_issue: null,
        },
      }],
      removed_by_challenger: [], review: null, recommended_action: "Escalated to a human reviewer.",
    },
    trail: [
      { seq: 1, stage: "extraction", actor: "code", detail: "records", prompt_tokens: null, completion_tokens: null, latency_ms: null },
      { seq: 2, stage: "controls", actor: "code", detail: "1 flags", prompt_tokens: null, completion_tokens: null, latency_ms: null },
    ],
  },
};

export const policy: PolicyOverview = {
  active: "2.5",
  versions: [
    { version: "2.5", policy_name: "Procurement & Vendor Auditing SOP", effective_date: "2025-04-01", active: true, adoption: null },
    { version: "2.6", policy_name: "Procurement & Vendor Auditing SOP", effective_date: "2026-04-01", active: false, adoption: null },
  ],
  rules: [{ rule: "2.1.1", title: "Amount match", severity: "high", kind: "control", params: { amount_tolerance_pct: 1 } }],
  documents: [{ file_name: "Procurement_Audit_SOP_v2.5.pdf", title: "SOP", version: "2.5", pages: 3, ingested_at: null, passages: 20, rules: 16 }],
  timeline: [{ version: "2.5", from: "2025-04-01", until: null, invoices: 1200, under_other_version: 0, unaudited: 0 }],
  under_other_version: 0,
  unaudited: 0,
};

export const preview: Preview = {
  upload_id: "0123456789abcdef", file: "Company_Policy_v3.06.pdf", title: "Company policy, version 3.06", version: "3.06", pages: 3,
  usable: true, problems: [],
  changes: [{ clause: "5.1.1", parameter: "approval_limits", from: { Manager: 100000, CFO: 10000000 }, to: { Manager: 50000, CFO: 10000000 } }],
};

const interval = (value: number) => ({ value, ci_low: value, ci_high: value });

export const results: Results = {
  benchmark: Object.fromEntries(
    ["bench_seed_101", "bench_seed_202", "bench_seed_303"].map((d) => [d, {
      n_invoices: 5000,
      metrics: {
        "C0-IF": { detection_recall: interval(0.577), detection_precision: interval(0.501), detection_f1: interval(0.536), fpr_ordinary: interval(0.044), fpr_hard_negative: interval(0.403) },
        "C0-SVM": { detection_recall: interval(0.464), detection_precision: interval(0.543), detection_f1: interval(0.498), fpr_ordinary: interval(0.025), fpr_hard_negative: interval(0.481) },
        C1: { detection_recall: interval(0.714), detection_precision: interval(1), detection_f1: interval(0.833), fpr_ordinary: interval(0), fpr_hard_negative: interval(0) },
      },
      per_class: { C1: { R1: interval(1), J1: interval(0) }, "C0-IF": { R1: interval(0.4) }, "C0-SVM": { R1: interval(1) } },
      construction_checks: {},
    }]),
  ),
  policy_swap: null,
  policy_change: {
    invoices: 40000, audits: 560000, audit_seconds: 13, produced: "2026-10-13",
    variants: [
      { version: "3.12", name: "Strict policy", change: "", parameters: 14, parameters_read_correctly: 14, rules: 16, rules_read_word_for_word: 16, affected: 12274,
        driven: { invoices: 40000, exact: 40000 }, frozen: { invoices: 40000, exact: 27726, stale_findings: 0, missed_exceptions: 12427, needless_escalations: 0, missed_escalations: 12012 } },
      { version: "3.14", name: "Version 2.6", change: "", parameters: 14, parameters_read_correctly: 14, rules: 16, rules_read_word_for_word: 16, affected: 302,
        driven: { invoices: 40000, exact: 40000 }, frozen: { invoices: 40000, exact: 39698, stale_findings: 302, missed_exceptions: 0, needless_escalations: 302, missed_escalations: 0 } },
    ],
  },
  scalability: {
    produced: "2026-10-13", logical_cpus: 12,
    by_workers: [
      { workers: 1, audits: 300000, seconds: 5.29, invoices_per_second: 56660, findings: 16840 },
      { workers: 8, audits: 300000, seconds: 1.74, invoices_per_second: 172226, findings: 16840 },
    ],
    by_size: [{ invoices: 5000, seconds: 0.089, invoices_per_second: 56117, microseconds_per_invoice: 17.8 }],
  },
  policy_reading: {
    produced: "2026-10-14", model: "qwen2.5:7b-ctx12k",
    total: { values: 84, right_verified: 56, right_held_back: 24, wrong_caught: 2, wrong_passed: 2, missing: 0, rules: 96, located: 92, right_passage: 92 },
    documents: [{ file: "memo_reference_v5.1.pdf", style: "memo", policy: "reference", counts: { values: 14, right_verified: 9, wrong_passed: 0, located: 16, rules: 16 }, usage: { seconds: 393 } }],
  },
  pilots: { "C3-demo": { model: "qwen2.5:7b-ctx12k", summary: { invoices: 6, invoices_flagged: 4, llm_calls: 18, prompt_tokens: 57767, failed_stages: 0, routes: { approve: 2, escalate: 4 } }, started: "", finished: "" } },
};

export const policyGraph: PolicyGraphData = {
  version: "2.5",
  versions: [
    { version: "2.5", policy_name: "Procurement & Vendor Auditing SOP", effective_date: "2025-04-01", is_active: true },
    { version: "2.6", policy_name: "Procurement & Vendor Auditing SOP", effective_date: "2026-04-01", is_active: false },
  ],
  nodes: [
    { id: "version:2.5", kind: "version", label: "v2.5", active: true, effective: "2025-04-01" },
    { id: "section:5.1", kind: "section", label: "5.1 Delegation of Authority" },
    { id: "clause:5.1.1", kind: "clause", label: "5.1.1", title: "Approval limit", severity: "critical", clause_kind: "control", findings: 20 },
    { id: "control:approval_limit", kind: "checker", label: "approval_limit() in controls.py", checker_kind: "control" },
    { id: "page:Procurement_Audit_SOP_v2.5.pdf:2", kind: "page", label: "Procurement_Audit_SOP_v2.5.pdf p.2", document: "Procurement_Audit_SOP_v2.5.pdf", page: 2 },
    { id: "param:5.1.1:approval_limits", kind: "parameter", label: "approval_limits", clause: "5.1.1", value: { Manager: 100000, Director: 2500000 } },
    { id: "role:Manager", kind: "role", label: "Manager", limit: 100000 },
    { id: "role:Director", kind: "role", label: "Director", limit: 2500000 },
    { id: "version:2.6", kind: "version", label: "v2.6", active: false, effective: "2026-04-01", other: true },
  ],
  edges: [
    { source: "version:2.5", target: "section:5.1", kind: "has section", label: "" },
    { source: "section:5.1", target: "clause:5.1.1", kind: "has rule", label: "" },
    { source: "clause:5.1.1", target: "control:approval_limit", kind: "checked by", label: "" },
    { source: "clause:5.1.1", target: "page:Procurement_Audit_SOP_v2.5.pdf:2", kind: "stated on", label: "" },
    { source: "clause:5.1.1", target: "param:5.1.1:approval_limits", kind: "sets", label: "" },
    { source: "param:5.1.1:approval_limits", target: "role:Manager", kind: "limit", label: "₹1,00,000" },
    { source: "param:5.1.1:approval_limits", target: "role:Director", kind: "limit", label: "₹25,00,000" },
    { source: "version:2.6", target: "param:5.1.1:approval_limits", kind: "changes", label: "100000 -> 150000" },
  ],
  counts: { version: 2, section: 1, clause: 1, checker: 1, page: 1, parameter: 1, role: 2 },
};

export const graphAnswer: GraphAnswer = {
  question: "Who has to approve an invoice of ₹30 lakh?",
  version: "2.5",
  recognised: { amounts: [3000000] },
  facts: [
    { text: "Under v2.5, ₹30,00,000 is above every approval limit (the highest is the Director's, ₹25,00,000): whoever approves it breaks rule 5.1.1.",
      kind: "routing", version: "2.5", clause: "5.1.1", source: "5.1 Delegation of Authority (Procurement_Audit_SOP_v2.5.pdf, page 2)", chunk_id: 65,
      data: { amount: 3000000, lowest: null } },
  ],
  passages: [{ chunk_id: 65, document: "Procurement_Audit_SOP_v2.5.pdf", version: "2.5", kind: "text", clause_id: null, section: "5.1 Delegation of Authority",
               page: 2, text: "Approver role Approval limit (INR) Manager 100,000 Director 2,500,000", score: 1,
               source: "5.1 Delegation of Authority (Procurement_Audit_SOP_v2.5.pdf, page 2)" }],
  nodes: ["version:2.5", "role:Director", "clause:5.1.1"],
};

export const system: SystemStatus = {
  store: { backend: "sqlite", ledger: "bench_seed_202" },
  policy_version: "2.5",
  kafka: { configured: true, connected: true, bootstrap: "127.0.0.1:9092", prefix: "demo" },
  model: { configured: true, name: "qwen2.5:7b", reachable: false, status: "does not answer", endpoint: "http://127.0.0.1:11435/v1" },
  embeddings: { configured: true, model: "nomic-embed-text", embedded: 3, passages: 3 },
};

export const streamStatus: StreamStatus = {
  configured: true,
  bootstrap: "127.0.0.1:9092",
  topics: [
    { kind: "invoice", topic: "demo.invoice", partitions: 6, messages: 500, processed: 200, lag: 300, outcomes: { audited: 180, duplicate: 20 } },
    { kind: "email", topic: "demo.email", partitions: 3, messages: 2105, processed: 2105, lag: 0, outcomes: { linked: 1900, unlinked: 205 } },
    { kind: "vendor", topic: "demo.vendor", partitions: 3, messages: 60, processed: 60, lag: 0, outcomes: { stored: 60 } },
    { kind: "compliance", topic: "demo.compliance", partitions: 1, messages: 0, processed: 0, lag: 0, outcomes: {} },
  ],
};

export const streamSources: StreamSources = {
  ledgers: [{ name: "bench_seed_202", invoices: 5000, vendors: 60 }],
  mailboxes: [{ name: "vendor_mail.mbox", bytes: 4_200_000 }],
  policies: [{ name: "Procurement_Audit_SOP_v2.6.pdf", bytes: 6_400 }],
};

const passage = (chunk_id: number, clause_id: string | null, section: string, text: string, ranks: [number, number, number], scores: [number, number, number]) => ({
  chunk_id, document: "Procurement_Audit_SOP_v2.5.pdf", version: "2.5", kind: clause_id ? "clause" : "text", clause_id, section, page: 2, text,
  lexical: scores[0], lexical_rank: ranks[0], dense: scores[1], dense_rank: ranks[1], hybrid: scores[2], hybrid_rank: ranks[2],
  point: [chunk_id / 100, 0.1, -0.2] as [number, number, number],
});

export const ragTrace: RagTrace = {
  question: "Who has to approve an invoice of ₹30 lakh?",
  mode: "hybrid", k: 5, rrf_k: 60, embedding_model: "nomic-embed-text", dense_error: null,
  recognised: { amounts: [3000000], clauses: [], topics: ["approval"] },
  facts: graphAnswer.facts,
  context: [
    { ...graphAnswer.passages[0], from: "graph" },
    { chunk_id: 12, document: "Procurement_Audit_SOP_v2.5.pdf", version: "2.5", kind: "clause", clause_id: "5.1.1", section: "5.1 Delegation of Authority", page: 2,
      text: "Every invoice is approved by a role whose limit covers its amount.", score: 0.03, source: "Rule 5.1.1 (Procurement_Audit_SOP_v2.5.pdf, page 2)", from: "retrieval" },
  ],
  passages: [
    passage(12, "5.1.1", "5.1 Delegation of Authority", "Every invoice is approved by a role whose limit covers its amount.", [1, 2, 1], [0.41, 0.78, 0.0325]),
    passage(65, null, "5.1 Delegation of Authority", "Approver role Approval limit (INR) Manager 100,000 Director 2,500,000", [2, 1, 2], [0.33, 0.81, 0.0323]),
    passage(30, "2.1.1", "2.1 Amounts", "The invoice amount matches the purchase order within the tolerance.", [3, 3, 3], [0.05, 0.52, 0.0317]),
  ],
  query_point: [0.2, 0.1, -0.1],
  explained: [0.21, 0.12, 0.08],
};

export const knowledge: KnowledgeLayer = {
  documents: [
    { doc_id: 1, file_name: "Procurement_Audit_SOP_v2.5.pdf", title: "SOP", version: "2.5", pages: 3, ingested_at: "2026-10-14 10:00:00", passages: 2 },
    { doc_id: 2, file_name: "Procurement_Audit_SOP_v2.6.pdf", title: "SOP", version: "2.6", pages: 3, ingested_at: "2026-10-14 10:00:00", passages: 1 },
  ],
  passages: [
    { chunk_id: 12, document: "Procurement_Audit_SOP_v2.5.pdf", version: "2.5", kind: "clause", clause_id: "5.1.1", section: "5.1 Delegation of Authority", page: 2,
      verified: true, text: "Every invoice is approved by a role whose limit covers its amount.", embed_model: "nomic-embed-text", point: [0.1, 0.2, 0.3] },
    { chunk_id: 65, document: "Procurement_Audit_SOP_v2.5.pdf", version: "2.5", kind: "text", clause_id: null, section: "5.1 Delegation of Authority", page: 2,
      verified: null, text: "Approver role Approval limit (INR) Manager 100,000 Director 2,500,000", embed_model: "nomic-embed-text", point: [0.2, 0.1, 0.0] },
    { chunk_id: 90, document: "Procurement_Audit_SOP_v2.6.pdf", version: "2.6", kind: "clause", clause_id: "5.1.1", section: "5.1 Delegation of Authority", page: 2,
      verified: false, text: "Every invoice is approved by a role whose limit covers its amount.", embed_model: null },
  ],
  explained: [0.3, 0.2, 0.1],
  embedding_model: "nomic-embed-text",
  registry: {
    "2.5": { "5.1.1": { title: "Approval limit", severity: "critical", kind: "control", params: { approval_limits: { Manager: 100000, Director: 2500000 } } } },
    "2.6": { "5.1.1": { title: "Approval limit", severity: "critical", kind: "control", params: { approval_limits: { Manager: 150000, Director: 2500000 } } } },
  },
  versions: [
    { version: "2.5", policy_name: "Procurement & Vendor Auditing SOP", effective_date: "2025-04-01", is_active: true },
    { version: "2.6", policy_name: "Procurement & Vendor Auditing SOP", effective_date: "2026-04-01", is_active: false },
  ],
};

export const aiLayer: AiLayer = {
  policy_version: "2.5",
  model: "qwen2.5:7b",
  agents: [
    { name: "math_approvals", title: "Math & Approvals", sections: ["2.1", "5"], judges: ["2.1.4", "2.1.5"], records: ["invoice", "po", "grn", "approvals"], history_rules: [] },
    { name: "tax_identity", title: "Tax & Identity", sections: ["2.2", "3"], judges: ["2.2.2"], records: ["invoice", "vendor"], history_rules: [] },
    { name: "vendor_intelligence", title: "Vendor Intelligence", sections: ["4"], judges: ["4.1.2"], records: ["vendor", "history"], history_rules: ["4.1.2"] },
  ],
  configurations: {
    C1: { controls: true, agents: "none", challenger: false, confidence: false, reruns: 0, temperature: 0, rerun_temperature: 0.7 },
    C5: { controls: true, agents: "specialists", challenger: true, confidence: true, reruns: 3, temperature: 0, rerun_temperature: 0.7 },
  },
  stages: [
    { stage: "controls", actor: "code", steps: 60, prompt_tokens: 0, completion_tokens: 0, mean_latency_ms: null, model_calls: 0 },
    { stage: "agent", actor: "math_approvals", steps: 5, prompt_tokens: 9000, completion_tokens: 1200, mean_latency_ms: 4100, model_calls: 5 },
  ],
  traced: [
    { invoice_id: "INV40237", configuration: "C5", route: "escalate", risk_level: "CRITICAL", rc: 70, flag_count: 1, llm_calls: 12, prompt_tokens: 21000,
      completion_tokens: 2400, latency_ms: 38000, created_at: "2026-10-14 10:00:01" },
  ],
};

// ------------------------------------------------------------------ the ledger graph
export const caseGraph: CaseGraphView = {
  focus: null,
  focus_kind: null,
  policy_version: "2.5",
  truncated: false,
  counts: { vendors: 250, invoices_with_findings: 291, rules: 16, approvers: 31, rings: 2, findings: 340 },
  nodes: [
    { id: "g:1", kind: "ring", label: "Ring 1", vendors: 2, approvers: 1, amount: 1.67e8, link_kinds: { "approver hotspot": 3 } },
    { id: "v:VEND1041", kind: "vendor", label: "Murty-Kari", category: "MRO", invoices: 40, flagged: 12, amount: 4.2e7, risk: 70, blacklisted: false },
    { id: "v:VEND1069", kind: "vendor", label: "Sharaf, Mohanty and Chowdhury", category: "Utilities", invoices: 31, flagged: 9, amount: 3.1e7, risk: 70, blacklisted: false },
    { id: "a:Meera Kapoor", kind: "approver", label: "Meera Kapoor", role: "Director", limit: 2500000, approvals: 291, flagged: 58, over_limit: 45, risk: 70 },
    { id: "r:5.1.1", kind: "rule", label: "5.1.1 Approval limit", severity: "critical", invoices: 601 },
  ],
  edges: [
    { source: "v:VEND1041", target: "g:1", kind: "member of" },
    { source: "v:VEND1069", target: "g:1", kind: "member of" },
    { source: "a:Meera Kapoor", target: "g:1", kind: "member of" },
    { source: "v:VEND1041", target: "r:5.1.1", kind: "breaks", count: 11 },
  ],
};

export const caseAnswer: CaseAnswer = {
  question: "Which approvers approved the most invoices above their own limit?",
  recognised: { approver_words: true },
  nodes: ["a:Meera Kapoor", "r:5.1.1"],
  facts: [
    {
      text: "Approvers with the most approvals above their own limit (rule 5.1.1): Meera Kapoor (Director, 45).",
      kind: "approvers", version: "2.5", clause: "5.1.1", source: null, chunk_id: null, data: {},
    },
  ],
};
