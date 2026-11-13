import { lazy, Suspense, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api/client";
import type { BenfordTest } from "../api/types";
import { AmountHistogram, BenfordChart, Heatmap, LimitCliff, LorenzChart, MonthlyChart, WeekdayChart } from "../components/charts";
import { Empty, ErrorBox, Kpi, Loading, Panel } from "../components/ui";
import { count, inr, rupeesCompact } from "../lib/format";
import { useApi } from "../lib/useApi";

const SpendSkyline = lazy(() => import("../three/SpendSkyline").then((m) => ({ default: m.SpendSkyline })));

function conformityTone(test: BenfordTest): "good" | "warn" | "bad" {
  return test.conformity === "nonconformity" ? "bad" : test.conformity.startsWith("marginally") ? "warn" : "good";
}

function BenfordSummary({ test, n }: { test: BenfordTest; n: number }) {
  const significant = test.digits.filter((d) => d.significant);
  return (
    <dl className="facts">
      <div>
        <dt>Amounts tested</dt>
        <dd>{count(n)} (at least ₹10)</dd>
      </div>
      <div>
        <dt>Mean absolute deviation</dt>
        <dd>
          {test.mad.toFixed(test.digits.length > 10 ? 5 : 4)} · <span className={`conformity ${conformityTone(test)}`}>{test.conformity}</span>
        </dd>
      </div>
      <div>
        <dt>Thresholds (Nigrini)</dt>
        <dd>{test.thresholds.map((t) => t.toString()).join(" · ")}</dd>
      </div>
      <div>
        <dt>Chi-square</dt>
        <dd>
          {test.chi2.toFixed(1)} on {test.dof} degrees of freedom
        </dd>
      </div>
      <div>
        <dt>Digits that differ (z &gt; 1.96)</dt>
        <dd>{significant.length ? significant.map((d) => d.digit).join(", ") : "none"}</dd>
      </div>
    </dl>
  );
}

export function AnalyticsPage() {
  const data = useApi(() => api.analytics());
  const policy = useApi(() => api.policy());
  const [digits, setDigits] = useState<"first" | "first_two">("first");
  const a = data.data;
  const titles = useMemo(() => Object.fromEntries((policy.data?.rules ?? []).map((r) => [r.rule, r.title])), [policy.data]);

  const near = a?.amounts.limits ?? [];
  const under = near.reduce((t, l) => t + l.below, 0);
  const over = near.reduce((t, l) => t + l.above, 0);
  const weekend = a ? a.weekdays.slice(5).reduce((t, w) => t + w.invoices, 0) : 0;

  return (
    <div className="page">
      <header className="page-head">
        <div>
          <span className="eyebrow">Intelligence · Analytics</span>
          <h1>Forensic analytics</h1>
          <p className="muted">
            The tests an auditor runs over the whole ledger before reading single findings: the shape of the amounts (Benford), amounts piled up under the approval limits, timing,
            where the findings concentrate, who approves them and how concentrated the spend is. Every figure is computed from the store when the page loads
            {a?.policy_version ? <>, against the limits of policy <strong>v{a.policy_version}</strong></> : null}.
          </p>
        </div>
        <div className="page-actions">
          <Link className="btn" to="/rings">
            Vendor collusion
          </Link>
        </div>
      </header>

      <ErrorBox error={data.error} onRetry={data.reload} />
      {!a && data.loading && <Loading what="Analysing the ledger" />}

      {a && (
        <>
          <div className="kpis eight">
            <Kpi label="Invoices analysed" value={count(a.invoices)} hint={`${a.monthly.length} months · ${a.skyline.categories.length} categories`} />
            <Kpi label="Benford, first digit" value={a.benford.first.mad.toFixed(4)} hint={a.benford.first.conformity} tone={conformityTone(a.benford.first)} />
            <Kpi label="Benford, first two digits" value={a.benford.first_two.mad.toFixed(5)} hint={a.benford.first_two.conformity} tone={conformityTone(a.benford.first_two)} />
            <Kpi label="Just under a limit" value={count(under)} hint={`against ${count(over)} just over · ${over ? (under / over).toFixed(2) : "–"}×`} tone={over && under / over > 1.25 ? "warn" : "default"} />
            <Kpi label="Spend concentration" value={a.concentration.gini === null ? "–" : a.concentration.gini.toFixed(3)} hint="Gini coefficient over vendors" tone="accent" share={a.concentration.gini ?? 0} />
            <Kpi label="Top 10 vendors" value={a.concentration.top10_share === null ? "–" : `${(a.concentration.top10_share * 100).toFixed(1)}%`} hint={`of the spend · HHI ${a.concentration.hhi?.toFixed(0) ?? "–"}`} share={a.concentration.top10_share ?? 0} />
            <Kpi label="Weekend invoices" value={count(weekend)} hint={`${((weekend / Math.max(1, a.invoices)) * 100).toFixed(1)}% of the ledger`} />
            <Kpi label="Approvers" value={count(a.approvers.total)} hint={`${count(a.approvers.top.reduce((t, r) => t + r.over_limit, 0))} approvals above own limit among the top ${a.approvers.top.length}`} tone="bad" />
          </div>

          <div className="grid-2">
            <Panel title="Monthly volume" subtitle="Invoices per month: clean, with findings, and escalated to a reviewer.">
              {a.monthly.length ? <MonthlyChart rows={a.monthly} /> : <Empty>No dated invoices.</Empty>}
            </Panel>
            <Panel title="Spend skyline" subtitle="Spend by vendor category and month in 3D: the tall bars are where the money went. Hover a bar for its amount.">
              <Suspense fallback={<Loading what="Raising the skyline" />}>
                <SpendSkyline skyline={a.skyline} />
              </Suspense>
            </Panel>
          </div>

          <Panel
            title="Benford's law"
            subtitle="In natural ledgers about 30% of amounts start with 1 and under 5% with 9. Fabricated or engineered amounts, and amounts pushed under a limit, break the pattern. Orange bars differ from the expected share by more than chance."
            actions={
              <div className="segmented" role="tablist" aria-label="Benford test">
                <button role="tab" aria-selected={digits === "first"} className={digits === "first" ? "active" : ""} onClick={() => setDigits("first")}>
                  First digit
                </button>
                <button role="tab" aria-selected={digits === "first_two"} className={digits === "first_two" ? "active" : ""} onClick={() => setDigits("first_two")}>
                  First two digits
                </button>
              </div>
            }
          >
            <div className="grid-2 wide-left flush">
              <BenfordChart test={a.benford[digits]} label={digits === "first" ? "First-digit test" : "First-two-digits test"} />
              <BenfordSummary test={a.benford[digits]} n={a.benford.n} />
            </div>
          </Panel>

          <div className="grid-2 wide-left">
            <Panel title="Amounts against the approval limits" subtitle="Invoices by amount on a logarithmic scale. Dashed lines are the approval limits of the active policy; the shaded band is the 10% just under each, where split and structured invoices land.">
              <AmountHistogram amounts={a.amounts} />
            </Panel>
            <Panel title="Just under, just over" subtitle="Invoices within 10% under each limit against 10% over it. A ratio well above 1 is the signature of amounts kept under an approver's limit.">
              {near.length ? <LimitCliff limits={near} near={a.amounts.near} /> : <Empty>The active policy has no approval limits.</Empty>}
            </Panel>
          </div>

          <div className="grid-2">
            <Panel title="Day of the week" subtitle="Invoices dated on each weekday. Weekend dates (hatched) are a rule of the policy (4.2.1).">
              <WeekdayChart rows={a.weekdays} />
            </Panel>
            <Panel title="Spend concentration" subtitle={`Lorenz curve over ${count(a.concentration.vendors)} vendors, with the ten largest.`}>
              <div className="lorenz-grid">
                <LorenzChart data={a.concentration} />
                <table className="table compact">
                  <thead>
                    <tr>
                      <th>Vendor</th>
                      <th className="num">Spend</th>
                      <th className="num">Share</th>
                    </tr>
                  </thead>
                  <tbody>
                    {a.concentration.top.map((v) => (
                      <tr key={v.vendor_id}>
                        <td>
                          <Link to={`/invoice?q=${encodeURIComponent(v.vendor_name)}`}>{v.vendor_name}</Link>
                        </td>
                        <td className="num">{rupeesCompact(v.amount)}</td>
                        <td className="num">{(v.share * 100).toFixed(2)}%</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </Panel>
          </div>

          <Panel title="Findings by vendor category and rule" subtitle="Kept findings of the latest result of each invoice. Darker cells hold more findings; hover a cell for the rule.">
            {a.categories.rules.length ? <Heatmap data={a.categories} titles={titles} /> : <Empty>No finding yet.</Empty>}
          </Panel>

          <Panel title="Approvers" subtitle={`The ${a.approvers.top.length} of ${count(a.approvers.total)} approvers with the most money on invoices with findings. "Above own limit" counts their approvals that broke the approval-limit rule.`}>
            <div className="table-wrap">
              <table className="table sticky">
                <thead>
                  <tr>
                    <th>Approver</th>
                    <th>Role</th>
                    <th className="num">Own limit</th>
                    <th className="num">Invoices</th>
                    <th className="num">Vendors</th>
                    <th className="num">Approved</th>
                    <th className="num">With findings</th>
                    <th className="share-col">Money with findings</th>
                    <th className="num">Above own limit</th>
                  </tr>
                </thead>
                <tbody>
                  {a.approvers.top.map((r) => (
                    <tr key={r.approver}>
                      <td className="strong">{r.approver}</td>
                      <td>{r.role ?? <span className="muted">unknown</span>}</td>
                      <td className="num">{r.limit === null ? "–" : `₹${inr(r.limit)}`}</td>
                      <td className="num">{count(r.invoices)}</td>
                      <td className="num">{count(r.vendors)}</td>
                      <td className="num">{rupeesCompact(r.amount)}</td>
                      <td className="num">{count(r.flagged)}</td>
                      <td className="share-col">
                        <span className="inline-bar">
                          <i style={{ width: `${(r.flagged_amount / Math.max(1, a.approvers.top[0]?.flagged_amount ?? 1)) * 100}%`, background: "#fb923c" }} />
                        </span>
                        <span className="small">{rupeesCompact(r.flagged_amount)}</span>
                      </td>
                      <td className={`num ${r.over_limit ? "bad-text strong" : ""}`}>{count(r.over_limit)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Panel>
        </>
      )}
    </div>
  );
}
