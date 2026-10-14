import { Link, useNavigate } from "react-router-dom";
import { api } from "../api/client";
import { BarList, Empty, ErrorBox, Kpi, Loading, Panel } from "../components/ui";
import { count, rupeesCompact, stateLabel } from "../lib/format";
import { useApi } from "../lib/useApi";
import { RiskConstellation } from "../three/RiskConstellation";

const SEVERITY_COLOR: Record<string, string> = { critical: "#f87171", high: "#fb923c", medium: "#fbbf24", low: "#94a3b8" };

export function OverviewPage() {
  const overview = useApi(() => api.overview());
  const map = useApi(() => api.riskMap());
  const navigate = useNavigate();
  const o = overview.data;

  return (
    <div className="page">
      <header className="page-head">
        <div>
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
        <div className="kpis">
          <Kpi label="Invoices in the ledger" value={count(o.invoices)} hint={`${count(o.vendors)} vendors`} />
          <Kpi label="Audited" value={count(o.audited)} hint={`${o.invoices ? ((o.audited / o.invoices) * 100).toFixed(0) : 0}% of the ledger`} tone="accent" />
          <Kpi label="Approved automatically" value={count(o.states.AUTO_APPROVED ?? 0)} tone="good" />
          <Kpi label="Waiting for review" value={count(o.states.PENDING_REVIEW ?? 0)} tone="warn" hint={o.states.NOT_SAMPLED ? `${count(o.states.NOT_SAMPLED)} sampled, not selected` : undefined} />
          <Kpi label="Findings" value={count(o.findings)} tone="bad" />
          <Kpi label="Reviewed" value={count(o.reviewed)} />
        </div>
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
            <Empty>No vendor is loaded. Run <code>python -m auditiq setup --dataset data/large_seed_505</code>.</Empty>
          )
        ) : (
          map.loading && <Loading what="Placing the vendors" />
        )}
        <div className="legend">
          <span><i style={{ background: "#34d399" }} /> risk below 30</span>
          <span><i style={{ background: "#fbbf24" }} /> 30 to 49</span>
          <span><i style={{ background: "#fb923c" }} /> 50 to 69</span>
          <span><i style={{ background: "#f87171" }} /> 70 and above</span>
          <span><i style={{ background: "#a78bfa" }} /> blacklisted</span>
        </div>
      </Panel>

      {o && (
        <div className="grid-2">
          <Panel title="Findings by rule" subtitle="Findings kept in the latest result of each invoice.">
            {o.findings_by_rule.length ? (
              <BarList
                rows={o.findings_by_rule.map((f) => ({
                  key: `${f.rule}-${f.source}-${f.severity}`,
                  label: (
                    <>
                      <strong>{f.rule}</strong> {f.title} <span className="muted">({f.source})</span>
                    </>
                  ),
                  value: f.findings,
                  color: SEVERITY_COLOR[f.severity],
                }))}
              />
            ) : (
              <Empty>No finding yet. Audit the ledger with <code>python -m auditiq run --config C1</code>.</Empty>
            )}
          </Panel>
          <div className="stack">
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
            <Panel title="Outcome of the latest audit">
              <BarList
                rows={Object.entries(o.states).map(([state, n]) => ({
                  key: state,
                  label: stateLabel(state),
                  value: n,
                  color: state === "PENDING_REVIEW" ? "#fb923c" : state === "AUTO_APPROVED" ? "#34d399" : "#818cf8",
                }))}
              />
            </Panel>
          </div>
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
                <th>Note</th>
              </tr>
            </thead>
            <tbody>
              {o.runs.map((r) => (
                <tr key={r.run_id}>
                  <td>{r.run_id}</td>
                  <td>{r.configuration}</td>
                  <td>v{r.policy_version}</td>
                  <td>{r.model ?? <span className="muted">no model</span>}</td>
                  <td className="num">{count(r.invoices)}</td>
                  <td>{r.started_at ?? "–"}</td>
                  <td className="muted">{r.note || "–"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </Panel>
      )}
    </div>
  );
}
