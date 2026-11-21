import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactElement } from "react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { describe, expect, it } from "vitest";
import { health, invoice, queue } from "../test/fixtures";
import { agentAnswer, explanation, investigation, mailTriage, modelOverview, story } from "../test/fixturesIntel";
import { mockApi } from "../test/mockApi";
import { AgentPage } from "./AgentPage";
import { ExplainPage } from "./ExplainPage";
import { InvestigatorPage } from "./InvestigatorPage";
import { InvoicePage } from "./InvoicePage";
import { MailPage } from "./MailPage";
import { ProcessPage } from "./ProcessPage";

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

describe("the explainable AI page", () => {
  it("shows what drives the screen, the second opinion and the model card", async () => {
    mockApi([["/api/model", () => modelOverview]]);
    renderAt("/explain", "/explain", <ExplainPage />);
    expect(await screen.findByRole("heading", { name: "Risk screen and SHAP explanations" })).toBeInTheDocument();
    expect(within(kpi("Invoices scored")).getByText("1,200")).toBeInTheDocument();
    expect(within(kpi("Judgement leads")).getByText("12")).toBeInTheDocument();
    expect(screen.getByText("gstin_mismatch", { selector: ".barlist-label" })).toBeInTheDocument();
    expect(screen.getByRole("img", { name: /SHAP values of the 2 most important features for 3 invoices/ })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "INV40127" })).toHaveAttribute("href", "/invoice/INV40127");
    expect(screen.getByText(/890 \(85\.6%\) are in the top 2 %/)).toBeInTheDocument();
    // another head of the screen
    await userEvent.click(screen.getByRole("tab", { name: "4.1.2" }));
    expect(screen.getByText("window_total_ratio", { selector: ".barlist-label" })).toBeInTheDocument();
  });

  it("says how to train the screen when there is none", async () => {
    mockApi([["/api/model", () => ({ trained: false, detail: "no trained screen" })]]);
    renderAt("/explain", "/explain", <ExplainPage />);
    expect(await screen.findByText(/python -m auditiq model train/)).toBeInTheDocument();
  });
});

describe("an invoice's explanations", () => {
  it("draws the SHAP waterfall, lists what would clear each finding and tells the story", async () => {
    mockApi([
      ["/api/invoices/INV40237/explain", () => explanation],
      ["/api/invoices/INV40237/story", () => story],
      ["/api/invoices/INV40237", () => invoice],
      ["/api/health", () => health],
    ]);
    renderAt("/invoice/INV40237", "/invoice/:id", <InvoicePage />);
    expect(await screen.findByRole("heading", { name: "What would clear each finding" })).toBeInTheDocument();
    expect(await screen.findByText(/₹194,181\.12 \(38\.8%\) above it/)).toBeInTheDocument();
    expect(screen.getByText(/the lowest role whose limit covers the amount/)).toBeInTheDocument();
    expect(screen.getByText(/would also clear 37 other invoice/)).toBeInTheDocument();
    expect(screen.getByRole("img", { name: /SHAP waterfall: from -4\.20 to 2\.65 log-odds/ })).toBeInTheDocument();
    await userEvent.click(screen.getByRole("tab", { name: /4\.1\.2/ }));
    expect(screen.getByText("Structuring across days", { selector: "strong" })).toBeInTheDocument();
    expect(await screen.findByText(/Audited in run 1 \(C1, policy v2\.5\)/)).toBeInTheDocument();
    expect(screen.getByText(/Now: PENDING_REVIEW after 1 audit/)).toBeInTheDocument();
  });
});

describe("the trail investigator", () => {
  it("states the verdict, opens the failed check with its places and lists the reviewers", async () => {
    mockApi([["/api/investigation", () => investigation]]);
    renderAt("/investigator", "/investigator", <InvestigatorPage />);
    expect(await screen.findByText(investigation.verdict)).toBeInTheDocument();
    expect(within(kpi("Checks failed")).getByText("1")).toBeInTheDocument();
    // the failed check is open; the one needing attention opens on a click
    expect(screen.getByText("Dev Malhotra approved it with the reason 'ok'")).toBeInTheDocument();
    expect(screen.queryByText("Dev Malhotra approved a critical invoice of VEND1001")).not.toBeInTheDocument();
    await userEvent.click(screen.getByText("Critical findings cleared by a reviewer"));
    expect(screen.getByText("Dev Malhotra approved a critical invoice of VEND1001")).toBeInTheDocument();
    expect(screen.getAllByRole("link", { name: "INV40237" })[0]).toHaveAttribute("href", "/invoice/INV40237");
    expect(screen.getByRole("img", { name: /Timeline of runs, decisions/ })).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Show the text" }));
    expect(screen.getByText(/# Investigation of the audit record/)).toBeInTheDocument();
  });
});

describe("the mail triage", () => {
  it("counts the mailbox, lists the alerts with their reasons and the payments to hold", async () => {
    mockApi([["/api/mail", () => mailTriage]]);
    renderAt("/mail", "/mail", <MailPage />);
    expect(await screen.findByRole("heading", { name: "Vendor e-mail triage" })).toBeInTheDocument();
    expect(within(kpi("Payment redirection")).getByText("1")).toBeInTheDocument();
    expect(within(kpi("Payments to hold")).getByText("₹1,84,575")).toBeInTheDocument();
    expect(screen.getAllByText(/reads like the vendor's domain but is not it/)[0]).toBeInTheDocument();
    await userEvent.click(screen.getByText("accounts@kallasavant.example"));
    expect(screen.getByText("Confirm with the vendor's registered contact before changing the vendor master")).toBeInTheDocument();
    expect(screen.getAllByRole("link", { name: "INV44193" }).length).toBeGreaterThan(0);
  });

  it("says how to load e-mails when there are none", async () => {
    mockApi([["/api/mail", () => ({ ...mailTriage, emails: 0, alerts: [], holds: [] })]]);
    renderAt("/mail", "/mail", <MailPage />);
    expect(await screen.findByText(/python -m auditiq mail load mailbox\.mbox/)).toBeInTheDocument();
  });
});

describe("the audit agent", () => {
  it("asks a question, waits for the job and shows the answer with every step", async () => {
    let asked: unknown = null;
    mockApi([
      ["/api/agent/ask", (_url, init) => {
        asked = JSON.parse(String(init?.body));
        return { id: "job1", kind: "agent", status: "running", done: 0, total: 0, result: null, error: null, seconds: 0 };
      }],
      ["/api/jobs/job1", () => ({ id: "job1", kind: "agent", status: "done", done: 0, total: 0, result: agentAnswer, error: null, seconds: 0.1 })],
      ["/api/queue", () => queue],
      ["/api/health", () => health],
    ]);
    renderAt("/agent", "/agent", <AgentPage />);
    await userEvent.type(await screen.findByLabelText("Question for the agent"), "Which role must approve an invoice of Rs 3,50,000?");
    await userEvent.click(screen.getByRole("button", { name: "Ask the agent" }));
    await waitFor(() => expect(asked).toEqual({ question: "Which role must approve an invoice of Rs 3,50,000?", mode: "auto" }));
    expect(await screen.findByText("planned by rules")).toBeInTheDocument();
    expect(screen.getByText("T1")).toBeInTheDocument();
    expect(screen.getByText(/approval_rule\(amount: 350000\)/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "INV40237" })).toHaveAttribute("href", "/invoice/INV40237");
    // without a model the model planner cannot be chosen
    expect(screen.getByRole("option", { name: /no model configured/ })).toBeDisabled();
  });
});

describe("process mining", () => {
  it("draws the process map and lists the variants, the deviations and the cycle times", async () => {
    const steps = ["PO raised", "Goods received", "Invoice dated", "Escalated", "Approved", "Due"];
    const reference = ["PO raised", "Goods received", "Invoice dated", "Approved", "Due"];
    mockApi([["/api/process", () => ({
      cases: 1200, events: 6100, steps, reference, conformant: 1170, conformant_share: 0.975,
      activities: steps.map((step) => ({ step, cases: step === "Escalated" ? 160 : 1200 })),
      edges: [{ from: "PO raised", to: "Goods received", cases: 1170, median_days: 24 }, { from: "Invoice dated", to: "Escalated", cases: 160, median_days: 3.5 }, { from: "PO raised", to: "Invoice dated", cases: 10, median_days: 30 }],
      variants: [{ steps: reference, cases: 1010, share: 0.8417, follows_reference: true, examples: ["INV40001"] }, { steps: ["Invoice dated", "Approved", "Due"], cases: 20, share: 0.0167, follows_reference: false, examples: ["INV40034"] }],
      variant_count: 4,
      deviations: [{ kind: "no goods received", cases: 30, flagged_by_audit: 30, audited: 30, examples: ["INV40034"] }],
      cycle_times: [{ stage: "PO raised -> Approved", cases: 1170, median: 33.6, p90: 46.7 }],
      approval_by_role: [{ role: "Manager", cases: 500, median: 3.7, p90: 6.6 }],
      escalations: [{ times: 0, cases: 1040 }, { times: 1, cases: 160 }],
    })]]);
    renderAt("/process", "/process", <ProcessPage />);
    expect(await screen.findByRole("heading", { name: "Procure-to-pay as it actually ran" })).toBeInTheDocument();
    expect(within(kpi("Follow the reference path")).getByText("97.5%")).toBeInTheDocument();
    expect(within(kpi("Escalated before approval")).getByText("160")).toBeInTheDocument();
    expect(screen.getByRole("img", { name: /Process map of 1200 invoices with 3 transitions/ })).toBeInTheDocument();
    expect(screen.getByText("30 of 30 audited")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "INV40034" })).toHaveAttribute("href", "/invoice/INV40034");
    expect(screen.getByText("PO raised → Approved")).toBeInTheDocument();
  });
});
