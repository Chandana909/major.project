import { useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api/client";
import { RiskBadge } from "../components/InvoiceInsight";
import { Empty, ErrorBox, Kpi, Loading, Panel, StackedBar } from "../components/ui";
import { count, inr } from "../lib/format";
import { useApi } from "../lib/useApi";

const CATEGORY_COLORS: Record<string, string> = {
  invoice_submission: "#34d399",
  payment_reminder: "#60a5fa",
  quantity_query: "#fbbf24",
  bank_change: "#f87171",
  other: "#cbd5e1",
};
const SIGNAL_TITLES: Record<string, string> = {
  lookalike_domain: "Look-alike domain",
  new_domain: "New sender domain",
  urgency: "Urgency",
  secrecy: "Asks not to be called",
  account_change: "Bank account change",
  money_at_risk: "Names an unpaid invoice",
  addresses_a_model: "Addresses an AI system",
};

/** Vendor e-mails judged by code: what each asks for, and which ones try to redirect a payment. */
export function MailPage() {
  const mail = useApi(() => api.mail());
  const [selected, setSelected] = useState<string | null>(null);
  if (mail.loading && !mail.data) return <Loading what="Triaging the vendor mailbox" />;
  if (mail.error) return <ErrorBox error={mail.error} onRetry={mail.reload} />;
  const m = mail.data;
  if (!m) return null;
  const open = m.alerts.find((a) => a.message_id === selected) ?? m.alerts[0];
  return (
    <div className="page">
      <header className="page-head">
        <div>
          <span className="eyebrow">Intelligence · Mail triage</span>
          <h1>Vendor e-mail triage</h1>
          <p className="muted">
            Every vendor e-mail in the store, read by code: what it asks for, and the signals of business e-mail compromise (a domain that reads like the vendor's but is not it, pressure, a request not to call back, a new bank account for an unpaid invoice). A request to pay elsewhere is held until it is confirmed by telephone with the contact on the vendor master. Text written to instruct an AI system is quarantined from every model prompt.
          </p>
        </div>
      </header>
      {!m.emails ? (
        <Empty>
          No vendor e-mail is stored. They arrive through the Kafka e-mail topic, or load an mbox file: <code>python -m auditiq mail load mailbox.mbox</code>.
        </Empty>
      ) : (
        <>
          <div className="kpis">
            <Kpi label="E-mails" value={count(m.emails)} hint={`${count(m.linked)} linked to an invoice`} />
            <Kpi label="Payment redirection" value={count(m.by_risk.high ?? 0)} tone={m.by_risk.high ? "bad" : "good"} hint="high risk: hold the payment" />
            <Kpi label="To confirm" value={count(m.by_risk.medium ?? 0)} tone={m.by_risk.medium ? "warn" : "default"} hint="bank changes from the vendor's own domain" />
            <Kpi label="Payments to hold" value={`₹${inr(m.hold_amount)}`} tone={m.holds.length ? "bad" : "default"} hint={`${count(m.holds.length)} invoice(s)`} />
          </div>
          <div className="grid-2">
            <Panel title="What the mailbox holds">
              <StackedBar
                label="E-mails by category"
                parts={Object.entries(m.by_category).map(([k, v]) => ({ key: k, label: m.titles[k] ?? k, value: v, color: CATEGORY_COLORS[k] ?? "#94a3b8" }))}
              />
            </Panel>
            <Panel title="Signals found" subtitle="An e-mail can carry several.">
              <ul className="barlist">
                {Object.entries(m.signals).map(([k, v]) => (
                  <li key={k}>
                    <span className="barlist-label">{SIGNAL_TITLES[k] ?? k}</span>
                    <span className="barlist-track">
                      <span className="barlist-fill" style={{ width: `${m.emails ? Math.max(v ? 1.5 : 0, (v / m.emails) * 100) : 0}%`, background: k === "lookalike_domain" ? "#dc2626" : "#7c3aed" }} />
                    </span>
                    <span className="barlist-value">{count(v)}</span>
                  </li>
                ))}
              </ul>
            </Panel>
          </div>
          <div className="grid-2 wide-left">
            <Panel title={`Alerts (${count(m.alerts_total)})`} subtitle="High risk first: the e-mails to act on before paying.">
              {m.alerts.length ? (
                <div className="table-wrap short">
                  <table className="table sticky compact">
                    <thead>
                      <tr>
                        <th>Risk</th>
                        <th>Sent</th>
                        <th>From</th>
                        <th>Subject</th>
                        <th>Invoice</th>
                      </tr>
                    </thead>
                    <tbody>
                      {m.alerts.map((a) => (
                        <tr key={a.message_id} className={open?.message_id === a.message_id ? "highlight" : ""} onClick={() => setSelected(a.message_id)} style={{ cursor: "pointer" }}>
                          <td>
                            <RiskBadge risk={a.risk} />
                          </td>
                          <td className="mono small">{a.sent_at.slice(0, 16)}</td>
                          <td className="mono small">{a.sender}</td>
                          <td>{a.subject}</td>
                          <td>{a.invoice_id ? <Link className="mono" to={`/invoice/${a.invoice_id}`}>{a.invoice_id}</Link> : "–"}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              ) : (
                <Empty>No e-mail needs action.</Empty>
              )}
            </Panel>
            <Panel title="Why">
              {open ? (
                <div className="stack">
                  <p>
                    <RiskBadge risk={open.risk} /> <span className="muted small">{m.titles[open.category] ?? open.category}</span>
                  </p>
                  <p className="small mono">{open.sender}</p>
                  <ul className="small">
                    {open.reasons.map((r) => (
                      <li key={r}>{r}</li>
                    ))}
                  </ul>
                  <p className="action">{open.action}</p>
                </div>
              ) : (
                <Empty>Select an alert.</Empty>
              )}
            </Panel>
          </div>
          {m.holds.length > 0 && (
            <Panel title="Payments to hold" subtitle="Unpaid invoices named by a high-risk request to pay into another account.">
              <table className="table compact">
                <thead>
                  <tr>
                    <th>Invoice</th>
                    <th>Vendor</th>
                    <th className="num">Amount</th>
                    <th>Request from</th>
                    <th>Subject</th>
                  </tr>
                </thead>
                <tbody>
                  {m.holds.map((h) => (
                    <tr key={h.invoice_id}>
                      <td>
                        <Link className="mono" to={`/invoice/${h.invoice_id}`}>
                          {h.invoice_id}
                        </Link>
                      </td>
                      <td className="mono">{h.vendor_id}</td>
                      <td className="num">₹{inr(h.amount)}</td>
                      <td className="mono small">{h.sender}</td>
                      <td>{h.subject}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </Panel>
          )}
        </>
      )}
    </div>
  );
}
