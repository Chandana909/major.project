import { lazy, Suspense, useMemo, useState, type FormEvent } from "react";
import { api, waitForJob } from "../api/client";
import type { CopilotAnswer, Job, RagPassage, RagTrace } from "../api/types";
import { Badge, Empty, ErrorBox, JobProgress, Kpi, Loading, Panel } from "../components/ui";
import { useApi } from "../lib/useApi";

const EmbeddingSpace = lazy(() => import("../three/EmbeddingSpace").then((m) => ({ default: m.EmbeddingSpace })));

const EXAMPLES = [
  "Who has to approve an invoice of ₹30 lakh?",
  "What changed between version 2.5 and 2.6?",
  "Can a supplier bill us on a Sunday?",
  "What happens when two invoices look like duplicates?",
  "Is ₹4,99,000 suspicious and who approves it?",
];
const DOC_COLORS = ["#38bdf8", "#a78bfa", "#2dd4bf", "#fbbf24", "#f472b6"];

function name(p: { clause_id: string | null; section: string; version: string | null }): string {
  return `${p.clause_id ? `Rule ${p.clause_id}` : p.section}${p.version ? ` · v${p.version}` : ""}`;
}

/** The top passages of one ranker as horizontal bars, those in the final context marked. */
function Ranking({ passages, score, rank, inContext, title }: {
  passages: RagPassage[];
  score: "lexical" | "dense" | "hybrid";
  rank: "lexical_rank" | "dense_rank" | "hybrid_rank";
  inContext: Set<number>;
  title: string;
}) {
  const top = [...passages].filter((p) => p[rank] !== undefined).sort((a, b) => (a[rank] ?? 0) - (b[rank] ?? 0)).slice(0, 8);
  const max = Math.max(1e-9, ...top.map((p) => p[score] ?? 0));
  return (
    <div className="ranking">
      <h3 className="sub">{title}</h3>
      <ol>
        {top.map((p) => (
          <li key={p.chunk_id} className={inContext.has(p.chunk_id) ? "in" : ""}>
            <span className="rank">{p[rank]}</span>
            <span className="name" title={p.text}>
              {name(p)}
            </span>
            <span className="bar">
              <i style={{ width: `${((p[score] ?? 0) / max) * 100}%` }} />
            </span>
            <span className="val">{(p[score] ?? 0).toFixed(score === "hybrid" ? 4 : 3)}</span>
          </li>
        ))}
      </ol>
    </div>
  );
}

export function RagPage() {
  const system = useApi(() => api.system());
  const [question, setQuestion] = useState("");
  const [k, setK] = useState(5);
  const [trace, setTrace] = useState<RagTrace | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<Error | null>(null);
  const [answer, setAnswer] = useState<CopilotAnswer | null>(null);
  const [job, setJob] = useState<Job | null>(null);
  const inContext = useMemo(() => new Set((trace?.context ?? []).map((c) => c.chunk_id)), [trace]);
  const docs = useMemo(() => [...new Set((trace?.passages ?? []).map((p) => p.document))], [trace]);
  const model = system.data?.model;

  const run = async (q: string) => {
    const text = q.trim();
    if (!text) return;
    setQuestion(text);
    setLoading(true);
    setError(null);
    setAnswer(null);
    try {
      setTrace(await api.ragTrace(text, k));
    } catch (err) {
      setError(err as Error);
    } finally {
      setLoading(false);
    }
  };
  const submit = (e: FormEvent) => {
    e.preventDefault();
    void run(question);
  };
  const generate = async () => {
    if (!trace) return;
    setError(null);
    try {
      setAnswer(await waitForJob(await api.ask(trace.question), setJob as (j: Job<CopilotAnswer>) => void, 1500));
    } catch (err) {
      setError(err as Error);
    } finally {
      setJob(null);
    }
  };

  const dense = trace?.embedding_model;
  const steps = [
    { n: 1, title: "Question", state: trace ? "done" : "wait", note: trace ? `${trace.question.length} characters` : "ask below" },
    { n: 2, title: "Graph recognises", state: trace ? "done" : "wait", note: trace ? `${Object.values(trace.recognised).filter((v) => (Array.isArray(v) ? v.length : v)).length} kinds of entity` : "" },
    { n: 3, title: "Lexical TF-IDF", state: trace ? "done" : "wait", note: trace ? `${trace.passages.length} passages scored` : "words + character n-grams" },
    { n: 4, title: "Dense vectors", state: trace ? (dense ? "done" : "skip") : "wait", note: dense ? dense : trace ? "no embedding model" : "cosine similarity" },
    { n: 5, title: "RRF fusion", state: trace ? (dense ? "done" : "skip") : "wait", note: `1/(${trace?.rrf_k ?? 60}+r) summed` },
    { n: 6, title: "Graph facts", state: trace ? "done" : "wait", note: trace ? `${trace.facts.length} facts` : "derived by code" },
    { n: 7, title: "Context", state: trace ? "done" : "wait", note: trace ? `${trace.context.length} passages` : "graph first" },
    { n: 8, title: "Answer", state: answer ? "done" : model?.reachable ? "wait" : "skip", note: model?.reachable ? model.name ?? "" : "model offline" },
  ];

  return (
    <div className="page">
      <header className="page-head">
        <div>
          <span className="eyebrow">Knowledge layer · RAG</span>
          <h1>RAG retrieval, step by step</h1>
          <p className="muted">
            What happens between a question and the context a model answers from: the policy graph recognises what the question names, every passage is scored by its words and
            by its meaning, the two rankings are fused, the graph adds the facts it derives, and the context is assembled. Each step is shown with its numbers.
          </p>
        </div>
      </header>

      <Panel title="Ask a question">
        <form className="search" onSubmit={submit}>
          <input value={question} onChange={(e) => setQuestion(e.target.value)} placeholder="e.g. who may approve an invoice of ₹7,50,000?" aria-label="Question to trace" />
          <select value={k} onChange={(e) => setK(Number(e.target.value))} aria-label="Passages to retrieve">
            {[3, 5, 8].map((n) => (
              <option key={n} value={n}>
                top {n}
              </option>
            ))}
          </select>
          <button className="btn btn-primary" type="submit" disabled={loading || !question.trim()}>
            Trace retrieval
          </button>
        </form>
        <div className="examples">
          {EXAMPLES.map((x) => (
            <button key={x} type="button" className="chip" onClick={() => void run(x)}>
              {x}
            </button>
          ))}
        </div>
      </Panel>

      <ol className="stepper" aria-label="Retrieval steps">
        {steps.map((s) => (
          <li key={s.n} className={s.state}>
            <span className="num">{s.n}</span>
            <strong>{s.title}</strong>
            <span className="muted small">{s.note}</span>
          </li>
        ))}
      </ol>

      <ErrorBox error={error} />
      {loading && <Loading what="Scoring every passage" />}
      {!trace && !loading && <Empty>Ask a question, or pick an example, to see every step.</Empty>}

      {trace && (
        <>
          <div className="kpis eight">
            <Kpi label="Ranking used" value={trace.mode} hint={trace.dense_error ? "embedding model did not answer" : dense ? `dense: ${dense}` : "wording only"} tone="accent" />
            <Kpi label="Passages scored" value={trace.passages.length} hint={`${docs.length} documents of the active version`} />
            <Kpi label="Graph facts" value={trace.facts.length} hint="exact, from the registry" tone="good" />
            <Kpi label="Context" value={trace.context.length} hint={`${trace.context.filter((c) => c.from === "graph").length} from the graph`} />
            <Kpi label="Top lexical score" value={Math.max(...trace.passages.map((p) => p.lexical)).toFixed(3)} />
            <Kpi label="Top cosine" value={dense ? Math.max(...trace.passages.map((p) => p.dense ?? 0)).toFixed(3) : "–"} />
            <Kpi label="Rules recognised" value={(trace.recognised.clauses as string[] | undefined)?.length ?? 0} hint={`${(trace.recognised.topics as string[] | undefined)?.length ?? 0} by topic`} />
            <Kpi label="Amounts recognised" value={(trace.recognised.amounts as number[] | undefined)?.length ?? 0} />
          </div>

          <div className="grid-2">
            <Panel title="2. What the graph recognises" subtitle="Rule numbers, versions, roles, amounts, agents, severities and topics found in the question by the policy graph.">
              <div className="recognised">
                {Object.entries(trace.recognised)
                  .filter(([, v]) => (Array.isArray(v) ? v.length : v))
                  .map(([key, v]) => (
                    <span key={key} className="recog">
                      <b>{key}</b> {Array.isArray(v) ? v.join(", ") : String(v)}
                    </span>
                  ))}
                {!Object.values(trace.recognised).some((v) => (Array.isArray(v) ? v.length : v)) && <span className="muted">nothing named: the topic comes from the rankers</span>}
              </div>
              <h3 className="sub">6. Facts the graph derives</h3>
              {trace.facts.length ? (
                <ol className="graph-facts">
                  {trace.facts.map((f, i) => (
                    <li key={i}>
                      <span className="fact-label">F{i + 1}</span>
                      <div>
                        <Badge tone="accent">{f.kind}</Badge> {f.text}
                        {f.source && <span className="cite">{f.source}</span>}
                      </div>
                    </li>
                  ))}
                </ol>
              ) : (
                <p className="muted">No fact: the question names nothing the graph holds.</p>
              )}
            </Panel>
            <Panel title="Embedding space" subtitle={dense ? `Every passage at the first three principal components of its ${dense} embedding; the question (gold) is projected the same way and joined to the passages in the context.` : "Needs the embedding model."}>
              {dense && trace.query_point ? (
                <Suspense fallback={<Loading what="Projecting the vectors" />}>
                  <EmbeddingSpace
                    label="Passages and the question in the embedding space"
                    points={trace.passages.filter((p) => p.point).map((p) => ({
                      id: p.chunk_id, point: p.point!, color: DOC_COLORS[docs.indexOf(p.document) % DOC_COLORS.length],
                      label: name(p), detail: `${p.document}, page ${p.page} · cosine ${p.dense?.toFixed(3)}`,
                    }))}
                    query={trace.query_point}
                    linked={[...inContext]}
                    explained={trace.explained}
                  />
                </Suspense>
              ) : (
                <Empty>{trace.dense_error ?? "No embedding model is configured: the passages are ranked by wording only."}</Empty>
              )}
              <div className="legend">
                {docs.map((d, i) => (
                  <span key={d}>
                    <i style={{ background: DOC_COLORS[i % DOC_COLORS.length] }} /> {d}
                  </span>
                ))}
                <span>
                  <i style={{ background: "#fbbf24" }} /> the question
                </span>
              </div>
            </Panel>
          </div>

          <Panel title="3–5. Scores, ranks and their fusion" subtitle="The top passages of each ranker. Highlighted passages made it into the context. Reciprocal-rank fusion adds 1/(k + rank) of the two rankings, so a passage both rank well wins.">
            <div className="rankings">
              <Ranking passages={trace.passages} score="lexical" rank="lexical_rank" inContext={inContext} title="Lexical (TF-IDF, words and character n-grams)" />
              {dense && <Ranking passages={trace.passages} score="dense" rank="dense_rank" inContext={inContext} title={`Dense (cosine, ${dense})`} />}
              {dense && <Ranking passages={trace.passages} score="hybrid" rank="hybrid_rank" inContext={inContext} title={`Fusion (RRF, k = ${trace.rrf_k})`} />}
            </div>
            {dense && (
              <div className="scroll-x">
                <table className="table compact">
                  <thead>
                    <tr>
                      <th>Passage</th>
                      <th className="num">Lexical rank</th>
                      <th className="num">Dense rank</th>
                      <th className="num">1/(k+lexical)</th>
                      <th className="num">1/(k+dense)</th>
                      <th className="num">Fused score</th>
                      <th className="num">Fused rank</th>
                    </tr>
                  </thead>
                  <tbody>
                    {[...trace.passages].sort((a, b) => (a.hybrid_rank ?? 0) - (b.hybrid_rank ?? 0)).slice(0, 8).map((p) => (
                      <tr key={p.chunk_id} className={inContext.has(p.chunk_id) ? "highlight" : ""}>
                        <td>{name(p)}</td>
                        <td className="num">{p.lexical_rank}</td>
                        <td className="num">{p.dense_rank}</td>
                        <td className="num">{(1 / (trace.rrf_k + p.lexical_rank)).toFixed(5)}</td>
                        <td className="num">{(1 / (trace.rrf_k + (p.dense_rank ?? 0))).toFixed(5)}</td>
                        <td className="num strong">{p.hybrid?.toFixed(5)}</td>
                        <td className="num strong">{p.hybrid_rank}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </Panel>

          <Panel
            title="7. The context the model is given"
            subtitle="The passages the graph's facts cite come first, then the ranker's best that are not among them. This, with the facts, is what Ask AI sends."
            actions={
              <button className="btn btn-primary" onClick={generate} disabled={Boolean(job)} title={model?.reachable ? "" : "the model is offline: the answer will be the facts and passages"}>
                8. Generate the answer
              </button>
            }
          >
            <JobProgress job={job} />
            {answer && (
              <div className="answer-box">
                {answer.answer ? <p className="answer">{answer.answer}</p> : <p className="muted">The model is offline, so there is no written answer: the facts and passages above are what it would have been given.</p>}
              </div>
            )}
            <ol className="context-list">
              {trace.context.map((c, i) => (
                <li key={c.chunk_id}>
                  <span className="fact-label">[{i + 1}]</span>
                  <div>
                    <Badge tone={c.from === "graph" ? "accent" : "neutral"}>{c.from === "graph" ? "from the graph" : "retrieved"}</Badge> <strong>{c.source}</strong>
                    <p>{c.text}</p>
                  </div>
                </li>
              ))}
            </ol>
          </Panel>
        </>
      )}
    </div>
  );
}
