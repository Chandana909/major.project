import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactElement } from "react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, describe, expect, it } from "vitest";
import { getToken, setToken } from "../api/client";
import { App } from "../App";
import { Layout } from "../components/Layout";
import {
  aiLayer, analytics, caseAnswer, caseGraph, graphAnswer, health, invoice, knowledge, noRings, overview, policy, policyGraph, preview, queue, ragTrace, results, rings, streamSources,
  streamStatus, system,
} from "../test/fixtures";
import { error, mockApi } from "../test/mockApi";
import { InvoicePage } from "./InvoicePage";
import { AiLayerPage } from "./AiLayerPage";
import { AnalyticsPage } from "./AnalyticsPage";
import { GraphPage } from "./GraphPage";
import { KafkaPage } from "./KafkaPage";
import { KnowledgePage } from "./KnowledgePage";
import { OverviewPage } from "./OverviewPage";
import { PipelinePage } from "./PipelinePage";
import { PolicyPage } from "./PolicyPage";
import { RagPage } from "./RagPage";
import { ResultsPage } from "./ResultsPage";
import { ReviewPage } from "./ReviewPage";
import { RingsPage } from "./RingsPage";

function renderAt(path: string, pattern: string, element: ReactElement) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route path={pattern} element={element} />
      </Routes>
    </MemoryRouter>,
  );
}

const kpi = (label: string) => screen.getByText(label, { selector: ".kpi-label" }).closest(".kpi") as HTMLElement;

afterEach(() => setToken(null));

describe("the overview", () => {
  it("shows the state of the audit and falls back from the 3D view without WebGL", async () => {
    mockApi([
      ["/api/overview", () => overview],
      ["/api/risk-map", () => ({ vendors: [{ vendor_id: "VEND1001", vendor_name: "Kurian LLC", category: "MRO", invoices: 20, amount: 1, waiting: 3, findings: 3, max_risk: 70, blacklisted: 0 }] })],
      ["/api/analytics", () => analytics],
      ["/api/queue", () => queue],
    ]);
    renderAt("/", "/", <OverviewPage />);
    expect(await screen.findByText("Invoices in the ledger")).toBeInTheDocument();
    expect(within(kpi("Invoices in the ledger")).getByText("1,200")).toBeInTheDocument();
    expect(within(kpi("Waiting for review")).getByText("40")).toBeInTheDocument();
    expect(within(kpi("Audited")).getByText("5% of the ledger")).toBeInTheDocument();
    expect(await screen.findByRole("note")).toHaveTextContent("needs WebGL");
    expect(screen.getAllByRole("link", { name: "Kurian LLC" })[0]).toHaveAttribute("href", "/invoice?q=Kurian%20LLC");
    expect(screen.getByText("Approval limit")).toBeInTheDocument();
    // The signals, counted from the findings by rule.
    expect(within(kpi("Approval & vendor")).getByText("20")).toBeInTheDocument();
    expect(within(kpi("Three-way match")).getByText("20")).toBeInTheDocument();
    expect(within(kpi("Duplicates")).getByText("0")).toBeInTheDocument();
    // The coverage says what was not checked, and how the results compare with the answer key.
    expect(screen.getByText(/55 of 60 invoices were audited without the language-model agents/)).toBeInTheDocument();
    expect(screen.getByText(/4 invoices have a finding but were approved/)).toBeInTheDocument();
    expect(screen.getByText(/2 invoices were flagged that the answer key marks as clean/)).toBeInTheDocument();
    expect(screen.getByRole("cell", { name: "0.500" })).toBeInTheDocument();                // the precision of C5
    // The trail and the queue.
    expect(await screen.findByText("count-based 70.0, weighted 70.0, route escalate")).toBeInTheDocument();
    expect(await screen.findByRole("heading", { name: "Escalation queue" })).toBeInTheDocument();
    expect(await screen.findByRole("img", { name: /Invoices per month over 2 months/ })).toBeInTheDocument();
  });

  it("does not score results produced under another policy against the answer key", async () => {
    const key = { ...overview.coverage!.answer_key!, found: 0, false_alarms: 0, missed: 0, not_checked: 0, passed: 0, other_policy: 60, by_configuration: {} };
    mockApi([
      ["/api/overview", () => ({ ...overview, coverage: { ...overview.coverage!, answer_key: key } })],
      ["/api/risk-map", () => ({ vendors: [] })],
      ["/api/analytics", () => analytics],
      ["/api/queue", () => queue],
    ]);
    renderAt("/", "/", <OverviewPage />);
    expect(await screen.findByText(/describes policy v2\.5, and all 60 latest results were produced under another version/)).toBeInTheDocument();
    expect(screen.queryByRole("columnheader", { name: "False alarms" })).not.toBeInTheDocument();
  });

  it("says what went wrong when the API fails, and retries", async () => {
    let fail = true;
    mockApi([
      ["/api/overview", () => (fail ? error(503, "The database cannot be reached: connection refused") : overview)],
      ["/api/risk-map", () => ({ vendors: [] })],
      ["/api/analytics", () => analytics],
      ["/api/queue", () => queue],
    ]);
    renderAt("/", "/", <OverviewPage />);
    expect(await screen.findByRole("alert")).toHaveTextContent("The database cannot be reached");
    fail = false;
    await userEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(await screen.findByText("Invoices in the ledger")).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("loads a ledger only after the replacement is confirmed, then audits it", async () => {
    let sent: FormData | null = null;
    const done = (result: unknown) => ({ id: "job1", kind: "k", status: "done", done: 1, total: 1, result, error: null, seconds: 1 });
    mockApi([
      ["/api/ledger", (_url, init) => {
        sent = init?.body as FormData;
        return done({ loaded: true, ledger: "new_ledger", problems: [], counts: { invoices: 1200, vendor_master: 60 } });
      }],
      ["/api/policy/apply", () => done({ invoices: 1200, flags: 420, states: { PENDING_REVIEW: 400 } })],
      ["/api/overview", () => overview],
      ["/api/risk-map", () => ({ vendors: [] })],
    ]);
    renderAt("/", "/", <OverviewPage />);
    await userEvent.upload(await screen.findByLabelText("Ledger file"), new File(["PK"], "new ledger.xlsx"));
    const load = screen.getByRole("button", { name: "Load the ledger" });
    expect(load).toBeDisabled();
    await userEvent.click(screen.getByLabelText(/Replace the current ledger/));
    await userEvent.click(load);
    expect(await screen.findByText(/1,200 invoices from 60 vendors/)).toBeInTheDocument();
    expect(sent!.get("replace")).toBe("true");
    expect((sent!.get("file") as File).name).toBe("new ledger.xlsx");

    await userEvent.click(screen.getByRole("button", { name: "Audit it with the controls" }));
    expect(await screen.findByText("1,200 invoices audited with the controls: 420 findings, 400 waiting for review.")).toBeInTheDocument();
  });

  it("lists the problems of a ledger that cannot be loaded", async () => {
    mockApi([
      ["/api/ledger", () => ({ id: "job2", kind: "load-ledger", status: "done", done: 0, total: 0, error: null, seconds: 1,
                              result: { loaded: false, ledger: "broken", problems: ["the table vendor_master is missing"], counts: {} } })],
      ["/api/overview", () => overview],
      ["/api/risk-map", () => ({ vendors: [] })],
    ]);
    renderAt("/", "/", <OverviewPage />);
    await userEvent.upload(await screen.findByLabelText("Ledger file"), new File(["PK"], "broken.zip"));
    await userEvent.click(screen.getByLabelText(/Replace the current ledger/));
    await userEvent.click(screen.getByRole("button", { name: "Load the ledger" }));
    expect(await screen.findByText("the table vendor_master is missing")).toBeInTheDocument();
    expect(screen.getByText(/nothing was replaced/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Audit it with the controls" })).not.toBeInTheDocument();
  });
});

describe("the review queue", () => {
  it("says what share of the audit waits for a person", async () => {
    mockApi([["/api/queue", () => queue], ["/api/overview", () => overview]]);
    renderAt("/review", "/review", <ReviewPage />);
    expect(await screen.findByLabelText("Share of the audit")).toHaveTextContent(
      "40 of the 60 audited invoices (66.7%) wait for a person; 20 were approved automatically, 4 of them with a medium or low finding recorded on the invoice.");
  });

  it("counts the whole queue per level and reads a level from the server", async () => {
    const levels = { CRITICAL: { invoices: 2142, amount: 9.1e8 }, HIGH: { invoices: 3570, amount: 4.2e8 } };
    const { calls } = mockApi([["/api/queue", (url) => (url.includes("level=HIGH")
      ? { ...queue, total: 3570, items: queue.items.filter((i) => i.risk_level === "HIGH"), levels }
      : { ...queue, total: 5712, items: queue.items.filter((i) => i.risk_level === "CRITICAL"), levels })]]);
    renderAt("/review", "/review", <ReviewPage />);
    expect(await screen.findByText("5,712 invoices are waiting for a reviewer, highest weighted risk first.")).toBeInTheDocument();
    const strip = screen.getByRole("group", { name: "Filter by risk level" });
    expect(within(strip).getByRole("button", { name: /High\s*3,570/ })).toBeEnabled();      // from the whole queue, not the list
    expect(screen.getByText(/the riskiest 1 of the 5,712 invoices waiting/)).toBeInTheDocument();
    await userEvent.click(within(strip).getByRole("button", { name: /High\s*3,570/ }));
    expect(await screen.findByText("INV40666")).toBeInTheDocument();
    expect(calls.some((c) => c.url.includes("/api/queue?limit=2000&level=HIGH"))).toBe(true);
  });

  it("filters by text and by risk level", async () => {
    mockApi([["/api/queue", () => queue]]);
    renderAt("/review", "/review", <ReviewPage />);
    expect(await screen.findByText("INV40237")).toBeInTheDocument();
    expect(screen.getByText("INV40666")).toBeInTheDocument();
    expect(screen.getByText("2 invoices are waiting for a reviewer, highest weighted risk first.")).toBeInTheDocument();

    await userEvent.selectOptions(screen.getByLabelText("Risk level"), "HIGH");
    expect(screen.queryByText("INV40237")).not.toBeInTheDocument();
    expect(screen.getByText("INV40666")).toBeInTheDocument();

    await userEvent.selectOptions(screen.getByLabelText("Risk level"), "all");
    await userEvent.type(screen.getByLabelText("Filter the queue"), "kurian");
    expect(screen.getByText("INV40237")).toBeInTheDocument();
    expect(screen.queryByText("INV40666")).not.toBeInTheDocument();

    await userEvent.clear(screen.getByLabelText("Filter the queue"));
    await userEvent.type(screen.getByLabelText("Filter the queue"), "nobody");
    expect(screen.getByText("No invoice matches the filter.")).toBeInTheDocument();
  });
});

describe("an invoice", () => {
  function mockInvoice() {
    let reads = 0;
    let decided: unknown = null;
    const mock = mockApi([
      ["/api/results/7/decision", (_url, init) => {
        decided = JSON.parse(String(init?.body));
        return { result_id: 7, invoice_id: "INV40237", workflow_status: "REVIEW_APPROVED" };
      }],
      ["/api/invoices/INV40237", () => {
        reads += 1;
        return invoice;
      }],
      ["/api/health", () => health],
    ]);
    return { ...mock, reads: () => reads, decided: () => decided };
  }

  it("shows the finding with its evidence and its citation, and the audit trail", async () => {
    mockInvoice();
    renderAt("/invoice/INV40237", "/invoice/:id", <InvoicePage />);
    expect(await screen.findByText("Rule 5.1.1")).toBeInTheDocument();
    expect(screen.getByText("Invoice amount exceeds the Senior Manager approval limit of 500000.")).toBeInTheDocument();
    expect(screen.getByText("Procurement_Audit_SOP_v2.5.pdf, page 2")).toBeInTheDocument();
    expect(screen.getByText("Revision · reapprove")).toBeInTheDocument();
    expect(screen.getByText("Obtain approval from a Director (limit 2500000) before payment.")).toBeInTheDocument();
    expect(screen.getByText("invoice.amount")).toBeInTheDocument();
    expect(screen.getByText("1 flags")).toBeInTheDocument();
    // Without a model only C1 can be run again.
    expect(within(screen.getByLabelText("Configuration")).getAllByRole("option").map((o) => o.textContent)).toEqual(["C1"]);
    await userEvent.click(screen.getByRole("tab", { name: "Purchase order" }));
    expect(screen.getByText("PO20001")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("tab", { name: "Goods receipt" }));
    expect(screen.getByText("No goods receipt on record.")).toBeInTheDocument();
  });

  it("refuses a decision without a reviewer, and an override without a justification", async () => {
    const mock = mockInvoice();
    renderAt("/invoice/INV40237", "/invoice/:id", <InvoicePage />);
    const form = await screen.findByRole("form", { name: "Review decision" });
    await userEvent.click(within(form).getByRole("button", { name: "Record decision" }));
    expect(within(form).getByRole("alert")).toHaveTextContent("Enter your name");

    await userEvent.type(within(form).getByPlaceholderText("Your name"), "A. Auditor");
    await userEvent.click(within(form).getByLabelText(/Override/));
    await userEvent.click(within(form).getByRole("button", { name: "Record decision" }));
    expect(within(form).getByRole("alert")).toHaveTextContent("An override needs a written justification.");
    expect(mock.decided()).toBeNull();
  });

  it("records a decision with the reviewer's name and reloads the invoice", async () => {
    const mock = mockInvoice();
    renderAt("/invoice/INV40237", "/invoice/:id", <InvoicePage />);
    const form = await screen.findByRole("form", { name: "Review decision" });
    await userEvent.click(within(form).getByLabelText(/Reject/));
    await userEvent.type(within(form).getByPlaceholderText("Your name"), "  A. Auditor ");
    await userEvent.type(within(form).getByPlaceholderText("Why, in a sentence or two"), "No goods receipt.");
    await userEvent.click(within(form).getByRole("button", { name: "Record decision" }));
    await waitFor(() => expect(mock.decided()).toEqual({ decision: "reject", reviewer: "A. Auditor", justification: "No goods receipt." }));
    await waitFor(() => expect(mock.reads()).toBe(2));
  });
});

describe("an invoice's vendor e-mails", () => {
  it("lists the e-mails that name the invoice, with their text on demand", async () => {
    const mail = { message_id: "<a1@kurian.example>", sender: "accounts@kurian.example", subject: "Invoice KUR/001 for PO20001", sent_at: "2025-04-03 10:15:00", body: "Please find our invoice KUR/001." };
    mockApi([
      ["/api/invoices/INV40237", () => ({ ...invoice, emails: [mail] })],
      ["/api/health", () => health],
    ]);
    renderAt("/invoice/INV40237", "/invoice/:id", <InvoicePage />);
    expect(await screen.findByText("Vendor e-mails (1)")).toBeInTheDocument();
    expect(screen.getByText("Invoice KUR/001 for PO20001")).toBeInTheDocument();
    expect(screen.getByText("accounts@kurian.example · 2025-04-03 10:15:00")).toBeInTheDocument();
  });
});

describe("the pipeline page", () => {
  const pipeline = { stages: [{ id: "controls", label: "Deterministic controls", kind: "code" }], configurations: { C1: ["controls"], C2: [], C3: [], C4: [], C5: ["controls"] } };

  it("shows how far the workers have got in each Kafka topic", async () => {
    mockApi([
      ["/api/pipeline", () => pipeline],
      ["/api/stream", () => ({ configured: true, bootstrap: "127.0.0.1:9092", topics: [
        { kind: "invoice", topic: "auditiq.invoice", partitions: 4, messages: 5000, processed: 4800, lag: 200, outcomes: { audited: 4800 } },
        { kind: "email", topic: "auditiq.email", partitions: 4, messages: 2105, processed: 2105, lag: 0, outcomes: { stored: 2105 } },
      ] })],
    ]);
    renderAt("/pipeline", "/pipeline", <PipelinePage />);
    expect(await screen.findByText("auditiq.invoice", { selector: ".kpi-label" })).toBeInTheDocument();
    expect(within(kpi("auditiq.invoice")).getByText("4,800")).toBeInTheDocument();
    expect(within(kpi("auditiq.invoice")).getByText(/4 partitions · lag 200/)).toBeInTheDocument();
    expect(kpi("auditiq.invoice")).toHaveClass("kpi-warn");
    expect(kpi("auditiq.email")).toHaveClass("kpi-good");
  });

  it("says how to start a broker when none is configured", async () => {
    mockApi([
      ["/api/pipeline", () => pipeline],
      ["/api/stream", () => ({ configured: false, topics: [] })],
    ]);
    renderAt("/pipeline", "/pipeline", <PipelinePage />);
    expect(await screen.findByText(/No broker is configured/)).toBeInTheDocument();
    expect(screen.getByText("python scripts/kafka_local.py start")).toBeInTheDocument();
  });
});

describe("the architecture diagram", () => {
  const pipeline = {
    stages: [
      { id: "extraction", label: "Evidence extraction", kind: "code" },
      { id: "controls", label: "Deterministic controls", kind: "code", feature: true },
      { id: "math_approvals", label: "Math & Approvals agent", kind: "llm" },
      { id: "risk_score", label: "Risk score & route", kind: "code" },
    ],
    configurations: { C1: ["extraction", "controls", "risk_score"], C2: ["extraction", "risk_score"], C3: ["extraction", "controls", "math_approvals", "risk_score"], C4: [], C5: [] },
  };

  it("explains a component, shows live figures and dims what a configuration does not run", async () => {
    mockApi([
      ["/api/pipeline", () => pipeline],
      ["/api/stream", () => ({ configured: false, topics: [] })],
      ["/api/overview", () => overview],
      ["/api/health", () => health],
      ["/api/policy/graph/ask", () => graphAnswer],
      ["/api/policy/graph", () => policyGraph],
      ["/api/policy", () => policy],
    ]);
    renderAt("/pipeline", "/pipeline", <PipelinePage />);
    const controls = await screen.findByRole("button", { name: /^Deterministic controls:/ });
    expect(await within(controls).findByText("40 findings")).toBeInTheDocument();           // live: both rules of the overview are controls
    await userEvent.click(controls);
    const about = screen.getByRole("region", { name: "About Deterministic controls" });
    expect(within(about).getByText("auditiq/controls.py")).toBeInTheDocument();
    expect(within(about).getByText(/Clause registry/)).toBeInTheDocument();               // one of its connections
    const agent = screen.getByRole("button", { name: /^Math & Approvals:/ });
    expect(agent).toHaveClass("dim");                                                       // not connected to the selection
    await userEvent.click(controls);                                                        // deselect
    expect(screen.queryByRole("region", { name: "About Deterministic controls" })).not.toBeInTheDocument();
    await userEvent.unhover(controls);
    expect(agent).not.toHaveClass("dim");
    await userEvent.click(within(screen.getByRole("tablist", { name: "Highlight a configuration" })).getByRole("tab", { name: "C1" }));
    expect(agent).toHaveClass("dim");
    expect(screen.getByRole("button", { name: /^Deterministic controls:/ })).not.toHaveClass("dim");
    expect(within(kpi("Rules in the policy")).getByText(String(policy.rules.length))).toBeInTheDocument();
  });
});

describe("the policy knowledge graph", () => {
  it("answers a question with facts and shows every relation", async () => {
    const { calls } = mockApi([
      ["/api/policy/graph/ask", () => graphAnswer],
      ["/api/policy/graph", () => policyGraph],
      ["/api/policy", () => policy],
      ["/api/health", () => health],
    ]);
    renderAt("/graph", "/graph", <GraphPage />);
    expect(await screen.findByRole("heading", { name: "Policy knowledge graph" })).toBeInTheDocument();
    expect(within(kpi("Relations")).getByText("8")).toBeInTheDocument();
    const table = screen.getByRole("table", { name: "Relations of the policy graph" });
    expect(within(table).getByRole("row", { name: /approval_limits of 5\.1\.1 limit Manager ₹1,00,000/ })).toBeInTheDocument();
    expect(within(table).getByRole("row", { name: /v2\.6 changes approval_limits of 5\.1\.1 100000 -> 150000/ })).toBeInTheDocument();
    await userEvent.type(screen.getByLabelText("Question for the graph"), "Who has to approve an invoice of ₹30 lakh?");
    await userEvent.click(screen.getByRole("button", { name: "Ask the graph" }));
    expect(await screen.findByText(/above every approval limit/)).toBeInTheDocument();
    expect(screen.getAllByText("5.1 Delegation of Authority (Procurement_Audit_SOP_v2.5.pdf, page 2)").length).toBeGreaterThan(0);
    expect(calls.some((c) => c.url.includes("/api/policy/graph/ask?q=Who%20has%20to%20approve"))).toBe(true);
    expect((await screen.findAllByRole("note")).some((n) => n.textContent?.includes("needs WebGL"))).toBe(true);
  });
});

describe("the audit findings graph", () => {
  it("shows what the audit found as a graph and answers a question from it", async () => {
    const { calls } = mockApi([
      ["/api/case-graph/ask", () => caseAnswer],
      ["/api/case-graph", () => caseGraph],
      ["/api/policy/graph", () => policyGraph],
      ["/api/policy", () => policy],
      ["/api/health", () => health],
    ]);
    renderAt("/graph", "/graph", <GraphPage />);
    await userEvent.click(await screen.findByRole("tab", { name: "Audit findings graph" }));
    expect(await screen.findByRole("heading", { name: "Audit knowledge graph" })).toBeInTheDocument();
    expect(within(kpi("Invoices with findings")).getByText("291")).toBeInTheDocument();
    expect(within(kpi("Rings")).getByText("2")).toBeInTheDocument();
    const table = screen.getByRole("table", { name: "Relations of the ledger graph" });
    expect(within(table).getByRole("row", { name: /Murty-Kari breaks ×11 5\.1\.1 Approval limit/ })).toBeInTheDocument();
    await userEvent.type(screen.getByLabelText("Question for the ledger graph"), caseAnswer.question);
    await userEvent.click(screen.getByRole("button", { name: "Ask the graph" }));
    expect(await screen.findByText(/Meera Kapoor \(Director, 45\)/)).toBeInTheDocument();
    expect(calls.some((c) => c.url.includes("/api/case-graph/ask?q=Which%20approvers"))).toBe(true);
    await userEvent.type(screen.getByLabelText("Open a node of the ledger graph"), "Frado Deep");
    await userEvent.click(screen.getByRole("button", { name: "Open" }));
    await waitFor(() => expect(calls.some((c) => c.url.includes("/api/case-graph?focus=Frado%20Deep"))).toBe(true));
  });
});

describe("the analytics page", () => {
  it("shows the forensic tests of the ledger", async () => {
    mockApi([["/api/analytics", () => analytics], ["/api/policy", () => policy]]);
    renderAt("/analytics", "/analytics", <AnalyticsPage />);
    expect(await screen.findByRole("heading", { name: "Forensic analytics" })).toBeInTheDocument();
    expect(within(kpi("Benford, first digit")).getByText("nonconformity")).toBeInTheDocument();
    expect(within(kpi("Just under a limit")).getByText("96")).toBeInTheDocument();
    expect(screen.getByText("3.10×")).toBeInTheDocument();                                  // 96 under against 31 over the Manager limit
    expect(screen.getByRole("cell", { name: "Janya Biswas" })).toBeInTheDocument();
    expect(screen.getByText("9", { selector: "dd" })).toBeInTheDocument();                  // the digit that differs
    await userEvent.click(screen.getByRole("tab", { name: "First two digits" }));
    expect(screen.getByText("close conformity", { selector: ".conformity" })).toBeInTheDocument();
    expect(screen.getByText("49", { selector: "dd" })).toBeInTheDocument();
    expect(await screen.findByRole("note")).toHaveTextContent("needs WebGL");              // the skyline without WebGL
  });
});

describe("the collusion rings page", () => {
  it("lists the rings and opens one", async () => {
    mockApi([["/api/rings", () => rings]]);
    renderAt("/rings", "/rings", <RingsPage />);
    expect(await screen.findByRole("heading", { name: "Vendor collusion rings" })).toBeInTheDocument();
    expect(within(kpi("Rings")).getByText("1")).toBeInTheDocument();
    expect(within(kpi("GSTIN mismatches")).getByText("12")).toBeInTheDocument();
    expect(screen.getByRole("cell", { name: "Shah Traders" })).toBeInTheDocument();
    expect(screen.getByText(/at least 40% of at least 10 invoices/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: /R1/ }));
    const ring = (await screen.findByRole("heading", { name: "Ring R1" })).closest("section") as HTMLElement;
    const links = within(ring).getAllByRole("row").filter((r) => within(r).queryByText("Janya Biswas") && within(r).queryByText("Kurian LLC"));
    expect(links).toHaveLength(1);
    expect(screen.getByRole("cell", { name: "₹25,00,000" })).toBeInTheDocument();         // the approver's own limit
  });

  it("says when no ring passes the tests and shows the leads instead", async () => {
    mockApi([["/api/rings", () => noRings]]);
    renderAt("/rings", "/rings", <RingsPage />);
    expect(await screen.findByText("No ring passes the tests.")).toBeInTheDocument();
    expect(within(kpi("Rings")).getByText("0")).toBeInTheDocument();
    expect(within(kpi("Pairs tested")).getByText("1,152")).toBeInTheDocument();
    expect(screen.getByRole("cell", { name: "4 of 5" })).toBeInTheDocument();             // the most unusual pair
    expect(screen.getByRole("cell", { name: "0.041" })).toBeInTheDocument();              // its q-value, above 0.01
    expect(screen.getByRole("cell", { name: "5.2%" })).toBeInTheDocument();               // the rate of Managers
    await userEvent.click(screen.getByRole("button", { name: /L1/ }));
    expect(await screen.findByRole("heading", { name: "Lead L1" })).toBeInTheDocument();
  });
});

describe("the policy page", () => {
  it("previews the thresholds of an uploaded document and adopts it", async () => {
    let adopted: unknown = null;
    mockApi([
      ["/api/policy/preview", () => preview],
      ["/api/policy/adopt", (_url, init) => {
        adopted = JSON.parse(String(init?.body));
        return { version: "3.06", adopted: true, active: true };
      }],
      ["/api/policy/graph/ask", () => graphAnswer],
      ["/api/policy/graph", () => policyGraph],
      ["/api/policy", () => policy],
      ["/api/health", () => health],
    ]);
    renderAt("/policy", "/policy", <PolicyPage />);
    expect(await screen.findByText("Amount match")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Make active" })).toBeInTheDocument();   // only for the inactive v2.6

    await userEvent.upload(screen.getByLabelText("Policy PDF"), new File(["%PDF-1.4"], "Company_Policy_v3.06.pdf", { type: "application/pdf" }));
    const row = (await screen.findByText("approval_limits: Manager")).closest("tr") as HTMLElement;
    expect(within(row).getByText("100000")).toBeInTheDocument();
    expect(within(row).getByText("50000")).toBeInTheDocument();
    expect(screen.queryByText("approval_limits: CFO")).not.toBeInTheDocument();   // unchanged limits are not listed

    await userEvent.click(screen.getByRole("button", { name: "Adopt version 3.06" }));
    expect(await screen.findByText("Policy version 3.06 adopted from Company_Policy_v3.06.pdf and made active.")).toBeInTheDocument();
    expect(adopted).toEqual({ upload_id: "0123456789abcdef", activate: true, replace: false });
  });

  it("simulates a document on the ledger before it is adopted", async () => {
    const impact = {
      active_version: "2.5", new_version: "3.06", baseline: { "2.5": 20000 }, effective_date: "2026-04-01", governs_if_adopted: 0,
      invoices: 20000, decisions_moved: 1540, newly_flagged: 1540, cleared: 0,
      routes: { before: { approve: 19760, escalate: 240 }, after: { approve: 18220, escalate: 1780 } },
      route_changes: { "approve -> escalate": 1540 },
      findings_by_rule: [{ rule: "5.1.1", before: 30, after: 1570 }, { rule: "2.1.1", before: 30, after: 30 }],
      amount_newly_held: 104000000, examples: [],
    };
    mockApi([
      ["/api/policy/preview", () => preview],
      ["/api/policy/simulate", () => ({ id: "sim1", kind: "simulate", status: "done", done: 0, total: 0, result: impact, error: null, seconds: 4 })],
      ["/api/policy/graph/ask", () => graphAnswer],
      ["/api/policy/graph", () => policyGraph],
      ["/api/policy", () => policy],
      ["/api/health", () => health],
    ]);
    renderAt("/policy", "/policy", <PolicyPage />);
    await screen.findByText("Amount match");
    await userEvent.upload(screen.getByLabelText("Policy PDF"), new File(["%PDF-1.4"], "Company_Policy_v3.06.pdf", { type: "application/pdf" }));
    await userEvent.click(await screen.findByRole("button", { name: "Simulate it on the ledger" }));
    const panel = await screen.findByLabelText("Simulated impact");
    expect(within(panel).getByText(/would govern/)).toHaveTextContent(
      "Adopted, version 3.06 takes effect on 2026-04-01 and would govern 0 of the ledger's 20,000 invoices; the others stay under the version in force on their date.");
    expect(within(panel).getByText(/As if it had always applied, instead of v2\.5/)).toBeInTheDocument();
    expect(within(panel).getByText("1,540")).toBeInTheDocument();
    expect(within(panel).getByText(/₹10,40,00,000 would newly wait for review/)).toBeInTheDocument();
    expect(within(panel).getByText("approve → escalate: 1,540")).toBeInTheDocument();
    expect(within(panel).getByText("1,570")).toBeInTheDocument();          // rule 5.1.1 under the document
    expect(within(panel).queryByText("2.1.1")).not.toBeInTheDocument();    // unchanged rules are not listed
  });

  it("lists the problems of a document the patterns cannot read", async () => {
    mockApi([
      ["/api/policy/preview", () => ({ ...preview, usable: false, changes: [], problems: ["Rule 4.3.1: the review threshold is not stated"] })],
      ["/api/policy/graph/ask", () => graphAnswer],
      ["/api/policy/graph", () => policyGraph],
      ["/api/policy", () => policy],
      ["/api/health", () => health],
    ]);
    renderAt("/policy", "/policy", <PolicyPage />);
    await screen.findByText("Amount match");
    await userEvent.upload(screen.getByLabelText("Policy PDF"), new File(["%PDF-1.4"], "memo.pdf", { type: "application/pdf" }));
    expect(await screen.findByText("Rule 4.3.1: the review threshold is not stated")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Adopt version/ })).not.toBeInTheDocument();
    expect(screen.getByText(/With a configured model/)).toBeInTheDocument();
  });
});

describe("the results page", () => {
  it("shows the measured results read from the repository", async () => {
    mockApi([["/api/results", () => results]]);
    renderAt("/results", "/results", <ResultsPage />);
    expect(await screen.findByText("Controls: F1 on the benchmark")).toBeInTheDocument();
    expect(within(kpi("Controls: F1 on the benchmark")).getByText("0.833")).toBeInTheDocument();
    expect(within(kpi("Policy-driven: wrong decisions")).getByText("0")).toBeInTheDocument();
    expect(within(kpi("Frozen thresholds: worst case")).getByText("30.7%")).toBeInTheDocument();
    expect(screen.getAllByText("Policy-driven controls")).toHaveLength(3 + 1);   // three ledgers, and the per-class table
    const strict = screen.getByText("Strict policy").closest("tr") as HTMLElement;
    expect(within(strict).getByText("14/14")).toBeInTheDocument();
    expect(within(strict).getByText("12,012")).toBeInTheDocument();
    expect(screen.getByRole("img", { name: "Throughput against worker processes" })).toBeInTheDocument();
    expect(screen.getByText("Out of 84 values, 80 were proposed correctly.")).toBeInTheDocument();
    expect(screen.getByText("pilot")).toBeInTheDocument();
  });
});

describe("the application shell", () => {
  it("asks for the API token when the server requires one", async () => {
    mockApi([
      ["/api/me", (_url, init) => (new Headers(init?.headers).get("Authorization") === "Bearer t0ken" ? { name: "A. Auditor", role: "reviewer", via: "account" } : error(401, "a valid API token is required"))],
      ["/api/health", () => ({ ...health, auth: true })],
    ]);
    render(
      <MemoryRouter>
        <Routes>
          <Route element={<Layout />}>
            <Route index element={<p>the page</p>} />
          </Route>
        </Routes>
      </MemoryRouter>,
    );
    expect(await screen.findByText("This server requires an API token.")).toBeInTheDocument();
    expect(screen.queryByText("the page")).not.toBeInTheDocument();
    await userEvent.type(screen.getByLabelText("API token"), "t0ken");
    await userEvent.click(screen.getByRole("button", { name: "Save token" }));
    expect(await screen.findByText("the page")).toBeInTheDocument();
    expect(getToken()).toBe("t0ken");
    expect(await screen.findByLabelText("Signed in")).toHaveTextContent("A. Auditor · reviewer");
  });

  it("routes an unknown address to a page that says so", async () => {
    mockApi([["/api/overview", () => overview], ["/api/health", () => health]]);
    render(
      <MemoryRouter initialEntries={["/no/such/page"]}>
        <App />
      </MemoryRouter>,
    );
    expect(await screen.findByRole("heading", { name: "Not found" })).toBeInTheDocument();
    expect(screen.getByRole("navigation", { name: "Main" })).toHaveTextContent("Review queue");
    expect(await screen.findByText(/API 0\.4\.0 · sqlite/)).toBeInTheDocument();
  });

  it("names the assistant Ask AI and sends the old address there", async () => {
    mockApi([["/api/overview", () => overview], ["/api/health", () => health]]);
    render(
      <MemoryRouter initialEntries={["/copilot"]}>
        <App />
      </MemoryRouter>,
    );
    expect(await screen.findByRole("heading", { name: "Ask AI" })).toBeInTheDocument();
    const nav = screen.getByRole("navigation", { name: "Main" });
    expect(within(nav).getByRole("link", { name: /Ask AI/ })).toHaveAttribute("href", "/ask");
    expect(within(nav).getByRole("link", { name: /Vendor collusion/ })).toHaveAttribute("href", "/rings");
    for (const [name, href] of [["Kafka streams", "/kafka"], ["Agents & pipeline", "/ai"], ["Knowledge base", "/knowledge"], ["Knowledge graph", "/graph"], ["RAG retrieval", "/rag"]]) {
      expect(within(nav).getByRole("link", { name: new RegExp(name) })).toHaveAttribute("href", href);
    }
    expect(await within(nav).findByLabelText("40 waiting")).toBeInTheDocument();       // from the overview
  });
});

const job = (result: unknown) => ({ id: "job9", kind: "k", status: "done", done: 1, total: 1, result, error: null, seconds: 1 });

describe("the Kafka console", () => {
  it("shows the topics, publishes a ledger, runs the workers and reads a topic", async () => {
    const { calls } = mockApi([
      ["/api/system", () => system],
      ["/api/stream/sources", () => streamSources],
      ["/api/stream/log", () => ({ messages: [{ topic: "demo.invoice", partition_no: 2, kafka_offset: 41, doc_key: "INV40237", produced_ms: 1000, processed_ms: 1450,
        outcome: "audited", detail: "1 finding", result_id: 7, latency_ms: 450 }] })],
      ["/api/stream/peek", () => ({ topic: "demo.invoice", messages: [{ partition: 2, offset: 41, key: "VEND1001", timestamp: 1000, bytes: 812,
        preview: { invoice_id: "INV40237", vendor_id: "VEND1001", amount: 694181.12 } }] })],
      ["/api/stream/publish", () => job({ source: "ledger", name: "bench_seed_202", sent: { vendor: 60, invoice: 500 } })],
      ["/api/stream/work", () => job({ counts: { invoice: { audited: 480, duplicate: 20 }, email: {} } })],
      ["/api/stream", () => streamStatus],
    ]);
    renderAt("/kafka", "/kafka", <KafkaPage />);
    expect(await screen.findByRole("heading", { name: "Kafka streams" })).toBeInTheDocument();
    expect(await within(kpi("Consumer lag")).findByText("300")).toBeInTheDocument();
    expect(screen.getByRole("img", { name: /Kafka topology/ })).toBeInTheDocument();
    expect(screen.getByText("demo.compliance", { selector: ".kt-title" })).toBeInTheDocument();
    expect(await screen.findByRole("cell", { name: "INV40237" })).toBeInTheDocument();                    // the worker log
    expect(await screen.findByText("694181.12")).toBeInTheDocument();                                   // inside the invoice topic
    await userEvent.click(await screen.findByRole("button", { name: "Publish to Kafka" }));
    expect(await screen.findByText("Published bench_seed_202: 60 to vendor, 500 to invoice.")).toBeInTheDocument();
    const published = calls.find((c) => c.url.includes("/api/stream/publish"));
    expect(JSON.parse(String(published?.init?.body))).toEqual({ source: "ledger", name: "bench_seed_202", limit: 500 });
    await userEvent.click(screen.getByRole("button", { name: "Run the workers" }));
    expect(await screen.findByText(/The workers caught up\. invoice: 480 audited, 20 duplicate · email: nothing new\./)).toBeInTheDocument();
  });

  it("says when the broker cannot be reached and does not offer to publish", async () => {
    mockApi([
      ["/api/system", () => ({ ...system, kafka: { configured: true, connected: false, bootstrap: "127.0.0.1:9092", error: "no broker answers" } })],
      ["/api/stream/sources", () => streamSources],
      ["/api/stream/log", () => ({ messages: [] })],
      ["/api/stream/peek", () => error(409, "Kafka is not reachable")],
      ["/api/stream", () => ({ configured: true, topics: [], error: "no broker answers" })],
    ]);
    renderAt("/kafka", "/kafka", <KafkaPage />);
    expect(await screen.findByRole("heading", { name: "Kafka streams" })).toBeInTheDocument();
    await waitFor(() => expect(screen.getByRole("button", { name: "Publish to Kafka" })).toBeDisabled());
    expect(screen.getByRole("button", { name: "Run the workers" })).toBeDisabled();
  });
});

describe("the RAG trace", () => {
  it("traces a question through every step and shows where the context came from", async () => {
    const { calls } = mockApi([
      ["/api/system", () => system],
      ["/api/rag/trace", () => ragTrace],
      ["/api/copilot/ask", () => job({ answer: null, invoice_id: null, model: null, passages: [], sources: [], facts: ragTrace.facts })],
    ]);
    renderAt("/rag", "/rag", <RagPage />);
    await userEvent.type(screen.getByLabelText("Question to trace"), "Who has to approve an invoice of ₹30 lakh?");
    await userEvent.click(screen.getByRole("button", { name: "Trace retrieval" }));
    expect(await within(kpi("Ranking used")).findByText("hybrid")).toBeInTheDocument();
    expect(calls.some((c) => c.url.includes("/api/rag/trace?q=Who%20has%20to%20approve") && c.url.includes("k=5"))).toBe(true);
    const steps = screen.getByRole("list", { name: "Retrieval steps" });
    expect(within(steps).getAllByRole("listitem").filter((li) => li.classList.contains("done"))).toHaveLength(7);   // all but the answer
    expect(screen.getByText(/above every approval limit/)).toBeInTheDocument();                               // the graph's fact
    expect(screen.getByText("Fusion (RRF, k = 60)")).toBeInTheDocument();
    expect(screen.getByText("from the graph")).toBeInTheDocument();
    expect(screen.getByText("retrieved")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "8. Generate the answer" }));
    expect(await screen.findByText(/The model is offline, so there is no written answer/)).toBeInTheDocument();
  });
});

describe("the knowledge base", () => {
  it("shows the documents, the registry across versions and every passage", async () => {
    mockApi([["/api/system", () => system], ["/api/knowledge", () => knowledge]]);
    renderAt("/knowledge", "/knowledge", <KnowledgePage />);
    expect(await screen.findByRole("heading", { name: "Knowledge base" })).toBeInTheDocument();
    expect(within(kpi("Rules verified")).getByText("1/2")).toBeInTheDocument();
    expect(within(kpi("Embedded")).getByText("2/3")).toBeInTheDocument();
    expect(screen.getByText("approval_limits: Manager 150000 · Director 2500000").closest("td")).toHaveClass("changed");
    expect(screen.getByText("approval_limits: Manager 100000 · Director 2500000").closest("td")).not.toHaveClass("changed");
    expect(screen.getByText("differs")).toBeInTheDocument();
    await userEvent.selectOptions(screen.getByLabelText("Kind of passage"), "text");
    expect(screen.getByText("Passages (1)")).toBeInTheDocument();
  });
});

describe("the agents page", () => {
  it("shows the agents and replays an invoice's audit step by step", async () => {
    mockApi([
      ["/api/system", () => system],
      ["/api/ai", () => aiLayer],
      ["/api/invoices/INV40237", () => invoice],
    ]);
    renderAt("/ai", "/ai", <AiLayerPage />);
    expect(await screen.findByRole("heading", { name: "Agents & pipeline" })).toBeInTheDocument();
    expect(within(kpi("Agents")).getByText("3")).toBeInTheDocument();
    expect(within(kpi("Model")).getByText("not answering")).toBeInTheDocument();
    expect(screen.getByRole("img", { name: /The audit graph/ })).toBeInTheDocument();
    const card = screen.getByText("vendor_intelligence", { selector: ".agent-card span" }).closest("article") as HTMLElement;
    expect(within(card).getByText("4.1.2")).toBeInTheDocument();                              // the rule it judges
    expect(within(card).getByText(/vendor history by 4\.1\.2/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "INV40237" }));
    expect(await screen.findByRole("heading", { name: "Replay: INV40237" })).toBeInTheDocument();
    await userEvent.click(await screen.findByRole("button", { name: "Show all" }));
    expect(await screen.findByRole("link", { name: "Open the audit pack" })).toHaveAttribute("href", "/invoice/INV40237");
  });
});

describe("the policy timeline", () => {
  it("shows which version governs which invoices and audits the ones under another version", async () => {
    const timeline = [
      { version: "2.5", from: "2025-04-01", until: "2026-04-01", invoices: 500000, under_other_version: 500000, unaudited: 0 },
      { version: "3.12", from: "2026-04-01", until: null, invoices: 0, under_other_version: 0, unaudited: 0 },
    ];
    let applied = false;
    mockApi([
      ["/api/policy/apply", () => {
        applied = true;
        return job({ invoices: 500000, flags: 10474, states: { AUTO_APPROVED: 492080, PENDING_REVIEW: 7920 }, unchanged: 0,
          runs: [{ run_id: 3, policy_version: "2.5", invoices: 500000 }] });
      }],
      ["/api/policy", () => (applied ? { ...policy, timeline: [{ ...timeline[0], under_other_version: 0 }, timeline[1]] }
        : { ...policy, active: "3.12", timeline, under_other_version: 500000 })],
      ["/api/health", () => health],
    ]);
    renderAt("/policy", "/policy", <PolicyPage />);
    expect(await screen.findByText(/5,00,000 invoices were last audited under a policy version that does not govern their date/)).toBeInTheDocument();
    const table = screen.getByRole("table", { name: "Which version governs which invoices" });
    expect(within(table).getByRole("row", { name: /v2\.5 from 2025-04-01 until 2026-04-01 5,00,000 5,00,000 under another version/ })).toBeInTheDocument();
    expect(within(table).getByRole("row", { name: /v3\.12 from 2026-04-01 onward 0 no invoice yet/ })).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Audit them under the version in force" }));
    expect(await screen.findByText(/5,00,000 invoices audited, each under the version in force on its date \(v2\.5: 5,00,000\); 0 kept their results/)).toBeInTheDocument();
  });
});
