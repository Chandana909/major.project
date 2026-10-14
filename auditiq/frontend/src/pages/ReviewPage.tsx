import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api/client";
import { Empty, ErrorBox, Loading, Panel, RiskMeter, RouteBadge } from "../components/ui";
import { inr } from "../lib/format";
import { useApi } from "../lib/useApi";

export function ReviewPage() {
  const queue = useApi(() => api.queue(2000));
  const [filter, setFilter] = useState("");
  const [level, setLevel] = useState("all");

  const items = useMemo(() => {
    const q = filter.trim().toLowerCase();
    return (queue.data?.items ?? []).filter(
      (i) =>
        (level === "all" || i.risk_level === level) &&
        (!q || i.invoice_id.toLowerCase().includes(q) || i.vendor_name.toLowerCase().includes(q)),
    );
  }, [queue.data, filter, level]);

  return (
    <div className="page">
      <header className="page-head">
        <div>
          <h1>Review queue</h1>
          <p className="muted">
            {queue.data ? `${queue.data.total.toLocaleString("en-IN")} invoices are waiting for a reviewer, highest weighted risk first.` : "Invoices escalated to a reviewer."}
          </p>
        </div>
      </header>
      <ErrorBox error={queue.error} onRetry={queue.reload} />
      <Panel
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
          <table className="table">
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
                  <td className="num">{inr(i.amount, 2)}</td>
                  <td>
                    <RouteBadge route={i.route} />
                  </td>
                  <td>
                    <RiskMeter score={i.rc} />
                  </td>
                  <td className="num">{i.flag_count}</td>
                  <td>{i.configuration}</td>
                </tr>
              ))}
            </tbody>
          </table>
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
