import path from "node:path";
import { fileURLToPath } from "node:url";
import { expect, test, type Locator, type Page } from "@playwright/test";

// The whole application in a browser, in the order a reviewer uses it. The server (scripts/e2e_server.py) starts
// with benchmark ledger 202 set up from the command line, policy v2.5 active and no model. The tests run in
// order and share that store: a workbook of ledger 909 is uploaded and audited, a finding is reviewed, a policy
// document is adopted and the ledger audited under it.

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..", "..");
const WORKBOOK = path.join(ROOT, ".auditiq", "e2e", "pilot_seed_909.xlsx");
const POLICY = path.join(ROOT, "policy", "variants_heldout", "Company_Policy_v4.10.pdf");

test.describe.configure({ mode: "serial" });

const kpi = (page: Page, label: string): Locator =>
  page.locator(".kpi").filter({ has: page.locator(".kpi-label", { hasText: new RegExp(`^${label}$`) }) }).locator(".kpi-value");

// An error in the browser's console or an uncaught exception fails the test in which it happened.
let browserErrors: string[] = [];
test.beforeEach(async ({ page }) => {
  browserErrors = [];
  page.on("console", (m) => {
    if (m.type() === "error") browserErrors.push(m.text());
  });
  page.on("pageerror", (e) => browserErrors.push(e.message));
});
test.afterEach(() => {
  expect(browserErrors, "errors in the browser console").toEqual([]);
});

test("the overview shows the ledger set up from the command line", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Audit overview" })).toBeVisible();
  await expect(page.locator(".page-head")).toContainText("bench_seed_202");
  await expect(page.locator(".page-head")).toContainText("v2.5");
  await expect(kpi(page, "Invoices in the ledger")).toHaveText("5,000");
  await expect(kpi(page, "Audited")).toHaveText("0");
  await expect(page.locator("canvas").first()).toBeVisible(); // the 3D risk constellation
});

test("a workbook is loaded through the web application and audited with the controls", async ({ page }) => {
  await page.goto("/");
  await page.getByLabel("Ledger file").setInputFiles(WORKBOOK);
  const load = page.getByRole("button", { name: "Load the ledger" });
  await expect(load).toBeDisabled(); // nothing is replaced before the reviewer confirms
  await page.getByLabel(/Replace the current ledger/).check();
  await load.click();
  await expect(page.locator(".banner")).toContainText("Ledger pilot_seed_909 loaded: 5,000 invoices from 250 vendors");
  await page.getByRole("button", { name: "Audit it with the controls" }).click();
  await expect(page.locator(".notice")).toHaveText(
    "5,000 invoices audited with the controls: 300 findings, 240 waiting for review.",
  );
  await expect(page.locator(".page-head")).toContainText("pilot_seed_909");
  await expect(kpi(page, "Audited")).toHaveText("5,000");
  await expect(kpi(page, "Waiting for review")).toHaveText("240");
  await expect(kpi(page, "Findings")).toHaveText("300");
});

test("an escalated invoice is opened from the review queue and a decision is recorded", async ({ page }) => {
  await page.goto("/review");
  await expect(page.getByRole("heading", { name: "Review queue" })).toBeVisible();
  const rows = page.locator("table tbody tr");
  await expect(rows).toHaveCount(240);
  const first = rows.first().getByRole("link");
  const invoice = (await first.textContent())!.trim();
  await first.click();

  await expect(page).toHaveURL(new RegExp(`/invoice/${invoice}$`));
  await expect(page.getByRole("heading", { name: new RegExp(invoice) })).toContainText("Escalated");
  await expect(page.getByText(/^Findings \([1-9]\d*\)$/)).toBeVisible();
  const decision = page.getByRole("form", { name: "Review decision" });
  await decision.getByRole("radio", { name: /^Approve/ }).check();
  await decision.getByRole("textbox", { name: "Reviewer" }).fill("E2E Reviewer");
  await decision.getByRole("textbox", { name: "Justification" }).fill("Checked against the purchase order in the browser test.");
  await decision.getByRole("button", { name: "Record decision" }).click();
  await expect(decision).toBeHidden(); // a decided result leaves the queue

  await page.goto("/review");
  await expect(page.locator("table tbody tr")).toHaveCount(239);
  await expect(page.locator("table tbody")).not.toContainText(invoice);
  await page.goto("/");
  await expect(kpi(page, "Reviewed")).toHaveText("1");
  await expect(kpi(page, "Waiting for review")).toHaveText("239");
});

test("an invoice is found by its vendor and by its number, and audited again on request", async ({ page, request }) => {
  const { items } = await (await request.get("/api/invoices?q=&limit=1")).json();
  const vendor: string = items[0].vendor_name;
  await page.goto("/invoice");
  await expect(page.getByRole("heading", { name: "Invoices" })).toBeVisible();
  await page.getByLabel("Invoice or vendor").fill(vendor);
  await page.getByRole("button", { name: "Search" }).click();
  const rows = page.locator("table tbody tr");
  await expect(rows.first()).toContainText(vendor);
  const invoice = (await rows.first().getByRole("link").textContent())!.trim();

  await page.getByLabel("Invoice or vendor").fill(invoice.toLowerCase()); // an invoice number opens the invoice
  await page.getByRole("button", { name: "Search" }).click();
  await expect(page).toHaveURL(new RegExp(`/invoice/${invoice}$`));
  await expect(page.getByLabel("Configuration")).toHaveValue("C1");
  await page.getByRole("button", { name: "Audit again" }).click();
  await expect(page.getByText(/C1 under policy v2\.5/)).toBeVisible();
  await expect(page.getByRole("heading", { name: new RegExp(invoice) })).toContainText(/Approved|Escalated|Sampled review/);
});

test("a policy document is previewed, adopted and applied to the ledger", async ({ page }) => {
  await page.goto("/policy");
  await expect(page.getByRole("heading", { name: "Policy", exact: true })).toBeVisible();
  await page.getByLabel("Policy PDF").setInputFiles(POLICY);
  await expect(page.locator(".preview")).toContainText("version 4.10");
  await expect(page.locator(".preview table tbody tr").first()).toBeVisible(); // the thresholds that change
  await page.getByRole("button", { name: "Adopt version 4.10" }).click();
  await expect(page.locator(".notice")).toHaveText(/Policy version 4\.10 adopted from Company_Policy_v4\.10\.pdf and made active\./);

  await page.getByRole("button", { name: "Audit the ledger under v4.10" }).click();
  await expect(page.locator(".notice")).toHaveText(/^5,000 invoices audited under the active version: [\d,]+ findings, [\d,]+ waiting for review\.$/);
  await page.goto("/");
  await expect(page.locator(".page-head")).toContainText("v4.10");
});

test("the policy is searched by wording without an embedding model", async ({ page }) => {
  await page.goto("/policy");
  await page.getByLabel("Question or keywords").fill("invoice dated on a weekend");
  await page.getByRole("button", { name: "Search", exact: true }).click();
  await expect(page.getByText("Ranking: lexical")).toBeVisible();
  await expect(page.locator("article.hit").first()).toBeVisible();
});

test("the measured results are shown", async ({ page }) => {
  await page.goto("/results");
  await expect(page.getByRole("heading", { name: "Results" })).toBeVisible();
  await expect(page.getByText("Detection on the benchmark ledgers")).toBeVisible();
  await expect(page.getByText("Policy change: policy-driven controls against frozen thresholds")).toBeVisible();
  await expect(page.locator("main")).toContainText("0.833");
});

test("the pipeline is drawn for every configuration", async ({ page }) => {
  await page.goto("/pipeline");
  await expect(page.getByRole("heading", { name: "The pipeline" })).toBeVisible();
  for (const config of ["C1", "C2", "C3", "C4", "C5"]) {
    await page.getByRole("tab", { name: config, exact: true }).click();
    await expect(page.getByRole("tab", { name: config, exact: true })).toHaveAttribute("aria-selected", "true");
    await expect(page.locator("canvas").first()).toBeVisible();
  }
});

test("the copilot works without a model and says what needs one", async ({ page }) => {
  await page.goto("/copilot");
  await expect(page.getByRole("heading", { name: "Copilot" })).toBeVisible();
  await expect(page.getByRole("tab", { name: /data/i })).toBeDisabled();
});

test("a page opened by its address and an unknown address", async ({ page }) => {
  await page.goto("/results");
  await page.reload();
  await expect(page.getByRole("heading", { name: "Results" })).toBeVisible();
  await page.goto("/no-such-page");
  await expect(page.locator("main")).toContainText(/not found/i);
});
