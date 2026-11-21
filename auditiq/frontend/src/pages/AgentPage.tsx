import { useState, type FormEvent } from "react";
import { Link } from "react-router-dom";
import { api, waitForJob } from "../api/client";
import type { AgentAnswer, Job } from "../api/types";
import { Badge, ErrorBox, JobProgress, Panel } from "../components/ui";
import { useApi } from "../lib/useApi";

const EXAMPLES = [
  "Which role must approve an invoice of Rs 3,50,000?",
  "Which vendors have the most findings?",
  "Are there any e-mails trying to change bank details?",
  "Was the audit trail tampered with?",
  "What might the controls have missed according to the model?",
  "Show me the collusion rings",
];

const ID = /\b(INV\d{3,}|VEND\d{3,})\b/g;

/** Text with invoice and vendor ids as links. */
function Linked({ text }: { text: string }) {
  const parts = text.split(ID);
  return (
    <>
      {parts.map((p, i) =>
        /^INV\d{3,}$/.test(p) ? (
          <Link key={i} className="mono" to={`/invoice/${p}`}>
            {p}
          </Link>
        ) : (
          <span key={i}>{p}</span>
        ),
      )}
    </>
  );
}

/** The audit agent: a question becomes a plan of tool calls over the audit; every step and its result is shown. */
export function AgentPage() {
  const health = useApi(() => api.health());
  const queue = useApi(() => api.queue(1), []);
  const [question, setQuestion] = useState("");
  const [mode, setMode] = useState<"auto" | "rules" | "model">("auto");
  const [turns, setTurns] = useState<AgentAnswer[]>([]);
  const [job, setJob] = useState<Job | null>(null);
  const [error, setError] = useState<Error | null>(null);
  const hasModel = Boolean(health.data?.model);
  const first = queue.data?.items[0]?.invoice_id;
  const examples = first ? [`Why was ${first} escalated?`, `Tell me the story of ${first}`, `What would clear the finding on ${first}?`, ...EXAMPLES] : EXAMPLES;

  const ask = async (q: string) => {
    const text = q.trim();
    if (!text) return;
    setError(null);
    try {
      const answer = await waitForJob<AgentAnswer>(await api.agentAsk(text, mode), setJob as (j: Job<AgentAnswer>) => void, 600);
      setTurns((t) => [answer, ...t]);
      setQuestion("");
    } catch (err) {
      setError(err as Error);
    } finally {
      setJob(null);
    }
  };
  const submit = (e: FormEvent) => {
    e.preventDefault();
    void ask(question);
  };

  return (
    <div className="page">
      <header className="page-head">
        <div>
          <span className="eyebrow">AI layer · Audit agent</span>
          <h1>Audit agent</h1>
          <p className="muted">
            Ask about an invoice, a vendor, an amount, a rule, the review queue, collusion, vendor e-mails, the risk screen or the audit trail. The agent plans calls to fifteen tools that read the audit, runs them and answers from what they return, citing each step. Without a model it plans by rules in milliseconds; with one, the model plans step by step (ReAct). Every number in an answer is checked against the tools' results.
          </p>
        </div>
      </header>
      <Panel>
        <form className="ask" onSubmit={submit}>
          <textarea value={question} onChange={(e) => setQuestion(e.target.value)} rows={2} placeholder={examples[0]} aria-label="Question for the agent" />
          <select value={mode} onChange={(e) => setMode(e.target.value as typeof mode)} aria-label="Planner">
            <option value="auto">Auto: rules, else the model</option>
            <option value="rules">Rules only (no model)</option>
            <option value="model" disabled={!hasModel}>
              The model plans (ReAct){hasModel ? "" : ": no model configured"}
            </option>
          </select>
          <button className="btn btn-primary" type="submit" disabled={Boolean(job)}>
            Ask the agent
          </button>
        </form>
        <div className="examples">
          {examples.map((x) => (
            <button key={x} className="chip" onClick={() => void ask(x)} disabled={Boolean(job)}>
              {x}
            </button>
          ))}
        </div>
        <JobProgress job={job} />
        <ErrorBox error={error} />
      </Panel>
      {turns.map((t, i) => (
        <Panel key={`${t.question}-${turns.length - i}`} title={t.question} actions={<Badge tone={t.mode === "model" ? "violet" : "accent"}>{t.mode === "model" ? `planned by ${t.model ?? "the model"}` : "planned by rules"}</Badge>}>
          <div className="answer-box">
            <Linked text={t.answer} />
          </div>
          {t.unverified_numbers.length > 0 && (
            <p className="warn-text small">Numbers that no tool returned (check them): {t.unverified_numbers.join(", ")}</p>
          )}
          {t.steps.length > 0 && (
            <ol className="agent-steps">
              {t.steps.map((s) => (
                <li key={s.n}>
                  <span className="step-n">T{s.n}</span>
                  <div>
                    <code>
                      {s.tool}({Object.entries(s.args).map(([k, v]) => `${k}: ${JSON.stringify(v)}`).join(", ")})
                    </code>{" "}
                    <span className="muted small">{s.ms} ms</span>
                    {s.thought && <div className="muted small">thought: {s.thought}</div>}
                    <div className="small">
                      <Linked text={s.summary} />
                    </div>
                  </div>
                </li>
              ))}
            </ol>
          )}
        </Panel>
      ))}
    </div>
  );
}
