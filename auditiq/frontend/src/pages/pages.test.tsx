import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactElement } from "react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, describe, expect, it } from "vitest";
import { getToken, setToken } from "../api/client";
import { App } from "../App";
import { Layout } from "../components/Layout";
import { health, invoice, overview, policy, preview, queue, results } from "../test/fixtures";
import { error, mockApi } from "../test/mockApi";
import { InvoicePage } from "./InvoicePage";
import { OverviewPage } from "./OverviewPage";
import { PolicyPage } from "./PolicyPage";
import { ResultsPage } from "./ResultsPage";
import { ReviewPage } from "./ReviewPage";

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
    ]);
    renderAt("/", "/", <OverviewPage />);
    expect(await screen.findByText("Invoices in the ledger")).toBeInTheDocument();
    expect(within(kpi("Invoices in the ledger")).getByText("1,200")).toBeInTheDocument();
    expect(within(kpi("Waiting for review")).getByText("40")).toBeInTheDocument();
    expect(within(kpi("Audited")).getByText("5% of the ledger")).toBeInTheDocument();
    expect(await screen.findByRole("note")).toHaveTextContent("needs WebGL");
    expect(screen.getByRole("link", { name: "Kurian LLC" })).toHaveAttribute("href", "/invoice?q=Kurian%20LLC");
    expect(screen.getByText("Approval limit")).toBeInTheDocument();
  });

  it("says what went wrong when the API fails, and retries", async () => {
    let fail = true;
    mockApi([
      ["/api/overview", () => (fail ? error(503, "The database cannot be reached: connection refused") : overview)],
      ["/api/risk-map", () => ({ vendors: [] })],
    ]);
    renderAt("/", "/", <OverviewPage />);
    expect(await screen.findByRole("alert")).toHaveTextContent("The database cannot be reached");
    fail = false;
    await userEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(await screen.findByText("Invoices in the ledger")).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });
});

describe("the review queue", () => {
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

describe("the policy page", () => {
  it("previews the thresholds of an uploaded document and adopts it", async () => {
    let adopted: unknown = null;
    mockApi([
      ["/api/policy/preview", () => preview],
      ["/api/policy/adopt", (_url, init) => {
        adopted = JSON.parse(String(init?.body));
        return { version: "3.06", adopted: true, active: true };
      }],
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

  it("lists the problems of a document the patterns cannot read", async () => {
    mockApi([
      ["/api/policy/preview", () => ({ ...preview, usable: false, changes: [], problems: ["Rule 4.3.1: the review threshold is not stated"] })],
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
      ["/api/overview", (_url, init) => (new Headers(init?.headers).get("Authorization") === "Bearer t0ken" ? overview : error(401, "a valid API token is required"))],
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
});
