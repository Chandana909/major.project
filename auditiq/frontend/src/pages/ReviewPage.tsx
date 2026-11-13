import { useMemo, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api } from "../api/client";
import { Empty, ErrorBox, Loading, Panel, RiskMeter, RouteBadge, RuleChips } from "../components/ui";
import { count, inr, RISK_COLORS, rupeesCompact } from "../lib/format";
import type { RiskLevel } from "../api/types";

const LEVELS: RiskLevel[] = ["CRITICAL", "HIGH", "MEDIUM", "LOW"];
import { useApi } from "../lib/useApi";
import { QueueConstellation } from "../three/QueueConstellation";

export function ReviewPage() {
  const [filter, setFilter] = useState("");
  const [level, setLevel] = useState("all");
  // The list holds at most 2,000 invoices, riskiest first; a level asked for is read from the server, and the
  // counts per level come from the whole queue, not from the list.
  const queue = useApi(() => api.queue(2000, level === "all" ? undefined : level), [level]);
  const overview = useApi(() => api.overview());
  const o = overview.data;
  const navigate = useNavigate();

  const items = useMemo(() => {
    const q = filter.trim().toLowerCase();
    return (queue.data?.items ?? []).filter(
      (i) =>
        (level === "all" || i.risk_level === level) &&
        (!q || i.invoice_id.toLowerCase().includes(q) || i.vendor_name.toLowerCase().includes(q)),
    );
  }, [queue.data, filter, level]);

  // Per risk level: how many invoices wait and the amount they put at stake.
  const levels = useMemo(() => {
    const all = queue.data?.items ?? [];
    const totals = queue.data?.levels;
    return LEVELS.map((l) => {
      if (totals) return { level: l, count: totals[l]?.invoices ?? 0, amount: totals[l]?.amount ?? 0 };
      const of = all.filter((i) => i.risk_level === l);
      return { level: l, count: of.length, amount: of.reduce((t, i) => t + i.amount, 0) };
    });
  }, [queue.data]);
  const exposure = levels.reduce((t, l) => t + l.amount, 0);
  const waiting = levels.reduce((t, l) => t + l.count, 0);

  return (
    <div className="page">
      <header className="page-head">
        <div>
          <span className="eyebrow">Audit · Review queue</span>
          <h1>Review queue</h1>
          <p className="muted">
            {queue.data ? `${waiting.toLocaleString("en-IN")} invoices are waiting for a reviewer, highest weighted risk first.` : "Invoices escalated to a reviewer."}
          </p>
          {o && o.audited > 0 && (
            <p className="muted small" aria-label="Share of the audit">
              {count(o.states.PENDING_REVIEW ?? 0)} of the {count(o.audited)} audited invoices ({(((o.states.PENDING_REVIEW ?? 0) / o.audited) * 100).toFixed(1)}%) wait for a
              person; {count(o.states.AUTO_APPROVED ?? 0)} were approved automatically
              {o.coverage?.approved_with_findings ? `, ${count(o.coverage.approved_with_findings)} of them with a medium or low finding recorded on the invoice` : ""}. Only
              a critical or high finding, or a high score from several findings, sends an invoice here.
            </p>
          )}
        </div>
      </header>
      <ErrorBox error={queue.error} onRetry={queue.reload} />
      {queue.data && queue.data.items.length > 0 && (
        <div className="level-strip" role="group" aria-label="Filter by risk level">
          <button className={`level-card ${level === "all" ? "active" : ""}`} onClick={() => setLevel("all")}>
            <span className="kpi-label">All waiting</span>
            <strong>{waiting.toLocaleString("en-IN")}</strong>
            <span className="muted small">{rupeesCompact(exposure)} at stake</span>
          </button>
          {levels.map((l) => (
            <button key={l.level} className={`level-card ${level === l.level ? "active" : ""}`} onClick={() => setLevel(l.level)} disabled={!l.count && level !== l.level}>
              <span className="kpi-label">
                <i style={{ background: RISK_COLORS[l.level] }} />
                {l.level.charAt(0) + l.level.slice(1).toLowerCase()}
              </span>
              <strong>{l.count.toLocaleString("en-IN")}</strong>
              <span className="muted small">{rupeesCompact(l.amount)} · {exposure ? ((l.amount / exposure) * 100).toFixed(0) : 0}% of the amount</span>
              <span className="level-bar" aria-hidden>
                <i style={{ width: `${exposure ? (l.amount / exposure) * 100 : 0}%`, background: RISK_COLORS[l.level] }} />
              </span>
            </button>
          ))}
        </div>
      )}
      {queue.data && items.length > 0 && (
        <Panel
          title="Queue constellation"
          subtitle="Every invoice in the list below. Each sector is the most severe rule the invoice breaks; height is its weighted risk; size grows with the amount; the riskiest pulse. Click a point to open the invoice."
        >
          <QueueConstellation items={items} rules={queue.data.rules} onSelect={(i) => navigate(`/invoice/${i.invoice_id}`)} />
          <div className="legend">
            <span><i style={{ background: RISK_COLORS.LOW }} /> risk below 30</span>
            <span><i style={{ background: RISK_COLORS.MEDIUM }} /> 30 to 49</span>
            <span><i style={{ background: RISK_COLORS.HIGH }} /> 50 to 69</span>
            <span><i style={{ background: RISK_COLORS.CRITICAL }} /> 70 and above</span>
          </div>
        </Panel>
      )}
      <Panel
        title="Waiting invoices"
        subtitle={`${items.length.toLocaleString("en-IN")} shown${queue.data && queue.data.items.length < queue.data.total ? `, the riskiest ${queue.data.items.length.toLocaleString("en-IN")} of the ${queue.data.total.toLocaleString("en-IN")} ${level === "all" ? "" : `${level.toLowerCase()} `}invoices waiting` : ""} · weighted risk, then date. The chips are the rules each invoice breaks, the most severe first.`}
        actions={
          <div className="filters">
            <input type="search" placeholder="Invoice or vendor" value={filter} onChange={(e) => setFilter(e.target.value)} aria-label="Filter the queue" />
            <select value={level} onChange={(e) => setLevel(e.target.value)} aria-label="Risk level">
              <option value="all">All risk levels</option>
              <option value="CRITICAL">Critical</option>
              <option value="HIGH">High</option>
              <option value="MEDIUM">Medium</option>
              <option value="LOW">Low</option>
            </select>
          </div>
        }
      >
        {queue.loading && !queue.data ? (
          <Loading what="Reading the queue" />
        ) : items.length ? (
          <div className="table-wrap">
          <table className="table sticky">
            <thead>
              <tr>
                <th>Invoice</th>
                <th>Vendor</th>
                <th>Date</th>
                <th className="num">Amount (₹)</th>
                <th>Route</th>
                <th>Weighted risk</th>
                <th className="num">Findings</th>
                <th>Configuration</th>
              </tr>
            </thead>
            <tbody>
              {items.map((i) => (
                <tr key={i.result_id}>
                  <td>
                    <Link to={`/invoice/${i.invoice_id}`} className="mono">
                      {i.invoice_id}
                    </Link>
                  </td>
                  <td>{i.vendor_name}</td>
                  <td>{i.invoice_date}</td>
                  <td className="num strong">{inr(i.amount, 2)}</td>
                  <td>
                    <RouteBadge route={i.route} />
                  </td>
                  <td>
                    <RiskMeter score={i.rc} />
                    <RuleChips rules={i.rules} titles={queue.data?.rules} />
                  </td>
                  <td className="num">{i.flag_count}</td>
                  <td>
                    <span className="config">{i.configuration}</span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          </div>
        ) : (
          <Empty>{queue.data?.total ? "No invoice matches the filter." : "Nothing is waiting for review."}</Empty>
        )}
        {queue.data && queue.data.total > (queue.data.items.length ?? 0) && (
          <p className="muted small">Showing the first {queue.data.items.length.toLocaleString("en-IN")} by risk.</p>
        )}
      </Panel>
    </div>
  );
}
