import { useState, type FormEvent } from "react";
import { Link } from "react-router-dom";
import { api } from "../api/client";
import type { LeadKey, MonetaryUnitSample, Reliability, TrailCheck } from "../api/types";
import { Badge, Empty, ErrorBox, Kpi, Loading, Panel } from "../components/ui";
import { count, inr, percent, rupeesCompact } from "../lib/format";
import { useApi } from "../lib/useApi";

const invoiceLink = (id: string) => (
  <Link className="mono" to={`/invoice/${id}`}>
    {id}
  </Link>
);

/** Recompute every seal of the stored audit record and say whether anything was changed after it was stored. */
function SealedRecord() {
  const [check, setCheck] = useState<TrailCheck | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<Error | null>(null);
  const verify = async () => {
    setBusy(true);
    setError(null);
    try {
      setCheck(await api.trailVerify());
    } catch (err) {
      setError(err as Error);
    } finally {
      setBusy(false);
    }
  };
  const altered = check ? check.results.altered + check.results.review_inconsistent + check.entries.broken + check.runs.altered : 0;
  return (
    <Panel
      title="The sealed audit record"
      subtitle="Every stored result is sealed with a SHA-256 hash over its decision, its findings and its audit pack; every audit-trail entry, the reviewer's decision included, is chained to the hash before it; every finished run is sealed over its results. Verifying computes them all again from what the store holds now (ISA 230: audit documentation is not changed after the fact)."
      actions={
        <button className="btn btn-primary" onClick={() => void verify()} disabled={busy}>
          {busy ? "Verifying…" : check ? "Verify again" : "Verify the record"}
        </button>
      }
    >
      <ErrorBox error={error} onRetry={() => void verify()} />
      {!check && !busy && <Empty>Not verified yet. Verifying reads every result, finding and trail entry of the store.</Empty>}
      {busy && !check && <Loading what="Recomputing the seals" />}
      {check && (
        <>
          <div className="kpis">
            <Kpi label="Record" value={check.intact ? "Intact" : "Altered"} tone={check.intact ? "good" : "bad"} hint={check.intact ? "nothing stored has been changed" : `${count(altered)} item(s) no longer match their seals`} />
            <Kpi label="Results sealed" value={count(check.results.sealed)} hint={`of ${count(check.results.checked)} · ${count(check.results.altered)} altered · ${count(check.results.unsealed)} stored before sealing`} tone={check.results.altered ? "bad" : "default"} />
            <Kpi label="Trail entries" value={count(check.entries.checked)} hint={`${count(check.entries.broken)} broken · ${count(check.entries.unsealed)} stored before sealing`} tone={check.entries.broken ? "bad" : "default"} />
            <Kpi label="Runs sealed" value={count(check.runs.sealed)} hint={`${count(check.runs.altered)} altered · ${count(check.runs.open)} open · ${count(check.runs.unsealed)} before sealing`} tone={check.runs.altered ? "bad" : "default"} />
          </div>
          {check.results.altered_ids.length > 0 && <p className="bad-text small">Altered results: {check.results.altered_ids.join(", ")}</p>}
          {check.results.review_inconsistent_ids.length > 0 && (
            <p className="bad-text small">Results whose state is not the decision their trail records: {check.results.review_inconsistent_ids.join(", ")}</p>
          )}
          {check.entries.broken_ids.length > 0 && <p className="bad-text small">Broken trail entries (the first is where the change was made): {check.entries.broken_ids.join(", ")}</p>}
          {check.runs.altered_ids.length > 0 && <p className="bad-text small">Runs whose results changed after they were sealed: {check.runs.altered_ids.join(", ")}</p>}
          {check.evidence && (
            <p className={`small ${check.evidence.changed ? "bad-text" : "muted"}`}>
              <strong>Evidence:</strong> {count(check.evidence.unchanged)} of {count(check.evidence.fingerprinted)} fingerprinted latest results still match the records in the ledger
              {check.evidence.changed
                ? `; ${count(check.evidence.changed)} were based on records changed since (${Object.entries(check.evidence.changed_by_record)
                    .filter(([, n]) => n)
                    .map(([part, n]) => `${part} ${n}`)
                    .join(", ")}) and should be audited again: ${check.evidence.changed_invoices
                    .slice(0, 8)
                    .map((c) => c.invoice_id)
                    .join(", ")}`
                : ""}
              {check.evidence.without_fingerprint ? ` · ${count(check.evidence.without_fingerprint)} results were stored before evidence was fingerprinted` : ""}.
            </p>
          )}
          {check.digest && (
            <dl className="facts">
              <div>
                <dt>Digest of every sealed run</dt>
                <dd className="mono small" style={{ overflowWrap: "anywhere" }}>
                  {check.digest}
                </dd>
              </div>
              <div>
                <dt>Keep it outside the store</dt>
                <dd className="small muted">Sent to the auditee or printed in the report, it shows later that no sealed run was changed or deleted, which the store cannot show about itself.</dd>
              </div>
            </dl>
          )}
        </>
      )}
    </Panel>
  );
}

/** A monetary-unit sample of the invoices approved without a person, with its plan and, on a benchmark ledger, its evaluation. */
function StatisticalSample() {
  const [confidence, setConfidence] = useState("0.95");
  const [tolerable, setTolerable] = useState("2");
  const [expected, setExpected] = useState("0");
  const [seed, setSeed] = useState("");
  const [sample, setSample] = useState<MonetaryUnitSample | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<Error | null>(null);
  const draw = async (e?: FormEvent) => {
    e?.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const out = await api.sampling({ confidence: Number(confidence), tolerable_pct: Number(tolerable), expected_pct: Number(expected), seed: seed ? Number(seed) : null });
      setSample(out);
      setSeed(String(out.seed));
    } catch (err) {
      setError(err as Error);
    } finally {
      setBusy(false);
    }
  };
  const p = sample?.plan;
  const key = sample?.answer_key;
  const anomalous = new Set(key?.sampled_anomalous ?? []);
  return (
    <Panel
      title="Statistical sample of the approved invoices (ISA 530)"
      subtitle="Monetary-unit sampling: every rupee approved without a person has the same chance to be drawn, so large invoices are examined more often and one of at least the sampling interval always is. The sample size follows from the confidence and the tolerable and expected misstatement; the Stringer bound turns what the examination finds into an upper limit on the misstatement of the whole approved population."
    >
      <form className="form-grid" onSubmit={(e) => void draw(e)}>
        <label>
          Confidence
          <select value={confidence} onChange={(e) => setConfidence(e.target.value)} aria-label="Confidence">
            <option value="0.9">90%</option>
            <option value="0.95">95%</option>
            <option value="0.99">99%</option>
          </select>
        </label>
        <label>
          Tolerable misstatement (% of the approved amount)
          <input type="number" min="0.1" max="20" step="0.1" value={tolerable} onChange={(e) => setTolerable(e.target.value)} aria-label="Tolerable misstatement" />
        </label>
        <label>
          Expected misstatement (%)
          <input type="number" min="0" max="10" step="0.1" value={expected} onChange={(e) => setExpected(e.target.value)} aria-label="Expected misstatement" />
        </label>
        <label>
          Seed of the random start (empty: a new one)
          <input type="number" min="1" value={seed} onChange={(e) => setSeed(e.target.value)} aria-label="Seed" />
        </label>
        <div className="row">
          <button className="btn btn-primary" type="submit" disabled={busy}>
            {busy ? "Drawing…" : "Draw the sample"}
          </button>
        </div>
      </form>
      <ErrorBox error={error} />
      {!sample && !busy && <Empty>No sample drawn yet.</Empty>}
      {sample && p && (
        <>
          <div className="kpis">
            <Kpi label="Approved population" value={rupeesCompact(p.book_value)} hint={`${count(p.items)} invoices approved without a person`} />
            <Kpi label="Tolerable misstatement" value={rupeesCompact(p.tolerable)} hint={`${p.tolerable_pct}% · expected ${p.expected_pct}%`} />
            <Kpi label="Sample size" value={count(p.size)} hint={`R(0) = ${p.reliability_factor.toFixed(2)} at ${percent(p.confidence, 0)} confidence`} tone="accent" />
            <Kpi label="Sampling interval" value={rupeesCompact(p.interval)} hint={`random start ₹${inr(sample.start)} · seed ${sample.seed}`} />
            <Kpi label="Invoices drawn" value={count(sample.drawn)} hint={`${count(sample.certain)} drawn with certainty (at least the interval)`} />
          </div>
          {key && (
            <div className={key.upper_limit <= p.tolerable ? "notice" : "error"} role="status" style={{ margin: "14px 0" }}>
              <strong>Examined against the answer key:</strong> {count(key.misstatements)} of the drawn invoices are anomalous; projected misstatement {rupeesCompact(key.projected)}, upper
              limit {rupeesCompact(key.upper_limit)} against a tolerable {rupeesCompact(p.tolerable)}: {key.conclusion}. The true anomalous amount among the approved invoices is{" "}
              {rupeesCompact(key.true_misstatement)}; the bound {key.bound_holds ? "holds" : "does not hold"} for this draw.
            </div>
          )}
          <div className="table-wrap">
            <table className="table sticky compact">
              <thead>
                <tr>
                  <th>Invoice</th>
                  <th>Vendor</th>
                  <th>Date</th>
                  <th className="num">Amount</th>
                  <th className="num">Units</th>
                  <th>Drawn</th>
                  <th className="num">Findings</th>
                  {key && <th>Answer key</th>}
                </tr>
              </thead>
              <tbody>
                {sample.sample.map((s) => (
                  <tr key={s.invoice_id}>
                    <td>{invoiceLink(s.invoice_id)}</td>
                    <td>{s.vendor_name ?? <span className="muted">unknown</span>}</td>
                    <td>{s.date?.slice(0, 10)}</td>
                    <td className="num">₹{inr(s.amount)}</td>
                    <td className="num">{s.units}</td>
                    <td>{s.certain ? <Badge tone="accent">certain</Badge> : <span className="muted small">by chance</span>}</td>
                    <td className="num">{s.findings}</td>
                    {key && <td>{anomalous.has(s.invoice_id) ? <Badge tone="bad">anomalous</Badge> : <span className="muted small">clean</span>}</td>}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
    </Panel>
  );
}

function KeyLine({ clause, k }: { clause: string; k?: LeadKey }) {
  if (!k) return null;
  const other = Object.entries(k.listed_otherwise);
  return (
    <p className="small muted">
      Answer key, rule {clause}: {count(k.listed_labelled)} of {count(k.labelled)} labelled invoices listed (recall {percent(k.recall)}), precision {percent(k.precision)}
      {other.length ? ` · also listed: ${other.map(([what, n]) => `${what} ${n}`).join(", ")}` : " · nothing else listed, no hard negative among them"}.
    </p>
  );
}

/** Invoices for a reviewer under the two judgement rules the policy words most precisely. */
function JudgementLeads() {
  const data = useApi(() => api.leads());
  const d = data.data;
  const key = d?.answer_key && d.answer_key.compared ? d.answer_key : null;
  return (
    <Panel
      title="Leads under the judgement rules"
      subtitle="Two judgement rules are worded closely enough for code to list the invoices that fit them, with the policy's own guide values: near duplicates (2.2.2) and structuring across days (4.1.2). A controls-only audit approves these invoices; a lead is not a finding and changes no result. It is a list for a reviewer, who decides whether the wording fits."
    >
      <ErrorBox error={data.error} onRetry={data.reload} />
      {!d && data.loading && <Loading what="Reading the ledger for leads" />}
      {d && (
        <>
          <div className="kpis">
            <Kpi label="Near duplicates (2.2.2)" value={count(d.near_duplicates.invoices)} hint={`${rupeesCompact(d.near_duplicates.amount)} · ${count(d.near_duplicates.approved)} approved without a person`} tone={d.near_duplicates.invoices ? "warn" : "good"} />
            <Kpi label="Structuring groups (4.1.2)" value={count(d.structuring.count)} hint={`${count(d.structuring.invoices)} invoices · ${rupeesCompact(d.structuring.amount)} · ${count(d.structuring.approved)} approved without a person`} tone={d.structuring.count ? "warn" : "good"} />
            <Kpi label="Guide window" value={`${d.guide.window_days} days`} hint={`band ${d.guide.band_pct}% under the approving role's limit · policy v${d.policy_version ?? "?"}`} />
          </div>
          <h3>Near duplicates</h3>
          <p className="small muted">The same vendor, PO, GRN and amount as an earlier invoice, under a re-keyed form of its number (case, separators, leading zeros, a suffix, one substituted or transposed character). Consecutive numbers for separate deliveries are not listed.</p>
          <KeyLine clause="2.2.2" k={key?.["2.2.2"]} />
          {d.near_duplicates.pairs.length ? (
            <div className="table-wrap short">
              <table className="table sticky compact">
                <thead>
                  <tr>
                    <th>Invoice</th>
                    <th>Number</th>
                    <th>Earlier invoice</th>
                    <th>Its number</th>
                    <th>Vendor</th>
                    <th className="num">Amount</th>
                    <th>PO · GRN</th>
                    <th>Why</th>
                  </tr>
                </thead>
                <tbody>
                  {d.near_duplicates.pairs.map((p) => (
                    <tr key={p.invoice_id}>
                      <td>
                        {invoiceLink(p.invoice_id)} <span className="muted small">{p.date}</span>
                      </td>
                      <td className="mono">{p.number}</td>
                      <td>
                        {invoiceLink(p.original_id)} <span className="muted small">{p.original_date}</span>
                      </td>
                      <td className="mono">{p.original_number}</td>
                      <td>{p.vendor_name}</td>
                      <td className="num">₹{inr(p.amount, 2)}</td>
                      <td className="mono small">
                        {p.po_id} · {p.grn_id}
                      </td>
                      <td className="small">{p.reason}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <Empty>No invoice bills a receipt again under a re-keyed number.</Empty>
          )}
          <h3>Structuring across days</h3>
          <p className="small muted">
            Invoices of one vendor approved by one role, on different days within {d.guide.window_days} days, each within {d.guide.band_pct}% under that role's limit and together above it. The
            rule also asks for the same goods, which may be worded differently: the descriptions are shown for the reviewer to judge.
          </p>
          <KeyLine clause="4.1.2" k={key?.["4.1.2"]} />
          {d.structuring.groups.length ? (
            <div className="table-wrap short">
              <table className="table sticky compact">
                <thead>
                  <tr>
                    <th>Vendor</th>
                    <th>Approved by</th>
                    <th className="num">Limit</th>
                    <th>Invoices</th>
                    <th>Period</th>
                    <th className="num">Together</th>
                    <th>Descriptions</th>
                  </tr>
                </thead>
                <tbody>
                  {d.structuring.groups.map((g) => (
                    <tr key={g.invoices.join("-")}>
                      <td>{g.vendor_name}</td>
                      <td>{g.role}</td>
                      <td className="num">₹{inr(g.limit)}</td>
                      <td>
                        {g.invoices.map((id, k) => (
                          <div key={id}>
                            {invoiceLink(id)} <span className="muted small">₹{inr(g.amounts[k])}</span>
                          </div>
                        ))}
                      </td>
                      <td className="small">
                        {g.first} to {g.last}
                      </td>
                      <td className="num strong">₹{inr(g.total)}</td>
                      <td className="small">
                        {g.same_description ? <Badge tone="warn">same description</Badge> : <Badge>worded differently</Badge>}
                        {g.descriptions.map((text, k) => (
                          <div key={k} className="muted">
                            {text}
                          </div>
                        ))}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <Empty>No group of invoices fits the structuring guide.</Empty>
          )}
        </>
      )}
    </Panel>
  );
}

/** Whether the ledger can be relied on (ISA 500): run on request, since it reads every table. */
function DataReliability() {
  const [report, setReport] = useState<Reliability | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<Error | null>(null);
  const run = async () => {
    setBusy(true);
    setError(null);
    try {
      setReport(await api.reliability());
    } catch (err) {
      setError(err as Error);
    } finally {
      setBusy(false);
    }
  };
  const s = report?.summary;
  return (
    <Panel
      title="Can the ledger be relied on? (ISA 500)"
      subtitle="Before an audit's results mean anything, the records it read must be complete and accurate: every document an invoice names on file, the arithmetic of every invoice right, every invoice approved, no holes in the company's numbered series, nothing received but never invoiced, every invoice audited under the policy in force on its date."
      actions={
        <button className="btn btn-primary" onClick={() => void run()} disabled={busy}>
          {busy ? "Checking…" : report ? "Check again" : "Check the ledger"}
        </button>
      }
    >
      <ErrorBox error={error} onRetry={() => void run()} />
      {!report && !busy && <Empty>Not checked yet.</Empty>}
      {report && s && (
        <>
          <div className={s.reliable ? "notice" : "error"} role="status" style={{ marginBottom: 14 }}>
            <strong>{s.reliable ? "Reliable" : "Not reliable yet"}:</strong> {s.conclusion}. {s.without_exceptions} of {s.checks} checks without exceptions.
          </div>
          <div className="table-wrap short">
            <table className="table sticky compact">
              <thead>
                <tr>
                  <th>Check</th>
                  <th>Assertion</th>
                  <th className="num">Exceptions</th>
                  <th>Decided by</th>
                  <th>Examples</th>
                </tr>
              </thead>
              <tbody>
                {report.checks.map((c) => (
                  <tr key={c.id}>
                    <td>
                      {c.title}
                      {c.note && <div className="muted small">{c.note}</div>}
                    </td>
                    <td>{c.assertion}</td>
                    <td className={`num ${c.exceptions && !c.decided_by ? "bad-text strong" : ""}`}>{count(c.exceptions)}</td>
                    <td>{c.decided_by ? <Badge tone="accent">rule {c.decided_by}</Badge> : <span className="muted small">–</span>}</td>
                    <td className="mono small">{c.examples.slice(0, 4).join(", ")}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <dl className="facts" style={{ marginTop: 14 }}>
            {report.totals.map((t) => (
              <div key={t.table}>
                <dt>{t.table.replace("_", " ")}</dt>
                <dd>
                  {count(t.records)} records{t.amount !== null ? ` · ₹${inr(t.amount, 2)}` : ""}
                </dd>
              </div>
            ))}
            <div>
              <dt>Ledger fingerprint (SHA-256 of every row)</dt>
              <dd className="mono small" style={{ overflowWrap: "anywhere" }}>
                {report.fingerprint.ledger}
              </dd>
            </div>
          </dl>
        </>
      )}
    </Panel>
  );
}

const mark = (on: boolean) => (on ? <span className="good-text strong">●</span> : <span className="muted">·</span>);

/** Which test addresses which assertion and which fraud scheme, what each found, and what nothing covers. */
function Program() {
  const data = useApi(() => api.program());
  const p = data.data;
  const assertions = p ? Object.keys(p.assertions) : [];
  const schemes = p ? Object.keys(p.schemes) : [];
  const key = p?.answer_key?.compared ? p.answer_key.schemes ?? {} : null;
  return (
    <Panel
      title="The audit program: assertions and fraud schemes"
      subtitle="Every test of the platform against the assertions about the transactions (ISA 315) and the ways purchasing is defrauded (ACFE fraud tree). Which test addresses what is a judgement written down in auditiq/audit_program.py; what each test found is read from the store. A grey row did not run on the latest results (the agents' rules need a configuration with agents)."
    >
      <ErrorBox error={data.error} onRetry={data.reload} />
      {!p && data.loading && <Loading what="Mapping the tests" />}
      {p && (
        <>
          <div className="table-wrap short">
            <table className="table sticky compact matrix">
              <thead>
                <tr>
                  <th>Test</th>
                  <th>How</th>
                  {assertions.map((a) => (
                    <th key={a} title={p.assertions[a]}>
                      {a}
                    </th>
                  ))}
                  <th>Schemes</th>
                  <th className="num">Found</th>
                </tr>
              </thead>
              <tbody>
                {p.tests.map((t) => (
                  <tr key={t.id} style={t.ran ? undefined : { opacity: 0.55 }}>
                    <td>
                      <span className="mono">{t.id}</span> <span className="small">{t.title}</span>
                    </td>
                    <td className="small">{t.how}</td>
                    {assertions.map((a) => (
                      <td key={a} style={{ textAlign: "center" }}>
                        {mark(t.assertions.includes(a))}
                      </td>
                    ))}
                    <td className="small">{t.schemes.join(", ")}</td>
                    <td className="num">
                      {t.found ?? ""}
                      {t.listed ? <span className="muted small"> + {t.listed} listed</span> : null}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <h3>Fraud schemes</h3>
          <div className="table-wrap short">
            <table className="table sticky compact">
              <thead>
                <tr>
                  <th>Scheme</th>
                  <th>Tests that address it</th>
                  {key && (
                    <>
                      <th className="num">Labelled</th>
                      <th className="num">Found by a rule</th>
                      <th className="num">Listed by a lead</th>
                      <th className="num">Missed</th>
                      <th className="num">Reached</th>
                    </>
                  )}
                </tr>
              </thead>
              <tbody>
                {schemes.map((s) => {
                  const k = key?.[s];
                  return (
                    <tr key={s}>
                      <td>
                        <strong>{s}</strong>
                        <div className="muted small">{p.schemes[s]}</div>
                      </td>
                      <td className="small">{p.by_scheme[s].length ? p.by_scheme[s].join(", ") : <Badge tone="bad">no test</Badge>}</td>
                      {key && (
                        <>
                          <td className="num">{k ? count(k.labelled) : "–"}</td>
                          <td className="num">{k ? count(k.found) : "–"}</td>
                          <td className="num">{k ? count(k.lead_only) : "–"}</td>
                          <td className={`num ${k?.missed ? "bad-text" : ""}`}>{k ? count(k.missed) : "–"}</td>
                          <td className="num">{k ? percent(k.reached) : "–"}</td>
                        </>
                      )}
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
          <h3>What no test covers, and the limits</h3>
          <ul className="small">
            {p.untested.assertions.map((a) => (
              <li key={a}>
                Assertion <strong>{a}</strong>: no test.
              </li>
            ))}
            {p.untested.schemes.map((s) => (
              <li key={s}>
                Scheme <strong>{s}</strong>: no test.
              </li>
            ))}
            {Object.entries(p.limits).map(([what, text]) => (
              <li key={what}>
                <strong>{what}</strong>: {text}
              </li>
            ))}
          </ul>
        </>
      )}
    </Panel>
  );
}

/** The engagement as a workbook, tied to the store by its digest. */
function WorkingPapers() {
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState<{ digest: string | null; filename: string } | null>(null);
  const [error, setError] = useState<Error | null>(null);
  const download = async () => {
    setBusy(true);
    setError(null);
    try {
      const { blob, digest, filename } = await api.workpapers();
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = filename;
      document.body.appendChild(link);
      link.click();
      link.remove();
      URL.revokeObjectURL(url);
      setDone({ digest, filename });
    } catch (err) {
      setError(err as Error);
    } finally {
      setBusy(false);
    }
  };
  return (
    <Panel
      title="Working papers (ISA 230)"
      subtitle="The engagement in one Excel workbook: summary, every finding, the review queue, the leads, the sample, the data-reliability checks, the audit program and the integrity of the record. Its report digest is the same whenever the store is unchanged; python -m auditiq workpapers --check tells whether a workbook still matches the store. The sample's seed comes from the digest of the sealed runs, so nobody chose it."
      actions={
        <button className="btn btn-primary" onClick={() => void download()} disabled={busy}>
          {busy ? "Preparing…" : "Download the working papers (.xlsx)"}
        </button>
      }
    >
      <ErrorBox error={error} />
      {done ? (
        <p className="small">
          Downloaded <span className="mono">{done.filename}</span>. Report digest <span className="mono">{done.digest}</span>.
        </p>
      ) : (
        <Empty>Not downloaded yet.</Empty>
      )}
    </Panel>
  );
}

export function AssurancePage() {
  return (
    <div className="page">
      <header className="page-head">
        <div>
          <span className="eyebrow">Intelligence · Assurance</span>
          <h1>Assurance</h1>
          <p className="muted">
            What an auditor needs before relying on the audit: proof that its record and the evidence behind it were not changed, that the ledger it read is complete and
            accurate, a statistical sample of what it approved without a person, the invoices a controls-only audit lets through under the judgement rules, the map of
            what the tests cover and what they do not, and the working papers to take away.
          </p>
        </div>
      </header>
      <SealedRecord />
      <DataReliability />
      <StatisticalSample />
      <JudgementLeads />
      <Program />
      <WorkingPapers />
    </div>
  );
}
