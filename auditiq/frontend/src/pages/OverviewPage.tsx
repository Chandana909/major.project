import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api, waitForJob } from "../api/client";
import type { Job, LedgerLoad } from "../api/types";
import { MonthlyChart, VendorMatrix } from "../components/charts";
import { ActivityLog, CoveragePanel, EscalationPreview, ForensicSignals, TopRiskVendors } from "../components/OverviewPanels";
import { Badge, Empty, ErrorBox, JobProgress, Kpi, Loading, Panel, StackedBar } from "../components/ui";
import { BLACKLISTED_COLOR, count, RISK_COLORS, rupeesCompact, SEVERITY_COLORS, stateLabel } from "../lib/format";
import { notifyStoreChanged, useApi } from "../lib/useApi";
import { RiskConstellation } from "../three/RiskConstellation";

/** "5.6%" of a whole, or a dash when there is no whole. */
function share(part: number | undefined, whole: number): string {
  return whole ? `${(((part ?? 0) / whole) * 100).toFixed(1)}%` : "–";
}

/** The time between two stored timestamps, in seconds or minutes. */
function duration(start: string | null, end: string | null): string {
  if (!start || !end) return "–";
  const seconds = (Date.parse(end.replace(" ", "T")) - Date.parse(start.replace(" ", "T"))) / 1000;
  if (!Number.isFinite(seconds) || seconds < 0) return "–";
  return seconds < 120 ? `${seconds.toFixed(0)} s` : `${(seconds / 60).toFixed(1)} min`;
}

type AuditSummary = { invoices: number; flags: number; states: Record<string, number> };

/** Replace the ledger with a workbook or a zip archive of CSV files, then audit it with the controls. */
function LedgerPanel({ onChanged }: { onChanged: () => void }) {
  const [file, setFile] = useState<File | null>(null);
  const [confirmed, setConfirmed] = useState(false);
  const [job, setJob] = useState<Job | null>(null);
  const [outcome, setOutcome] = useState<LedgerLoad | null>(null);
  const [audited, setAudited] = useState<string | null>(null);
  const [error, setError] = useState<Error | null>(null);

  const choose = (chosen: File | null) => {
    setFile(chosen);
    setConfirmed(false);
    setOutcome(null);
    setAudited(null);
    setError(null);
  };

  const load = async () => {
    if (!file) return;
    setError(null);
    try {
      const result = await waitForJob<LedgerLoad>(await api.loadLedger(file), setJob as (j: Job<LedgerLoad>) => void, 1000);
      setOutcome(result);
      if (result.loaded) {
        setFile(null);
        onChanged();
      }
    } catch (err) {
      setError(err as Error);
    } finally {
      setJob(null);
    }
  };

  const audit = async () => {
    setError(null);
    try {
      const summary = await waitForJob<AuditSummary>(await api.applyPolicy(), setJob as (j: Job<AuditSummary>) => void, 1000);
      setAudited(`${count(summary.invoices)} invoices audited with the controls: ${count(summary.flags)} findings, ${count(summary.states.PENDING_REVIEW ?? 0)} waiting for review.`);
      setOutcome(null);
      onChanged();
    } catch (err) {
      setError(err as Error);
    } finally {
      setJob(null);
    }
  };

  return (
    <Panel
      title="Load a ledger"
      subtitle="An Excel workbook with one sheet per table (vendor_master, purchase_orders, goods_receipts, invoices, approval_logs), or a .zip archive of the same tables as CSV files. The file is checked first; a ledger with any problem replaces nothing."
    >
      <label className="file">
        <input type="file" accept=".xlsx,.zip" aria-label="Ledger file" onChange={(e) => choose(e.target.files?.[0] ?? null)} />
        <span>{file ? file.name : "Choose a workbook or a zip archive"}</span>
      </label>
      {file && (
        <div className="row">
          <label className="toggle">
            <input type="checkbox" checked={confirmed} onChange={(e) => setConfirmed(e.target.checked)} /> Replace the current ledger with its audit results and review decisions
          </label>
          <button className="btn btn-primary" onClick={load} disabled={!confirmed || Boolean(job)}>
            Load the ledger
          </button>
        </div>
      )}
      <JobProgress job={job} />
      <ErrorBox error={error} />
      {outcome && !outcome.loaded && (
        <>
          <p>The ledger was not loaded; nothing was replaced:</p>
          <ul className="problems">
            {outcome.problems.map((p) => (
              <li key={p}>{p}</li>
            ))}
          </ul>
        </>
      )}
      {outcome?.loaded && (
        <div className="banner">
          <span>
            Ledger <strong>{outcome.ledger}</strong> loaded: {count(outcome.counts.invoices ?? 0)} invoices from {count(outcome.counts.vendor_master ?? 0)} vendors. It has not been audited yet.
          </span>
          <button className="btn btn-primary" onClick={audit} disabled={Boolean(job)}>
            Audit it with the controls
          </button>
        </div>
      )}
      {audited && (
        <div className="notice" role="status">
          {audited}
        </div>
      )}
    </Panel>
  );
}

export function OverviewPage() {
  const overview = useApi(() => api.overview());
  const map = useApi(() => api.riskMap());
  const analytics = useApi(() => api.analytics());
  const queue = useApi(() => api.queue(8));
  const navigate = useNavigate();
  const o = overview.data;

  return (
    <div className="page">
      <header className="page-head">
        <div>
          <span className="eyebrow">Audit · Overview</span>
          <h1>Audit overview</h1>
          <p className="muted">
            {o ? <>Ledger <strong>{o.ledger ?? "none loaded"}</strong> · active policy <strong>v{o.policy_version ?? "–"}</strong> · {o.backend}</> : "Every invoice of the ledger, checked against the policy in force."}
          </p>
        </div>
        <div className="page-actions">
          <Link className="btn btn-primary" to="/review">
            Open the review queue
          </Link>
        </div>
      </header>

      <ErrorBox error={overview.error} onRetry={overview.reload} />
      {!o && overview.loading && <Loading what="Reading the audit" />}

      {o && (
        <div className="kpis six">
          <Kpi label="Invoices in the ledger" value={count(o.invoices)} hint={`${count(o.vendors)} vendors · ${(o.invoices / Math.max(1, o.vendors)).toFixed(1)} invoices each`} />
          <Kpi label="Audited" value={count(o.audited)} hint={`${o.invoices ? ((o.audited / o.invoices) * 100).toFixed(0) : 0}% of the ledger`} tone="accent" share={o.invoices ? o.audited / o.invoices : 0} />
          <Kpi label="Approved automatically" value={count(o.states.AUTO_APPROVED ?? 0)} tone="good" hint={`${share(o.states.AUTO_APPROVED, o.audited)} of the audited`} share={(o.states.AUTO_APPROVED ?? 0) / Math.max(1, o.audited)} />
          <Kpi label="Waiting for review" value={count(o.states.PENDING_REVIEW ?? 0)} tone="warn" hint={o.states.NOT_SAMPLED ? `${count(o.states.NOT_SAMPLED)} sampled, not selected` : `${share(o.states.PENDING_REVIEW, o.audited)} of the audited`} share={(o.states.PENDING_REVIEW ?? 0) / Math.max(1, o.audited)} />
          <Kpi label="Findings" value={count(o.findings)} tone="bad" hint={`${((o.findings / Math.max(1, o.audited)) * 100).toFixed(1)} per 100 invoices · ${o.findings_by_rule.length} rules`} />
          <Kpi label="Reviewed" value={count(o.reviewed)} hint={`of ${count((o.states.PENDING_REVIEW ?? 0) + o.reviewed)} sent to a reviewer`} share={o.reviewed / Math.max(1, (o.states.PENDING_REVIEW ?? 0) + o.reviewed)} />
        </div>
      )}

      {o && <ForensicSignals o={o} vendors={map.data?.vendors ?? null} />}

      {o?.coverage && <CoveragePanel coverage={o.coverage} audited={o.audited} />}

      {o && (
        <Panel title="Composition of the audit" subtitle="The latest result of every audited invoice: the level of its weighted risk, the route it took, and where it stands in the workflow.">
          <div className="stacked-grid">
            <StackedBar
              label="Risk level"
              parts={(["CRITICAL", "HIGH", "MEDIUM", "LOW"] as const).map((k) => ({ key: k, label: k.charAt(0) + k.slice(1).toLowerCase(), value: o.risk_levels[k] ?? 0, color: RISK_COLORS[k] }))}
            />
            <StackedBar
              label="Route"
              parts={[
                { key: "escalate", label: "Escalated", value: o.routes.escalate ?? 0, color: RISK_COLORS.CRITICAL },
                { key: "sample", label: "Sampled", value: o.routes.sample ?? 0, color: RISK_COLORS.MEDIUM },
                { key: "approve", label: "Approved", value: o.routes.approve ?? 0, color: RISK_COLORS.LOW },
              ]}
            />
            <StackedBar
              label="Workflow"
              parts={Object.entries(o.states).map(([state, n]) => ({
                key: state,
                label: stateLabel(state),
                value: n,
                color: state === "PENDING_REVIEW" ? RISK_COLORS.HIGH : state === "AUTO_APPROVED" ? RISK_COLORS.LOW : state.startsWith("REVIEW_") ? "#6366f1" : "#94a3b8",
              }))}
            />
          </div>
        </Panel>
      )}

      <Panel
        title="Risk constellation"
        subtitle="Every vendor of the ledger. Each sector is a spending category; height is the highest risk among the vendor's invoices; size grows with the number of invoices; pulsing points have invoices waiting for review; violet points are blacklisted."
      >
        <ErrorBox error={map.error} onRetry={map.reload} />
        {map.data ? (
          map.data.vendors.length ? (
            <RiskConstellation vendors={map.data.vendors} onSelect={(v) => navigate(`/invoice?q=${encodeURIComponent(v.vendor_name)}`)} />
          ) : (
            <Empty>No vendor is loaded. Load a ledger below, or run <code>python -m auditiq setup --dataset data/large_seed_505</code>.</Empty>
          )
        ) : (
          map.loading && <Loading what="Placing the vendors" />
        )}
        <div className="legend">
          <span><i style={{ background: RISK_COLORS.LOW }} /> risk below 30</span>
          <span><i style={{ background: RISK_COLORS.MEDIUM }} /> 30 to 49</span>
          <span><i style={{ background: RISK_COLORS.HIGH }} /> 50 to 69</span>
          <span><i style={{ background: RISK_COLORS.CRITICAL }} /> 70 and above</span>
          <span><i style={{ background: BLACKLISTED_COLOR }} /> blacklisted</span>
        </div>
      </Panel>

      <div className="grid-2">
        <Panel title="Vendor risk matrix" subtitle="Each vendor: invoices across, the share of its invoices with findings up, size by spend, colour by its highest risk. Click a vendor to see its invoices.">
          <ErrorBox error={map.error} onRetry={map.reload} />
          {map.data ? <VendorMatrix vendors={map.data.vendors} onSelect={(v) => navigate(`/invoice?q=${encodeURIComponent(v.vendor_name)}`)} /> : map.loading && <Loading what="Plotting the vendors" />}
        </Panel>
        <Panel title="Monthly anomaly trend" subtitle="Invoices per month and how many had findings or went to a reviewer." actions={<Link className="btn btn-ghost" to="/analytics">All analytics</Link>}>
          <ErrorBox error={analytics.error} onRetry={analytics.reload} />
          {analytics.data ? <MonthlyChart rows={analytics.data.monthly} /> : analytics.loading && <Loading what="Counting the months" />}
        </Panel>
      </div>

      {o && (
        <div className="grid-2">
          <Panel title="Findings by rule" subtitle="Findings kept in the latest result of each invoice, most frequent first.">
            {o.findings_by_rule.length ? (
              <table className="table compact">
                <thead>
                  <tr>
                    <th>Rule</th>
                    <th>Check</th>
                    <th>Severity</th>
                    <th>Source</th>
                    <th className="num">Findings</th>
                    <th className="share-col">Share</th>
                  </tr>
                </thead>
                <tbody>
                  {o.findings_by_rule.map((f) => (
                    <tr key={`${f.rule}-${f.source}-${f.severity}`}>
                      <td className="mono strong">{f.rule}</td>
                      <td>{f.title}</td>
                      <td>
                        <span className="sev">
                          <i style={{ background: SEVERITY_COLORS[f.severity] }} />
                          {f.severity}
                        </span>
                      </td>
                      <td>
                        <Badge tone={f.source === "agent" ? "violet" : "neutral"}>{f.source}</Badge>
                      </td>
                      <td className="num strong">{count(f.findings)}</td>
                      <td className="share-col">
                        <span className="inline-bar">
                          <i style={{ width: `${(f.findings / Math.max(1, o.findings)) * 100}%`, background: SEVERITY_COLORS[f.severity] }} />
                        </span>
                        <span className="muted small">{((f.findings / Math.max(1, o.findings)) * 100).toFixed(1)}%</span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            ) : (
              <Empty>No finding yet. Audit the ledger with <code>python -m auditiq run --config C1</code>.</Empty>
            )}
          </Panel>
          <div className="stack">
            {queue.data && queue.data.items.length > 0 && <EscalationPreview items={queue.data.items} total={queue.data.total} titles={queue.data.rules} />}
            <Panel title="Vendors with the most invoices waiting">
              {o.vendors_waiting.length ? (
                <table className="table compact">
                  <thead>
                    <tr>
                      <th>Vendor</th>
                      <th className="num">Waiting</th>
                      <th className="num">Amount</th>
                    </tr>
                  </thead>
                  <tbody>
                    {o.vendors_waiting.map((v) => (
                      <tr key={v.vendor_id}>
                        <td>
                          <Link to={`/invoice?q=${encodeURIComponent(v.vendor_name)}`}>{v.vendor_name}</Link>
                        </td>
                        <td className="num">{v.waiting}</td>
                        <td className="num">{rupeesCompact(v.amount)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              ) : (
                <Empty>Nothing is waiting for review.</Empty>
              )}
            </Panel>
          </div>
        </div>
      )}

      {o && (
        <div className="grid-2">
          {o.activity && o.activity.length > 0 ? <ActivityLog rows={o.activity} /> : <Panel title="Activity"><Empty>Nothing has been audited yet.</Empty></Panel>}
          {map.data && <TopRiskVendors vendors={map.data.vendors} />}
        </div>
      )}

      {o && (
        <Panel title="Recent audit runs" subtitle="Each run is one configuration applied under one policy version; every result records its run.">
          <table className="table">
            <thead>
              <tr>
                <th>Run</th>
                <th>Configuration</th>
                <th>Policy</th>
                <th>Model</th>
                <th className="num">Invoices</th>
                <th>Started</th>
                <th className="num">Duration</th>
                <th>Note</th>
              </tr>
            </thead>
            <tbody>
              {o.runs.map((r) => (
                <tr key={r.run_id}>
                  <td className="mono">#{r.run_id}</td>
                  <td>
                    <Badge tone="accent">{r.configuration}</Badge>
                  </td>
                  <td>v{r.policy_version}</td>
                  <td>{r.model ?? <span className="muted">no model</span>}</td>
                  <td className="num">{count(r.invoices)}</td>
                  <td className="mono small">{r.started_at ?? "–"}</td>
                  <td className="num">{duration(r.started_at, r.finished_at)}</td>
                  <td className="muted">{r.note || "–"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </Panel>
      )}

      <LedgerPanel
        onChanged={() => {
          overview.reload();
          map.reload();
          analytics.reload();
          queue.reload();
          notifyStoreChanged();
        }}
      />
    </div>
  );
}
