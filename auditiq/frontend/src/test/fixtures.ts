// Responses of the API used by the page tests, shaped as auditiq/api.py returns them.
import type { Health, InvoiceDetail, Overview, PolicyOverview, Preview, Results } from "../api/types";

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
};

export const queue = {
  total: 2,
  items: [
    { result_id: 7, invoice_id: "INV40237", vendor_id: "VEND1001", vendor_name: "Kurian LLC", invoice_date: "2025-04-03", amount: 694181.12, route: "escalate", risk_level: "CRITICAL", r0: 70, rc: 70, flag_count: 1, configuration: "C1", created_at: "2026-10-14" },
    { result_id: 8, invoice_id: "INV40666", vendor_id: "VEND1002", vendor_name: "Rajan Inc", invoice_date: "2025-04-14", amount: 180287.69, route: "escalate", risk_level: "HIGH", r0: 50, rc: 50, flag_count: 1, configuration: "C1", created_at: "2026-10-14" },
  ],
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
  results_under_other_versions: 0,
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
