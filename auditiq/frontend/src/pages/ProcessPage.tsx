import { Link } from "react-router-dom";
import { api } from "../api/client";
import type { ProcessMining } from "../api/types";
import { Badge, Empty, ErrorBox, Kpi, Loading, Panel } from "../components/ui";
import { count, percent } from "../lib/format";
import { useApi } from "../lib/useApi";

// Where each step sits on the map: the reference path on one row, escalation above it.
const PLACE: Record<string, { x: number; y: number }> = {
  "PO raised": { x: 62, y: 150 },
  "Goods received": { x: 207, y: 150 },
  "Invoice dated": { x: 352, y: 150 },
  Escalated: { x: 432, y: 48 },
  Approved: { x: 512, y: 150 },
  Due: { x: 657, y: 150 },
};
const BOX_W = 104;
const BOX_H = 40;

/** The directly-follows graph: one box per step, one arrow per pair of steps that directly follow each other. */
function ProcessMap({ data }: { data: ProcessMining }) {
  const top = Math.max(1, ...data.edges.map((e) => e.cases));
  const cases = Object.fromEntries(data.activities.map((a) => [a.step, a.cases]));
  return (
    <svg className="process-map" viewBox="0 0 720 230" role="img" aria-label={`Process map of ${data.cases} invoices with ${data.edges.length} transitions`}>
      <defs>
        <marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="9" markerHeight="9" markerUnits="userSpaceOnUse" orient="auto-start-reverse">
          <path d="M0,0 L10,5 L0,10 z" fill="#64748b" />
        </marker>
      </defs>
      {data.edges.map((e) => {
        const a = PLACE[e.from];
        const b = PLACE[e.to];
        if (!a || !b) return null;
        const forward = b.x >= a.x;
        const reference = data.reference.indexOf(e.to) === data.reference.indexOf(e.from) + 1 || e.from === "Escalated" || e.to === "Escalated";
        const x1 = a.x + (forward ? BOX_W / 2 : -BOX_W / 2);
        const x2 = b.x - (forward ? BOX_W / 2 : -BOX_W / 2);
        const y1 = a.y + (b.y < a.y ? -BOX_H / 2 : b.y > a.y ? BOX_H / 2 : 0);
        const y2 = b.y + (a.y < b.y ? -BOX_H / 2 : a.y > b.y ? BOX_H / 2 : 0);
        const skip = Math.abs(data.steps.indexOf(e.to) - data.steps.indexOf(e.from)) > 1 && a.y === b.y;
        const bend = skip ? 70 : 0;
        const mx = (x1 + x2) / 2;
        const my = (y1 + y2) / 2 + bend;
        return (
          <g key={`${e.from}-${e.to}`}>
            <title>{`${e.from} → ${e.to}: ${e.cases.toLocaleString("en-IN")} invoices, median ${e.median_days} days`}</title>
            <path
              d={skip ? `M${x1},${y1 + 12} Q${mx},${my} ${x2},${y2 + 12}` : `M${x1},${y1} L${x2},${y2}`}
              fill="none"
              stroke={reference ? "#047857" : "#dc2626"}
              strokeWidth={1.5 + (e.cases / top) * 5}
              strokeOpacity={0.55}
              markerEnd="url(#arrow)"
            />
            <text x={mx} y={skip ? my - 18 : a.y === b.y ? a.y - BOX_H / 2 - 8 : my} dx={a.y === b.y || skip ? 0 : a.y > b.y ? -34 : 34} textAnchor="middle" className="edge-label">
              {e.cases.toLocaleString("en-IN")} · {e.median_days} d
            </text>
          </g>
        );
      })}
      {data.steps.map((step) => {
        const p = PLACE[step];
        return (
          <g key={step}>
            <rect x={p.x - BOX_W / 2} y={p.y - BOX_H / 2} width={BOX_W} height={BOX_H} rx={9} className={step === "Escalated" ? "step escalated" : "step"} />
            <text x={p.x} y={p.y - 2} textAnchor="middle" className="step-name">
              {step}
            </text>
            <text x={p.x} y={p.y + 12} textAnchor="middle" className="step-count">
              {(cases[step] ?? 0).toLocaleString("en-IN")}
            </text>
          </g>
        );
      })}
    </svg>
  );
}

/** Process mining of procure-to-pay: how the invoices actually went through the process. */
export function ProcessPage() {
  const process = useApi(() => api.process());
  if (process.loading && !process.data) return <Loading what="Mining the process from the ledger" />;
  if (process.error) return <ErrorBox error={process.error} onRetry={process.reload} />;
  const p = process.data;
  if (!p) return null;
  if (!p.cases) {
    return (
      <div className="page">
        <h1>Process mining</h1>
        <Empty>No ledger is loaded.</Empty>
      </div>
    );
  }
  const total = (stage: string) => p.cycle_times.find((c) => c.stage === stage);
  const end = total("PO raised -> Approved");
  const escalated = p.escalations.filter((e) => e.times > 0).reduce((t, e) => t + e.cases, 0);
  const deviating = p.cases - p.conformant;
  return (
    <div className="page">
      <header className="page-head">
        <div>
          <span className="eyebrow">Intelligence · Process mining</span>
          <h1>Procure-to-pay as it actually ran</h1>
          <p className="muted">
            Every invoice is a case and the ledger holds the time of each of its steps: the purchase order, the goods receipt, the invoice, each escalation, the approval and the due date. The map shows how often one step directly follows another and the median days between them; the variants and the conformance check show where invoices left the reference path PO → goods receipt → invoice → approval → due date. A description of the process, not a finding.
          </p>
        </div>
      </header>
      <div className="kpis">
        <Kpi label="Invoices (cases)" value={count(p.cases)} hint={`${count(p.events)} events`} />
        <Kpi label="Follow the reference path" value={percent(p.conformant_share)} hint={`${count(p.conformant)} invoices`} tone="good" />
        <Kpi label="Leave it" value={count(deviating)} hint={`${count(p.deviations.reduce((t, d) => t + d.flagged_by_audit, 0))} of their deviations already flagged by the audit`} tone={deviating ? "warn" : "default"} />
        <Kpi label="Escalated before approval" value={count(escalated)} hint={percent(escalated / p.cases)} tone="accent" />
        <Kpi label="PO to approval" value={end?.median != null ? `${end.median} d` : "–"} hint={end?.p90 != null ? `median; 90% within ${end.p90} days` : ""} />
      </div>
      <Panel title="Process map" subtitle="Green: transitions of the reference path (escalation included); red: transitions that skip a step. Line width follows the number of invoices; labels give invoices · median days.">
        <ProcessMap data={p} />
      </Panel>
      <div className="grid-2">
        <Panel title={`Variants (${count(p.variant_count)})`} subtitle="The distinct orders of steps (repeated escalations counted once), most frequent first.">
          <table className="table compact">
            <thead>
              <tr>
                <th>Path</th>
                <th className="num">Invoices</th>
                <th className="num">Share</th>
              </tr>
            </thead>
            <tbody>
              {p.variants.map((v) => (
                <tr key={v.steps.join(">")}>
                  <td>
                    {v.follows_reference ? <Badge tone="good">reference</Badge> : <Badge tone="warn">deviates</Badge>} <span className="small">{v.steps.join(" → ")}</span>
                  </td>
                  <td className="num">{count(v.cases)}</td>
                  <td className="num">{percent(v.share)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </Panel>
        <Panel title="Conformance" subtitle="How the deviating invoices leave the reference path, and how many of them the latest audit already flagged.">
          {p.deviations.length ? (
            <table className="table compact">
              <thead>
                <tr>
                  <th>Deviation</th>
                  <th className="num">Invoices</th>
                  <th className="num">Flagged by the audit</th>
                  <th>Examples</th>
                </tr>
              </thead>
              <tbody>
                {p.deviations.map((d) => (
                  <tr key={d.kind}>
                    <td>{d.kind}</td>
                    <td className="num">{count(d.cases)}</td>
                    <td className="num">
                      {count(d.flagged_by_audit)} of {count(d.audited)} audited
                    </td>
                    <td>
                      {d.examples.slice(0, 3).map((id) => (
                        <Link key={id} className="mono small" to={`/invoice/${id}`} style={{ marginRight: 6 }}>
                          {id}
                        </Link>
                      ))}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : (
            <Empty>Every invoice follows the reference path.</Empty>
          )}
        </Panel>
      </div>
      <div className="grid-2">
        <Panel title="Cycle times" subtitle="Days between the steps: median and 90th percentile.">
          <table className="table compact">
            <thead>
              <tr>
                <th>Stage</th>
                <th className="num">Invoices</th>
                <th className="num">Median days</th>
                <th className="num">90th percentile</th>
              </tr>
            </thead>
            <tbody>
              {p.cycle_times.map((c) => (
                <tr key={c.stage}>
                  <td>{c.stage.replace(" -> ", " → ")}</td>
                  <td className="num">{count(c.cases)}</td>
                  <td className="num">{c.median ?? "–"}</td>
                  <td className="num">{c.p90 ?? "–"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </Panel>
        <Panel title="Approval time by role" subtitle="Days from the invoice to its approval, by the role that approved it.">
          <table className="table compact">
            <thead>
              <tr>
                <th>Role</th>
                <th className="num">Invoices</th>
                <th className="num">Median days</th>
                <th className="num">90th percentile</th>
              </tr>
            </thead>
            <tbody>
              {p.approval_by_role.map((r) => (
                <tr key={r.role}>
                  <td>{r.role}</td>
                  <td className="num">{count(r.cases)}</td>
                  <td className="num">{r.median ?? "–"}</td>
                  <td className="num">{r.p90 ?? "–"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </Panel>
      </div>
    </div>
  );
}
