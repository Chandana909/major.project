import { useState, type FormEvent } from "react";
import { api, waitForJob } from "../api/client";
import type { CopilotAnswer, DataAnswer, Job } from "../api/types";
import { ErrorBox, JobProgress, Panel } from "../components/ui";
import { cell } from "../lib/format";
import { useApi } from "../lib/useApi";

type Turn =
  | { kind: "ask"; question: string; answer: CopilotAnswer }
  | { kind: "data"; question: string; answer: DataAnswer };

const EXAMPLES = {
  ask: ["Can a supplier bill us on a Sunday?", "What happens to a vendor whose GST registration is suspended?"],
  data: ["Which five vendors have the most invoices waiting for review?", "How many invoices were escalated under rule 5.1.1?"],
};

export function AskPage() {
  const health = useApi(() => api.health());
  const [mode, setMode] = useState<"ask" | "data">("ask");
  const [question, setQuestion] = useState("");
  const [invoice, setInvoice] = useState("");
  const [turns, setTurns] = useState<Turn[]>([]);
  const [job, setJob] = useState<Job | null>(null);
  const [error, setError] = useState<Error | null>(null);
  const hasModel = Boolean(health.data?.model);
  // The first invoice waiting for review in this ledger: an example question about a real, audited invoice.
  const waiting = useApi(() => api.queue(1), []);
  const first = waiting.data?.items[0]?.invoice_id;
  const examples = mode === "ask" && first ? [`Why was ${first} flagged, and which rule applies?`, ...EXAMPLES.ask] : EXAMPLES[mode];

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    const q = question.trim();
    if (!q) return;
    setError(null);
    try {
      if (mode === "ask") {
        const answer = await waitForJob<CopilotAnswer>(await api.ask(q, invoice.trim() || undefined), setJob as (j: Job<CopilotAnswer>) => void, 1500);
        setTurns((t) => [{ kind: "ask", question: q, answer }, ...t]);
      } else {
        const answer = await waitForJob<DataAnswer>(await api.askData(q), setJob as (j: Job<DataAnswer>) => void, 1500);
        setTurns((t) => [{ kind: "data", question: q, answer }, ...t]);
      }
      setQuestion("");
    } catch (err) {
      setError(err as Error);
    } finally {
      setJob(null);
    }
  };

  return (
    <div className="page">
      <header className="page-head">
        <div>
          <span className="eyebrow">Governance · Ask AI</span>
          <h1>Ask AI</h1>
          <p className="muted">
            Questions about the policy and about audited invoices are answered from the policy documents and the audit record, with citations. Questions about the data become one checked, read-only query.
          </p>
        </div>
      </header>
      {!hasModel && (
        <div className="banner subtle">
          No model is configured: policy questions return the matching passages without a written answer, and data questions are not available.
        </div>
      )}
      <Panel>
        <div className="tabs" role="tablist">
          <button role="tab" aria-selected={mode === "ask"} className={mode === "ask" ? "active" : ""} onClick={() => setMode("ask")}>
            Policy &amp; invoices
          </button>
          <button role="tab" aria-selected={mode === "data"} className={mode === "data" ? "active" : ""} onClick={() => setMode("data")} disabled={!hasModel}>
            Data
          </button>
        </div>
        <form className="ask" onSubmit={submit}>
          <textarea value={question} onChange={(e) => setQuestion(e.target.value)} rows={2} placeholder={examples[0]} aria-label="Question" />
          {mode === "ask" && <input value={invoice} onChange={(e) => setInvoice(e.target.value)} placeholder="Invoice id (optional)" aria-label="Invoice id" />}
          <button className="btn btn-primary" type="submit" disabled={Boolean(job)}>
            Ask
          </button>
        </form>
        <div className="examples">
          {examples.map((x) => (
            <button key={x} className="chip" onClick={() => setQuestion(x)}>
              {x}
            </button>
          ))}
        </div>
        <JobProgress job={job} />
        <ErrorBox error={error} />
      </Panel>

      {turns.map((t, i) => (
        <Panel key={i} title={t.question}>
          {t.kind === "ask" ? (
            <>
              {t.answer.answer ? <p className="answer">{t.answer.answer}</p> : <p className="muted">No written answer: the facts and passages that match the question are below.</p>}
              {t.answer.facts && t.answer.facts.length > 0 && (
                <div>
                  <h3 className="sub">Facts from the policy graph ({t.answer.facts.length})</h3>
                  <ol className="graph-facts">
                    {t.answer.facts.map((f, j) => (
                      <li key={j}>
                        <span className="fact-label">F{j + 1}</span>
                        <div>
                          {f.text}
                          {f.source && <span className="cite">{f.source}</span>}
                        </div>
                      </li>
                    ))}
                  </ol>
                </div>
              )}
              {t.answer.case_facts && t.answer.case_facts.length > 0 && (
                <div>
                  <h3 className="sub">Facts from the audit graph ({t.answer.case_facts.length})</h3>
                  <ol className="graph-facts">
                    {t.answer.case_facts.map((f, j) => (
                      <li key={j}>
                        <span className="fact-label">C{j + 1}</span>
                        <div>{f.text}</div>
                      </li>
                    ))}
                  </ol>
                </div>
              )}
              {t.answer.sources.length > 0 && (
                <p className="small">
                  Sources:{" "}
                  {t.answer.sources.map((s) => (
                    <span key={s.chunk_id} className="cite">
                      {s.source}
                    </span>
                  ))}
                </p>
              )}
              <details>
                <summary>Passages shown to the model ({t.answer.passages.length})</summary>
                {t.answer.passages.map((h, j) => (
                  <article key={h.chunk_id} className="hit">
                    <strong>
                      [{j + 1}] {h.source}
                    </strong>
                    <p>{h.text}</p>
                  </article>
                ))}
              </details>
            </>
          ) : (
            <>
              {t.answer.sql && <pre className="sql">{t.answer.sql}</pre>}
              {t.answer.error ? (
                <ErrorBox error={new Error(t.answer.error)} />
              ) : (
                <>
                  <div className="scroll-x">
                    <table className="table compact">
                      <thead>
                        <tr>
                          {t.answer.columns.map((c) => (
                            <th key={c}>{c}</th>
                          ))}
                        </tr>
                      </thead>
                      <tbody>
                        {t.answer.rows.map((r, j) => (
                          <tr key={j}>
                            {r.map((v, k) => (
                              <td key={k}>{cell(v)}</td>
                            ))}
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                  <p className="muted small">{t.answer.explanation}</p>
                </>
              )}
            </>
          )}
        </Panel>
      ))}
    </div>
  );
}
