// Fixtures of the intelligence layer: the risk screen, counterfactuals, stories, the investigation, mail triage, the agent.
import type { AgentAnswer, EmailVerdict, Explanation, Investigation, InvoiceStory, MailTriage, ModelOverview, ScreenHead } from "../api/types";

const shapHead = (title: string, probability: number, raw: number): ScreenHead => ({
  title,
  probability,
  raw,
  base: -4.2,
  base_probability: 0.015,
  other: 0.05,
  check: 0,
  contributions: [
    { feature: "limit_ratio", meaning: "the amount divided by the approval limit", value: 1.388, shap: 4.75 },
    { feature: "below_limit_pct", meaning: "how far below the approver's limit", value: 100, shap: 2.51 },
    { feature: "desc_po_overlap", meaning: "word overlap with the PO", value: 1, shap: -0.41 },
  ],
});

export const explanation: Explanation = {
  invoice_id: "INV40237",
  policy_version: "2.5",
  screen: {
    suggested_rule: "4.1.2",
    values: { limit_ratio: 1.388 },
    heads: {
      any: shapHead("Anomalous (any rule)", 0.921, 2.65),
      "2.1.4": shapHead("Receipt remarks contradict the billed quantity", 0.001, -6.9),
      "2.1.5": shapHead("Invoice description does not match the PO", 0.002, -6.2),
      "2.2.2": shapHead("Near-duplicate invoice", 0.001, -6.9),
      "4.1.2": shapHead("Structuring across days", 0.004, -5.5),
    },
  },
  counterfactuals: [
    {
      clause: "5.1.1",
      title: "Approval limit",
      severity: "critical",
      message: "Invoice amount 694181.12 exceeds the Senior Manager approval limit of 500000.",
      margin: { value: 194181.12, unit: "rupees above the approver's limit", text: "₹694,181.12 against the Senior Manager limit of ₹500,000.00: ₹194,181.12 (38.8%) above it" },
      record: [{ change: "Approved by a Director (limit ₹2,500,000.00), the lowest role whose limit covers the amount", edit: { "approval.approver_role": "Director" }, clears: true, raises: [] }],
      policy: [{ change: "The Senior Manager limit of rule 5.1.1 raised from ₹500,000.00 to ₹694,182.00", parameter: "5.1.1.approval_limits.Senior Manager", from: 500000, to: 694182, clears: true, raises: [], also_clears: 37 }],
      no_parameter: false,
    },
  ],
};

export const story: InvoiceStory = {
  invoice_id: "INV40237",
  vendor_id: "VEND1001",
  audits: 1,
  state: "PENDING_REVIEW after 1 audit(s); the latest result is intact",
  steps: [
    { at: "2025-03-20", kind: "ledger", what: "Purchase order PO20001 for ₹694,181.12" },
    { at: "2025-04-03", kind: "ledger", what: "Invoice KUR/001 of ₹694,181.12 from Kurian LLC (VEND1001)" },
    { at: "2025-04-05 10:00:00", kind: "approval", what: "Approved by A. Rao (Senior Manager)" },
    { at: "2026-10-14 10:00:00", kind: "audit", result_id: 7, what: "Audited in run 1 (C1, policy v2.5): escalate, CRITICAL, score 70.0; findings 5.1.1 (critical)" },
  ],
};

export const modelOverview: ModelOverview = {
  trained: true,
  training: {
    ledger: "pilot_seed_909",
    policy_version: "2.5",
    invoices: 5000,
    scikit_learn: "1.6.1",
    params: { n_estimators: 150, max_depth: 3, learning_rate: 0.1 },
    heads: { any: { positives: 420, training_auc: 0.9997 } },
  },
  heads: {
    any: "Anomalous (any rule)",
    "2.1.4": "Receipt remarks contradict the billed quantity",
    "2.1.5": "Invoice description does not match the PO",
    "2.2.2": "Near-duplicate invoice",
    "4.1.2": "Structuring across days",
  },
  features: [{ feature: "limit_ratio", meaning: "the amount divided by the approval limit" }],
  invoices: 1200,
  scored: 1200,
  limited: false,
  importance: {
    any: {
      title: "Anomalous (any rule)",
      base: -4.2,
      rows: 3,
      features: [
        { feature: "gstin_mismatch", meaning: "the invoice GSTIN differs from the vendor master", mean_abs_shap: 0.219 },
        { feature: "limit_ratio", meaning: "amount over the limit", mean_abs_shap: 0.139 },
      ],
      points: [
        { feature: "gstin_mismatch", shap: [-0.2, 6.1, -0.2], rank: [0.2, 1, 0.2] },
        { feature: "limit_ratio", shap: [-0.4, 4.7, 0.1], rank: [0.1, 1, 0.5] },
      ],
    },
    "4.1.2": {
      title: "Structuring across days",
      base: -6,
      rows: 3,
      features: [{ feature: "window_total_ratio", meaning: "their total divided by the role's limit", mean_abs_shap: 0.8 }],
      points: [{ feature: "window_total_ratio", shap: [-0.5, 7.2, -0.5], rank: [0, 1, 0] }],
    },
  },
  distribution: {
    bins: 20,
    by_route: {
      approve: [1100, 20, 5, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 15],
      escalate: [0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 10, 50],
    },
  },
  paper_score: { "0": 1140, "50": 20, "70": 40 },
  above_half: { any: 65, judgement: 12 },
  second_opinion: [
    { invoice_id: "INV40127", route: "approve", suggested_rule: "4.1.2", rule_title: "Structuring across days", probability: 0.998, any: 0.97, vendor_name: "Purohit-Khosla", amount: 452956, date: "2025-04-09" },
  ],
  evaluation: {
    ledgers: ["bench_seed_101", "bench_seed_202"],
    heads: {
      any: { title: "Anomalous (any rule)", auc_mean: 0.9995, auc_min: 0.9992, auc_max: 0.9998, isolation_forest_auc_mean: 0.8531, recall_at_2pct_mean: 0.348 },
      "4.1.2": { title: "Structuring across days", auc_mean: 1, auc_min: 1, auc_max: 1, isolation_forest_auc_mean: 0.7284, recall_at_2pct_mean: 1 },
    },
    second_opinion_at_2pct: { found: 890, of: 1040, recall: 0.8558 },
    classification: { right: 985, of: 985, accuracy: 1 },
  },
};

export const investigation: Investigation = {
  verdict: "The audit record needs action: 1 check(s) failed, 1 need attention, 10 passed.",
  status: { fail: 1, attention: 1, pass: 10 },
  scope: {
    ledger: "small_seed_7",
    invoices: 1200,
    audited: 1200,
    results: 1201,
    runs: 2,
    decisions: 3,
    reviewers: 2,
    trail_entries: 3604,
    first: "2026-11-21 10:00:00",
    last: "2026-11-21 11:00:00",
    digest: "ab12cd",
    generated: "2026-11-21 12:00:00",
  },
  checks: [
    {
      key: "documentation",
      title: "Decisions with a written reason",
      standard: "ISA 230, paragraph 8",
      status: "fail",
      count: 1,
      summary: "2 of 3 decisions give a reason; 1 do not, 1 of them clearing a critical invoice",
      items: [{ where: "INV40237", invoice_id: "INV40237", result_id: 7, what: "Dev Malhotra approved it with the reason 'ok'" }],
      why: "A decision without its reason cannot be understood.",
      action: "Ask the reviewers to complete the reasons.",
    },
    {
      key: "overrides",
      title: "Critical findings cleared by a reviewer",
      standard: "ISA 240 (management override)",
      status: "attention",
      count: 1,
      summary: "1 invoices with a critical finding cleared; 0 reviewer-vendor pair(s) with 3 or more",
      items: [{ where: "INV40237", invoice_id: "INV40237", result_id: 7, what: "Dev Malhotra approved a critical invoice of VEND1001" }],
      why: "",
      action: "Have a second reviewer confirm.",
    },
    { key: "integrity", title: "The sealed record", standard: "ISA 230", status: "pass", count: 0, summary: "1,201 of 1,201 results match their seals", items: [], why: "", action: "" },
  ],
  timeline: {
    events: [
      { at: "2026-11-21 10:00:00", kind: "run", where: "run 1", what: "C1 under policy v2.5: 1,200 results, 420 with findings" },
      { at: "2026-11-21 23:59:59", kind: "review", where: "Dev Malhotra", what: "Dev Malhotra: 1 approve decision(s) on 2026-11-21" },
    ],
    total: 2,
    by_kind: { run: 1, review: 1 },
  },
  reviewers: [{ reviewer: "Dev Malhotra", decisions: 1, approve: 1, reject: 0, override: 0, critical_cleared: 1, without_reason: 1 }],
  markdown: "# Investigation of the audit record\n\n**The audit record needs action.**\n",
};

const verdict = (risk: EmailVerdict["risk"], sender: string, invoiceId: string): EmailVerdict => ({
  message_id: `<${sender}>`,
  sent_at: "2026-01-30 14:13:00",
  sender,
  sender_domain: sender.split("@")[1],
  subject: `URGENT: new bank account for invoice ${invoiceId}`,
  invoice_id: invoiceId,
  vendor_id: "VEND1104",
  category: "bank_change",
  scores: { bank_change: 6 },
  signals: { lookalike_domain: risk === "high", new_domain: risk === "high", urgency: risk === "high", secrecy: risk === "high", account_change: true, money_at_risk: true, addresses_a_model: false },
  risk,
  reasons:
    risk === "high"
      ? ["sent from chatterjeeravals.example, which reads like the vendor's domain but is not it", "asks to pay into another bank account"]
      : ["asks to pay into another bank account"],
  action:
    risk === "high"
      ? "Hold the payment; confirm the request by telephone with the contact on the vendor master, never with details from the e-mail"
      : "Confirm with the vendor's registered contact before changing the vendor master",
});

export const mailTriage: MailTriage = {
  emails: 2104,
  linked: 2104,
  by_category: { bank_change: 19, payment_reminder: 297, quantity_query: 30, invoice_submission: 1758, other: 0 },
  by_risk: { high: 1, medium: 1, low: 0, none: 2102 },
  signals: { lookalike_domain: 1, new_domain: 1, urgency: 1, secrecy: 1, account_change: 19, money_at_risk: 2104, addresses_a_model: 0 },
  alerts: [verdict("high", "finance@chatterjeeravals.example", "INV44193"), verdict("medium", "accounts@kallasavant.example", "INV44176")],
  alerts_total: 2,
  holds: [
    { invoice_id: "INV44193", vendor_id: "VEND1104", amount: 184575.05, message_id: "<finance@chatterjeeravals.example>", sender: "finance@chatterjeeravals.example", subject: "URGENT: new bank account for invoice INV44193" },
  ],
  hold_amount: 184575.05,
  titles: { bank_change: "Bank-detail change", payment_reminder: "Payment reminder", quantity_query: "Quantity query", invoice_submission: "Invoice submission", other: "Other" },
  recent: [],
};

/** A high-risk verdict on an e-mail that names INV40237, the invoice of the invoice fixtures. */
export const highRiskMail: EmailVerdict = { ...verdict("high", "finance@kurian-accounts.example", "INV40237"), message_id: "<a1@kurian.example>" };

export const agentAnswer: AgentAnswer = {
  question: "Which role must approve an invoice of Rs 3,50,000?",
  mode: "rules",
  steps: [
    { n: 1, tool: "approval_rule", args: { amount: 350000 }, summary: "Under policy v2.5, rule 5.1.1, an invoice of ₹3,50,000 needs a Senior Manager (limit ₹5,00,000).", refs: ["5.1.1"], ms: 0.8 },
  ],
  answer: "Under policy v2.5, rule 5.1.1, an invoice of ₹3,50,000 needs a Senior Manager (limit ₹5,00,000); see INV40237 for a case. [T1]",
  citations: ["T1"],
  unverified_numbers: [],
  model: null,
};
