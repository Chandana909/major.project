import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api/client";
import type { Investigation, InvestigationCheck } from "../api/types";
import { Badge, Empty, ErrorBox, Kpi, Loading, Panel } from "../components/ui";
import { count } from "../lib/format";
import { useApi } from "../lib/useApi";

const TONE = { fail: "bad", attention: "warn", pass: "good" } as const;
const LABEL = { fail: "Failed", attention: "Attention", pass: "Passed" } as const;
const KIND_COLORS: Record<string, string> = { run: "#047857", review: "#ea580c", document: "#7c3aed", policy: "#0d9488" };
// The investigator lists at most this many places per check (auditiq/investigator.py, SHOW); fewer means all of them.
const LISTED = 50;

function CheckCard({ check }: { check: InvestigationCheck }) {
  const [open, setOpen] = useState(check.status === "fail");
  return (
    <article className={`check-card check-${check.status}`}>
      <header onClick={() => setOpen((o) => !o)} role="button" aria-expanded={open} tabIndex={0} onKeyDown={(e) => (e.key === "Enter" || e.key === " ") && setOpen((o) => !o)}>
        <Badge tone={TONE[check.status]}>{LABEL[check.status]}</Badge>
        <div>
          <strong>{check.title}</strong> <span className="muted small">{check.standard}</span>
          <div className="small">{check.summary}</div>
        </div>
        {check.count > 0 && <span className="check-count">{count(check.count)}</span>}
      </header>
      {open && check.status !== "pass" && (
        <div className="check-body">
          {check.why && (
            <p className="small">
              <strong>Why it matters.</strong> {check.why}
            </p>
          )}
          {check.items.length > 0 && (
            <div className="table-wrap short">
              <table className="table compact">
                <thead>
                  <tr>
                    <th>Where</th>
                    <th>What</th>
                  </tr>
                </thead>
                <tbody>
                  {check.items.map((item, i) => (
                    <tr key={`${item.where}-${i}`}>
                      <td className="mono">{item.invoice_id ? <Link to={`/invoice/${item.invoice_id}`}>{item.where}</Link> : item.where}</td>
                      <td>{item.what}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          {check.items.length >= LISTED && check.count > check.items.length && <p className="muted small">The first {check.items.length} of {count(check.count)} are listed.</p>}
          <p className="small">
            <strong>What to do.</strong> {check.action}
          </p>
        </div>
      )}
    </article>
  );
}

/** Events of the engagement by day, one lane per kind. */
function Timeline({ report }: { report: Investigation }) {
  const lanes = useMemo(() => {
    const kinds = Object.keys(report.timeline.by_kind);
    const days = new Map<string, Record<string, number>>();
    for (const e of report.timeline.events) {
      const day = e.at.slice(0, 10);
      const row = days.get(day) ?? {};
      row[e.kind] = (row[e.kind] ?? 0) + 1;
      days.set(day, row);
    }
    return { kinds, days: [...days.entries()].sort((a, b) => a[0].localeCompare(b[0])) };
  }, [report]);
  if (!lanes.days.length) return <Empty>No events yet.</Empty>;
  const W = 640;
  const left = 80;
  const laneH = 28;
  const H = lanes.kinds.length * laneH + 30;
  const step = (W - left - 10) / Math.max(1, lanes.days.length);
  return (
    <svg className="lanes" viewBox={`0 0 ${W} ${H}`} role="img" aria-label="Timeline of runs, decisions, documents and policies by day">
      {lanes.kinds.map((kind, k) => (
        <g key={kind}>
          <text x={6} y={k * laneH + 20} className="row-label">
            {kind}
          </text>
          <line x1={left} x2={W - 10} y1={k * laneH + 16} y2={k * laneH + 16} className="grid-line" />
          {lanes.days.map(([day, row], i) =>
            row[kind] ? (
              <circle key={day} cx={left + i * step + step / 2} cy={k * laneH + 16} r={Math.min(11, 3 + Math.sqrt(row[kind]) * 2)} fill={KIND_COLORS[kind] ?? "#94a3b8"} opacity={0.8}>
                <title>{`${day}: ${row[kind]} ${kind} event(s)`}</title>
              </circle>
            ) : null,
          )}
        </g>
      ))}
      <text x={left} y={H - 6} className="axis-label">
        {lanes.days[0][0]}
      </text>
      <text x={W - 10} y={H - 6} textAnchor="end" className="axis-label">
        {lanes.days[lanes.days.length - 1][0]}
      </text>
    </svg>
  );
}

/** The trail investigator: an agent that audits the audit and reports what happened where. */
export function InvestigatorPage() {
  const report = useApi(() => api.investigation());
  const [showReport, setShowReport] = useState(false);
  if (report.loading && !report.data) return <Loading what="Investigating the audit record" />;
  if (report.error) return <ErrorBox error={report.error} onRetry={report.reload} />;
  const r = report.data;
  if (!r) return null;
  const download = () => {
    const blob = new Blob([r.markdown], { type: "text/markdown;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `investigation-${(r.scope.ledger ?? "store").replace(/[^A-Za-z0-9._-]+/g, "_")}.md`;
    a.click();
    URL.revokeObjectURL(url);
  };
  const tone = r.status.fail ? "bad" : r.status.attention ? "warn" : "good";
  return (
    <div className="page">
      <header className="page-head">
        <div>
          <span className="eyebrow">Intelligence · Trail investigator</span>
          <h1>Audit of the audit</h1>
          <p className="muted">
            An agent that reads the stored audit record and checks how the audit was done: whether anything was changed after the fact, whether every invoice was audited under the policy in force, whether each decision has a reason, was taken at a human pace and by someone independent of the transaction, and whether outcomes changed between audits without a cause. Every check is code over the store: the same store gives the same report.
          </p>
        </div>
        <div className="page-actions">
          <button className="btn" onClick={report.reload}>
            Investigate again
          </button>
          <button className="btn btn-primary" onClick={download}>
            Download the report (.md)
          </button>
        </div>
      </header>

      <div className={`banner ${tone === "good" ? "subtle" : ""}`} role="status">
        <strong>{r.verdict}</strong>
        <span className="muted small">generated {r.scope.generated}</span>
      </div>

      <div className="kpis">
        <Kpi label="Checks failed" value={count(r.status.fail ?? 0)} tone={r.status.fail ? "bad" : "default"} />
        <Kpi label="Need attention" value={count(r.status.attention ?? 0)} tone={r.status.attention ? "warn" : "default"} />
        <Kpi label="Passed" value={count(r.status.pass ?? 0)} tone="good" />
        <Kpi label="Results examined" value={count(r.scope.results)} hint={`${count(r.scope.runs)} runs · ${count(r.scope.trail_entries)} trail entries`} />
        <Kpi label="Decisions" value={count(r.scope.decisions)} hint={`${r.scope.reviewers} reviewer(s)`} />
      </div>

      <Panel title="Checks" subtitle="The failed ones open first; click a check to see where and what.">
        <div className="check-list">
          {r.checks.map((c) => (
            <CheckCard key={c.key} check={c} />
          ))}
        </div>
      </Panel>

      <div className="grid-2">
        <Panel title="Timeline" subtitle={`${count(r.timeline.total)} events: audit runs, review decisions (by day and reviewer), documents ingested and policies taking effect.`}>
          <Timeline report={r} />
          <ol className="story compact">
            {r.timeline.events.slice(-8).reverse().map((e, i) => (
              <li key={`${e.at}-${i}`}>
                <span className="story-dot" style={{ background: KIND_COLORS[e.kind] ?? "#94a3b8" }} aria-hidden />
                <div>
                  <span className="muted small mono">{e.at.slice(0, 16)}</span> <span className="story-kind">{e.kind}</span>
                  <div className="small">{e.what}</div>
                </div>
              </li>
            ))}
          </ol>
        </Panel>
        <Panel title="Reviewers" subtitle="Who decided what; clearances of critical invoices and decisions without a reason stand out.">
          {r.reviewers.length ? (
            <table className="table compact">
              <thead>
                <tr>
                  <th>Reviewer</th>
                  <th className="num">Decisions</th>
                  <th className="num">Approved</th>
                  <th className="num">Rejected</th>
                  <th className="num">Critical cleared</th>
                  <th className="num">No reason</th>
                </tr>
              </thead>
              <tbody>
                {r.reviewers.map((t) => (
                  <tr key={t.reviewer}>
                    <td>{t.reviewer}</td>
                    <td className="num">{count(t.decisions)}</td>
                    <td className="num">{count(t.approve ?? 0)}</td>
                    <td className="num">{count(t.reject ?? 0)}</td>
                    <td className={`num ${t.critical_cleared ? "warn-text" : ""}`}>{count(t.critical_cleared)}</td>
                    <td className={`num ${t.without_reason ? "bad-text" : ""}`}>{count(t.without_reason)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : (
            <Empty>No review decision has been recorded.</Empty>
          )}
          <dl className="facts">
            <div>
              <dt>Digest of the sealed runs</dt>
              <dd className="mono small" style={{ overflowWrap: "anywhere" }}>
                {r.scope.digest ?? "no sealed run"}
              </dd>
            </div>
          </dl>
        </Panel>
      </div>

      <Panel title="The report" actions={<button className="btn btn-ghost" onClick={() => setShowReport((s) => !s)}>{showReport ? "Hide" : "Show"} the text</button>}>
        {showReport ? <pre className="report-text">{r.markdown}</pre> : <p className="muted small">The same findings as text, ready for the working papers: download it above or show it here.</p>}
      </Panel>
    </div>
  );
}
