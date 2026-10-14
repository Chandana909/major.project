import { useState, type FormEvent } from "react";
import { api, waitForJob } from "../api/client";
import type { Hit, Job, Preview, Proposal } from "../api/types";
import { Badge, Empty, ErrorBox, JobProgress, Loading, Panel, SeverityBadge } from "../components/ui";
import { count } from "../lib/format";
import { changeRows } from "../lib/policy";
import { useApi } from "../lib/useApi";

function ProposalForm({ proposal, uploadId, onAdopted }: { proposal: Proposal; uploadId: string; onAdopted: (v: string) => void }) {
  const [reviewer, setReviewer] = useState("");
  const [accept, setAccept] = useState(false);
  const [version, setVersion] = useState(proposal.version ?? "");
  const [activate, setActivate] = useState(true);
  const [values, setValues] = useState<Record<string, string>>({});
  const [passages, setPassages] = useState<Record<string, string>>({});
  const [error, setError] = useState<Error | null>(null);
  const held = proposal.items.filter((i) => i.status !== "verified");
  const unlocated = Object.entries(proposal.rules).filter(([, r]) => !r.located).map(([k]) => k);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setError(null);
    try {
      const parsed: Record<string, unknown> = {};
      for (const [key, raw] of Object.entries(values)) if (raw.trim()) parsed[key] = JSON.parse(raw);
      const report = await api.confirm({ upload_id: uploadId, reviewer, accept_verified: accept, values: parsed, passages, version: version || null, activate });
      onAdopted(report.version);
    } catch (err) {
      setError(err instanceof SyntaxError ? new Error(`A typed value is not valid JSON: ${err.message}`) : (err as Error));
    }
  };

  return (
    <form className="proposal" onSubmit={submit}>
      <p className="muted">
        Read by <strong>{proposal.model}</strong>. A value is <em>verified</em> when its quote is in the document word for word and the value is written in that quote. Verified does not mean right: compare each value with its quote before you accept.
      </p>
      {proposal.problems.length > 0 && (
        <ul className="problems">
          {proposal.problems.map((p) => (
            <li key={p}>{p}</li>
          ))}
        </ul>
      )}
      <div className="scroll-x">
        <table className="table compact">
          <thead>
            <tr>
              <th>Rule</th>
              <th>Parameter</th>
              <th>Proposed</th>
              <th>Status</th>
              <th>Page</th>
              <th>Quote, or why it is held back</th>
            </tr>
          </thead>
          <tbody>
            {proposal.items.map((i) => (
              <tr key={`${i.clause}.${i.parameter}`}>
                <td>{i.clause}</td>
                <td className="mono">{i.parameter}</td>
                <td className="mono">{JSON.stringify(i.value)}</td>
                <td>
                  <Badge tone={i.status === "verified" ? "good" : i.status === "missing" ? "bad" : "warn"}>{i.status}</Badge>
                </td>
                <td>{i.page ?? "–"}</td>
                <td className="small">{i.reason || `“${i.quote}”`}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {held.map((i) => (
        <label key={`${i.clause}.${i.parameter}`}>
          Rule {i.clause} {i.parameter}: your value (JSON)
          <input value={values[`${i.clause}.${i.parameter}`] ?? ""} onChange={(e) => setValues({ ...values, [`${i.clause}.${i.parameter}`]: e.target.value })} placeholder={JSON.stringify(i.value ?? i.reference)} />
        </label>
      ))}
      {unlocated.map((clause) => (
        <label key={clause}>
          Rule {clause}: the passage of the document that states it
          <input value={passages[clause] ?? ""} onChange={(e) => setPassages({ ...passages, [clause]: e.target.value })} />
        </label>
      ))}
      <label className="toggle">
        <input type="checkbox" checked={accept} onChange={(e) => setAccept(e.target.checked)} /> I have compared every verified value with its quote and accept them
      </label>
      <div className="row">
        <label>
          Your name
          <input value={reviewer} onChange={(e) => setReviewer(e.target.value)} />
        </label>
        <label>
          Version
          <input value={version} onChange={(e) => setVersion(e.target.value)} />
        </label>
      </div>
      <label className="toggle">
        <input type="checkbox" checked={activate} onChange={(e) => setActivate(e.target.checked)} /> Make it the active version
      </label>
      <ErrorBox error={error} />
      <button className="btn btn-primary" type="submit">
        Adopt the confirmed policy
      </button>
    </form>
  );
}

function AdoptDocument({ hasModel, onChanged }: { hasModel: boolean; onChanged: (message: string) => void }) {
  const [preview, setPreview] = useState<Preview | null>(null);
  const [activate, setActivate] = useState(true);
  const [replace, setReplace] = useState(false);
  const [error, setError] = useState<Error | null>(null);
  const [busy, setBusy] = useState(false);
  const [job, setJob] = useState<Job | null>(null);
  const [proposal, setProposal] = useState<Proposal | null>(null);

  const choose = async (file: File | undefined) => {
    setPreview(null);
    setProposal(null);
    setError(null);
    if (!file) return;
    setBusy(true);
    try {
      setPreview(await api.preview(file));
    } catch (err) {
      setError(err as Error);
    } finally {
      setBusy(false);
    }
  };

  const adopt = async () => {
    if (!preview) return;
    setError(null);
    try {
      const report = await api.adopt(preview.upload_id, activate, replace);
      onChanged(`Policy version ${report.version} adopted from ${preview.file}${activate ? " and made active" : ""}.`);
      setPreview(null);
    } catch (err) {
      setError(err as Error);
    }
  };

  const readWithModel = async () => {
    if (!preview) return;
    setError(null);
    try {
      setProposal(await waitForJob<Proposal>(await api.propose(preview.upload_id), setJob as (j: Job<Proposal>) => void, 3000));
    } catch (err) {
      setError(err as Error);
    } finally {
      setJob(null);
    }
  };

  const rows = preview ? changeRows(preview.changes) : [];
  return (
    <Panel title="Adopt a policy document" subtitle="The thresholds are read from the wording of the document and compared with the active version. Nothing is stored until you adopt it.">
      <label className="file">
        <input type="file" accept="application/pdf,.pdf" onChange={(e) => choose(e.target.files?.[0])} aria-label="Policy PDF" />
        <span>{busy ? "Reading the document…" : "Choose a policy PDF"}</span>
      </label>
      <ErrorBox error={error} />
      {preview && (
        <div className="preview">
          <p>
            <strong>{preview.title}</strong>: version {preview.version ?? "not stated"}, {preview.pages} page(s).
          </p>
          {preview.usable ? (
            <>
              {rows.length ? (
                <table className="table compact">
                  <thead>
                    <tr>
                      <th>Rule</th>
                      <th>Parameter</th>
                      <th>Active version</th>
                      <th>This document</th>
                    </tr>
                  </thead>
                  <tbody>
                    {rows.map((r) => (
                      <tr key={`${r.rule}-${r.parameter}`}>
                        <td>{r.rule}</td>
                        <td className="mono">{r.parameter}</td>
                        <td className="mono">{r.from}</td>
                        <td className="mono strong">{r.to}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              ) : (
                <p className="muted">Every threshold of this document equals the active version.</p>
              )}
              <div className="row">
                <label className="toggle">
                  <input type="checkbox" checked={activate} onChange={(e) => setActivate(e.target.checked)} /> Make it the active version
                </label>
                <label className="toggle">
                  <input type="checkbox" checked={replace} onChange={(e) => setReplace(e.target.checked)} /> Replace a stored version of the same number
                </label>
              </div>
              <button className="btn btn-primary" onClick={adopt}>
                Adopt version {preview.version}
              </button>
            </>
          ) : (
            <>
              <ul className="problems">
                {preview.problems.map((p) => (
                  <li key={p}>{p}</li>
                ))}
              </ul>
              <p className="muted">This document is not in the wording the system reads by pattern.</p>
              {hasModel ? (
                <button className="btn" onClick={readWithModel} disabled={Boolean(job)}>
                  Let the model read this document
                </button>
              ) : (
                <p className="muted">With a configured model, the system can read a policy in its own wording and propose the thresholds for your confirmation.</p>
              )}
              <JobProgress job={job} />
              {proposal && <ProposalForm proposal={proposal} uploadId={preview.upload_id} onAdopted={(v) => onChanged(`Policy version ${v} adopted after your confirmation.`)} />}
            </>
          )}
        </div>
      )}
    </Panel>
  );
}

function PolicySearch() {
  const [q, setQ] = useState("");
  const [hits, setHits] = useState<{ mode: string; hits: Hit[] } | null>(null);
  const [error, setError] = useState<Error | null>(null);
  const search = async (e: FormEvent) => {
    e.preventDefault();
    if (!q.trim()) return;
    try {
      setError(null);
      setHits(await api.search(q.trim(), 4));
    } catch (err) {
      setError(err as Error);
    }
  };
  return (
    <Panel title="Search the policy documents" subtitle={hits ? `Ranking: ${hits.mode}` : "By meaning when an embedding model is configured, by wording otherwise."}>
      <form className="search" onSubmit={search}>
        <input type="search" value={q} onChange={(e) => setQ(e.target.value)} placeholder="bill raised on the weekend" aria-label="Question or keywords" />
        <button className="btn btn-primary" type="submit">
          Search
        </button>
      </form>
      <ErrorBox error={error} />
      {hits?.hits.map((h, i) => (
        <article key={h.chunk_id} className="hit">
          <strong>
            [{i + 1}] {h.source}
          </strong>
          <p>{h.text}</p>
        </article>
      ))}
    </Panel>
  );
}

export function PolicyPage() {
  const policy = useApi(() => api.policy());
  const health = useApi(() => api.health());
  const [notice, setNotice] = useState<string | null>(null);
  const [job, setJob] = useState<Job | null>(null);
  const [error, setError] = useState<Error | null>(null);
  const p = policy.data;

  const changed = (message: string) => {
    setNotice(message);
    policy.reload();
  };

  const apply = async () => {
    setError(null);
    try {
      const summary = await waitForJob<{ invoices: number; flags: number; states: Record<string, number> }>(await api.applyPolicy(), setJob as (j: Job<{ invoices: number; flags: number; states: Record<string, number> }>) => void, 1000);
      setNotice(`${count(summary.invoices)} invoices audited under the active version: ${count(summary.flags)} findings, ${count(summary.states.PENDING_REVIEW ?? 0)} waiting for review.`);
      policy.reload();
    } catch (err) {
      setError(err as Error);
    } finally {
      setJob(null);
    }
  };

  const activate = async (version: string) => {
    try {
      await api.activate(version);
      changed(`Version ${version} is now the policy the audit applies.`);
    } catch (err) {
      setError(err as Error);
    }
  };

  return (
    <div className="page">
      <header className="page-head">
        <div>
          <h1>Policy</h1>
          <p className="muted">The organisation's policy, as data: every threshold the controls apply comes from a policy document.</p>
        </div>
      </header>
      {notice && (
        <div className="notice" role="status">
          {notice}
        </div>
      )}
      <ErrorBox error={policy.error ?? error} onRetry={policy.reload} />
      {!p && policy.loading && <Loading what="Reading the policy store" />}
      {p && p.results_under_other_versions > 0 && (
        <div className="banner">
          <span>
            {count(p.results_under_other_versions)} invoices were last audited under another policy version than v{p.active}. Their results do not yet follow the active policy.
          </span>
          <button className="btn btn-primary" onClick={apply} disabled={Boolean(job)}>
            Audit the ledger under v{p.active}
          </button>
        </div>
      )}
      <JobProgress job={job} />

      {p && (
        <Panel title="Versions" subtitle="The active version is the one the next audit applies.">
          <table className="table">
            <thead>
              <tr>
                <th>Version</th>
                <th>Name</th>
                <th>Effective</th>
                <th>How it was adopted</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {p.versions.map((v) => (
                <tr key={v.version}>
                  <td>
                    v{v.version} {v.active && <Badge tone="good">active</Badge>}
                  </td>
                  <td>{v.policy_name ?? "–"}</td>
                  <td>{v.effective_date ?? "–"}</td>
                  <td className="small muted">
                    {v.adoption ? `read by ${v.adoption.model}, confirmed by ${v.adoption.confirmed_by} on ${v.adoption.confirmed_at}` : "from the registry or a template document"}
                  </td>
                  <td>
                    {!v.active && (
                      <button className="btn btn-ghost" onClick={() => activate(v.version)}>
                        Make active
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </Panel>
      )}

      <AdoptDocument hasModel={Boolean(health.data?.model)} onChanged={changed} />

      {p && (
        <div className="grid-2">
          <Panel title={`Rules of v${p.active}`} subtitle="Rules decided by a control are executed by code; rules that need reading go to the agents.">
            {p.rules.length ? (
              <table className="table compact">
                <thead>
                  <tr>
                    <th>Rule</th>
                    <th>Title</th>
                    <th>Severity</th>
                    <th>Decided by</th>
                    <th>Parameters</th>
                  </tr>
                </thead>
                <tbody>
                  {p.rules.map((r) => (
                    <tr key={r.rule}>
                      <td>{r.rule}</td>
                      <td>{r.title}</td>
                      <td>
                        <SeverityBadge severity={r.severity} />
                      </td>
                      <td>{r.kind === "control" ? "control" : "agent"}</td>
                      <td className="mono small">
                        {Object.entries(r.params)
                          .map(([k, v]) => `${k} = ${JSON.stringify(v)}`)
                          .join("; ") || "–"}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            ) : (
              <Empty>No active policy.</Empty>
            )}
          </Panel>
          <div className="stack">
            <PolicySearch />
            <Panel title="Ingested documents">
              <table className="table compact">
                <thead>
                  <tr>
                    <th>Document</th>
                    <th>Version</th>
                    <th className="num">Pages</th>
                    <th className="num">Rules</th>
                  </tr>
                </thead>
                <tbody>
                  {p.documents.map((d) => (
                    <tr key={d.file_name}>
                      <td>{d.file_name}</td>
                      <td>{d.version ?? "–"}</td>
                      <td className="num">{d.pages}</td>
                      <td className="num">{d.rules}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </Panel>
          </div>
        </div>
      )}
    </div>
  );
}
