import { useEffect, useState, type FormEvent } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { api, waitForJob } from "../api/client";
import type { ConfigName, InvoiceDetail, Job, PackFlag, RecordMap } from "../api/types";
import { Badge, Empty, ErrorBox, JobProgress, Loading, Panel, RiskMeter, RouteBadge, SeverityBadge } from "../components/ui";
import { cell, inr, ratio, stateLabel } from "../lib/format";
import { useApi } from "../lib/useApi";

function Records({ title, record }: { title: string; record: RecordMap | null }) {
  if (!record) return <Empty>No {title.toLowerCase()} on record.</Empty>;
  return (
    <dl className="records">
      {Object.entries(record).map(([key, value]) => (
        <div key={key}>
          <dt>{key}</dt>
          <dd>{cell(value)}</dd>
        </div>
      ))}
    </dl>
  );
}

function RowsTable({ rows }: { rows: RecordMap[] }) {
  if (!rows.length) return <Empty>None on record.</Empty>;
  const columns = Object.keys(rows[0]);
  return (
    <div className="scroll-x">
      <table className="table compact">
        <thead>
          <tr>
            {columns.map((c) => (
              <th key={c}>{c}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={i}>
              {columns.map((c) => (
                <td key={c}>{cell(r[c])}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function FindingCard({ flag }: { flag: PackFlag }) {
  const terms = flag.confidence_terms;
  return (
    <article className="finding">
      <header>
        <strong>Rule {flag.clause}</strong> <span>{flag.title}</span>
        <SeverityBadge severity={flag.severity} />
        <Badge tone={flag.source === "control" ? "accent" : "violet"}>{flag.source}</Badge>
      </header>
      <p>{flag.message}</p>
      <div className="finding-meta">
        <span>Confidence {flag.confidence === null ? "n/a" : ratio(flag.confidence, 2)}</span>
        {terms && (
          <span className="muted">
            grounding {terms.g ?? "–"} · clause validity {terms.p ?? "–"} · agreement {terms.a === null ? "–" : ratio(terms.a, 2)}
          </span>
        )}
        {flag.citation && (
          <span className="cite">
            {flag.citation.document}, page {flag.citation.page}
          </span>
        )}
      </div>
      {flag.evidence.length > 0 && (
        <ul className="evidence">
          {flag.evidence.map((e, i) => (
            <li key={i}>
              <code>{e.field}</code> = {cell(e.value)}
            </li>
          ))}
        </ul>
      )}
      {flag.revision && (
        <div className="revision">
          <strong>Revision · {flag.revision.kind}</strong>
          <p>{flag.revision.action}</p>
          {flag.revision.changes.length > 0 && (
            <ul className="evidence">
              {flag.revision.changes.map((c, i) => (
                <li key={i}>
                  <code>{c.field}</code>: {cell(c.from)} → {cell(c.to)}
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </article>
  );
}

function DecisionForm({ resultId, onDone }: { resultId: number; onDone: () => void }) {
  const [decision, setDecision] = useState<"approve" | "reject" | "override">("approve");
  const me = useApi(() => api.me(), []).data;
  const account = me?.via === "account" ? me.name : null;      // signed in as a user: the decision carries the name
  const [typed, setTyped] = useState("");
  const reviewer = account ?? typed;
  const [justification, setJustification] = useState("");
  const [error, setError] = useState<Error | null>(null);
  const [busy, setBusy] = useState(false);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setError(null);
    if (!reviewer.trim()) return setError(new Error("Enter your name: every decision is recorded with the reviewer."));
    if (decision === "override" && !justification.trim()) return setError(new Error("An override needs a written justification."));
    setBusy(true);
    try {
      await api.decide(resultId, decision, reviewer.trim(), justification.trim());
      onDone();
    } catch (err) {
      setError(err as Error);
    } finally {
      setBusy(false);
    }
  };

  return (
    <form className="decision" onSubmit={submit} aria-label="Review decision">
      <fieldset>
        <legend>Decision</legend>
        {(
          [
            ["approve", "Approve", "The findings do not prevent payment."],
            ["reject", "Reject", "Not to be paid as submitted."],
            ["override", "Override", "Set the findings aside; needs a justification."],
          ] as const
        ).map(([value, label, help]) => (
          <label key={value} className={`choice ${decision === value ? "selected" : ""}`}>
            <input type="radio" name="decision" value={value} checked={decision === value} onChange={() => setDecision(value)} />
            <strong>{label}</strong>
            <span className="muted">{help}</span>
          </label>
        ))}
      </fieldset>
      <label>
        Reviewer
        <input value={reviewer} onChange={(e) => setTyped(e.target.value)} placeholder="Your name" readOnly={Boolean(account)} />
      </label>
      <label>
        Justification
        <textarea value={justification} onChange={(e) => setJustification(e.target.value)} rows={3} placeholder="Why, in a sentence or two" />
      </label>
      <ErrorBox error={error} />
      <button className="btn btn-primary" type="submit" disabled={busy}>
        {busy ? "Recording…" : "Record decision"}
      </button>
    </form>
  );
}

function InvoiceSearch() {
  const [params, setParams] = useSearchParams();
  const [q, setQ] = useState(params.get("q") ?? "");
  const query = params.get("q") ?? "";
  const found = useApi(() => api.invoices(query, 100), [query]);
  const navigate = useNavigate();
  return (
    <div className="page">
      <header className="page-head">
        <div>
          <h1>Invoices</h1>
          <p className="muted">Find an invoice by its id or its vendor, and open its audit pack.</p>
        </div>
      </header>
      <Panel>
        <form
          className="search"
          onSubmit={(e) => {
            e.preventDefault();
            const value = q.trim();
            if (/^INV\d+$/i.test(value)) navigate(`/invoice/${value.toUpperCase()}`);
            else setParams(value ? { q: value } : {});
          }}
        >
          <input type="search" value={q} onChange={(e) => setQ(e.target.value)} placeholder="INV40042 or a vendor name" aria-label="Invoice or vendor" />
          <button className="btn btn-primary" type="submit">
            Search
          </button>
        </form>
        <ErrorBox error={found.error} />
        {found.loading && !found.data ? (
          <Loading />
        ) : found.data?.items.length ? (
          <table className="table">
            <thead>
              <tr>
                <th>Invoice</th>
                <th>Vendor</th>
                <th>Date</th>
                <th className="num">Amount (₹)</th>
                <th>Route</th>
                <th>Status</th>
              </tr>
            </thead>
            <tbody>
              {found.data.items.map((i) => (
                <tr key={i.invoice_id}>
                  <td>
                    <Link to={`/invoice/${i.invoice_id}`} className="mono">
                      {i.invoice_id}
                    </Link>
                  </td>
                  <td>{i.vendor_name}</td>
                  <td>{i.date}</td>
                  <td className="num">{inr(i.amount, 2)}</td>
                  <td>
                    <RouteBadge route={i.route} />
                  </td>
                  <td className="muted">{stateLabel(i.workflow_status)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          <Empty>No invoice matches.</Empty>
        )}
      </Panel>
    </div>
  );
}

const TABS = ["Invoice", "Purchase order", "Goods receipt", "Vendor", "Approvals", "Vendor history"] as const;

function InvoiceView({ id }: { id: string }) {
  const [withLabel, setWithLabel] = useState(false);
  const detail = useApi<InvoiceDetail>(() => api.invoice(id, withLabel), [id, withLabel]);
  const health = useApi(() => api.health());
  const [tab, setTab] = useState<(typeof TABS)[number]>("Invoice");
  const [config, setConfig] = useState<ConfigName>("C1");
  const [job, setJob] = useState<Job | null>(null);
  const [auditError, setAuditError] = useState<Error | null>(null);

  useEffect(() => setTab("Invoice"), [id]);

  const runAudit = async () => {
    setAuditError(null);
    try {
      await waitForJob(await api.audit(id, config), setJob as (j: Job) => void, 1500);
      setJob(null);
      detail.reload();
    } catch (err) {
      setAuditError(err as Error);
      setJob(null);
    }
  };

  if (detail.loading && !detail.data) return <Loading what={`Reading ${id}`} />;
  if (detail.error) return <ErrorBox error={detail.error} onRetry={detail.reload} />;
  const d = detail.data;
  if (!d) return null;
  const result = d.result;
  const pack = result?.pack;
  const inv = d.records.invoice;
  const configs: ConfigName[] = health.data?.model ? ["C1", "C2", "C3", "C4", "C5"] : ["C1"];

  return (
    <div className="page">
      <header className="page-head">
        <div>
          <p className="crumbs">
            <Link to="/invoice">Invoices</Link> / <span className="mono">{id}</span>
          </p>
          <h1>
            <span className="mono">{id}</span> <RouteBadge route={result?.route} />
          </h1>
          <p className="muted">
            {cell(d.records.vendor?.vendor_name)} · {cell(inv.date)} · ₹{inr(inv.amount as number, 2)} · {stateLabel(result?.workflow_status)}
          </p>
        </div>
        <div className="page-actions audit-again">
          <select value={config} onChange={(e) => setConfig(e.target.value as ConfigName)} aria-label="Configuration">
            {configs.map((c) => (
              <option key={c} value={c}>
                {c}
              </option>
            ))}
          </select>
          <button className="btn" onClick={runAudit} disabled={Boolean(job)}>
            {result ? "Audit again" : "Audit now"}
          </button>
        </div>
      </header>
      <JobProgress job={job} />
      <ErrorBox error={auditError} />
      {!health.data?.model && <p className="muted small">C2 to C5 need a configured model; C1 uses the controls only.</p>}

      <div className="grid-2 wide-left">
        <div className="stack">
          {pack && result ? (
            <>
              <Panel title="Audit result" subtitle={`${result.configuration}${result.model ? ` with ${result.model}` : ""} under policy v${result.policy_version} · run ${result.run_id} · ${result.created_at}`}>
                <div className="scores">
                  <div>
                    <span className="muted">Count-based risk</span>
                    <RiskMeter score={result.r0} />
                  </div>
                  <div>
                    <span className="muted">Confidence-weighted risk</span>
                    <RiskMeter score={result.rc} />
                  </div>
                </div>
                <p className="action">{pack.recommended_action}</p>
              </Panel>
              <Panel title={`Findings (${pack.flags.length})`}>
                {pack.flags.length ? pack.flags.map((f, i) => <FindingCard key={`${f.clause}-${i}`} flag={f} />) : <Empty>No finding: every check passed.</Empty>}
              </Panel>
              {pack.removed_by_challenger.length > 0 && (
                <Panel title="Removed by the challenger" subtitle="Findings an agent raised that the challenger rejected, with its reason. They do not count.">
                  {pack.removed_by_challenger.map((r, i) => (
                    <article key={i} className="finding removed">
                      <header>
                        <strong>Rule {r.clause}</strong> <span className="muted">{r.agent}</span>
                      </header>
                      <p>{r.message}</p>
                      <p className="muted">Reason: {r.reason}</p>
                    </article>
                  ))}
                </Panel>
              )}
            </>
          ) : (
            <Panel title="Audit result">
              <Empty>This invoice has not been audited yet.</Empty>
            </Panel>
          )}

          <Panel title="Records">
            <div className="tabs" role="tablist">
              {TABS.map((t) => (
                <button key={t} role="tab" aria-selected={tab === t} className={tab === t ? "active" : ""} onClick={() => setTab(t)}>
                  {t}
                </button>
              ))}
            </div>
            {tab === "Invoice" && <Records title="Invoice" record={inv} />}
            {tab === "Purchase order" && <Records title="Purchase order" record={d.records.po} />}
            {tab === "Goods receipt" && <Records title="Goods receipt" record={d.records.grn} />}
            {tab === "Vendor" && <Records title="Vendor" record={d.records.vendor} />}
            {tab === "Approvals" && <RowsTable rows={d.records.approvals} />}
            {tab === "Vendor history" && (
              <>
                <p className="muted small">
                  {d.history.total} other invoices of this vendor; the latest {Math.min(40, d.history.total)} are shown.
                </p>
                <RowsTable rows={d.history.items} />
              </>
            )}
          </Panel>
        </div>

        <div className="stack">
          {result?.workflow_status === "PENDING_REVIEW" ? (
            <Panel title="Your decision" subtitle="Recorded with your name, added to the audit pack and to the audit trail.">
              <DecisionForm resultId={result.result_id} onDone={detail.reload} />
            </Panel>
          ) : pack?.review ? (
            <Panel title="Review">
              <p>
                <strong>{pack.review.decision}</strong> by {pack.review.reviewer} on {pack.review.decided_at}
              </p>
              {pack.review.justification && <p className="muted">{pack.review.justification}</p>}
            </Panel>
          ) : null}
          {result && (
            <Panel title="Audit trail" subtitle="Every step, in order: what ran, who or what did it, what it cost.">
              <ol className="trail">
                {result.trail.map((t) => (
                  <li key={t.seq}>
                    <span className={`trail-dot trail-${t.stage}`} />
                    <div>
                      <strong>{t.stage}</strong> <span className="muted">{t.actor}</span>
                      <div className="small">{t.detail}</div>
                      {t.prompt_tokens ? (
                        <div className="muted small">
                          {t.prompt_tokens.toLocaleString("en-IN")} tokens in · {t.completion_tokens} out · {((t.latency_ms ?? 0) / 1000).toFixed(1)} s
                        </div>
                      ) : null}
                    </div>
                  </li>
                ))}
              </ol>
            </Panel>
          )}
          <Panel title="Benchmark answer key" subtitle="Synthetic ledgers only: what was injected into this invoice. The audit never reads it.">
            <label className="toggle">
              <input type="checkbox" checked={withLabel} onChange={(e) => setWithLabel(e.target.checked)} /> Show
            </label>
            {withLabel && d.benchmark_label && (
              <dl className="records">
                <div>
                  <dt>label</dt>
                  <dd>{d.benchmark_label.label}</dd>
                </div>
                <div>
                  <dt>class</dt>
                  <dd>{d.benchmark_label.class_id || d.benchmark_label.hard_negative_type || "–"}</dd>
                </div>
                <div>
                  <dt>rules</dt>
                  <dd>{d.benchmark_label.clause_ids || "–"}</dd>
                </div>
                <div>
                  <dt>note</dt>
                  <dd>{d.benchmark_label.note || "–"}</dd>
                </div>
              </dl>
            )}
          </Panel>
        </div>
      </div>
    </div>
  );
}

export function InvoicePage() {
  const { id } = useParams();
  return id ? <InvoiceView id={id.toUpperCase()} /> : <InvoiceSearch />;
}
