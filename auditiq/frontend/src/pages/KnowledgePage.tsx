import { lazy, Suspense, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api/client";
import { Badge, Empty, ErrorBox, Kpi, Loading, Panel } from "../components/ui";
import { count } from "../lib/format";
import { useApi } from "../lib/useApi";

const EmbeddingSpace = lazy(() => import("../three/EmbeddingSpace").then((m) => ({ default: m.EmbeddingSpace })));
const DOC_COLORS = ["#38bdf8", "#a78bfa", "#2dd4bf", "#fbbf24", "#f472b6", "#fb923c"];

function show(value: unknown): string {
  if (value === undefined) return "–";
  if (value !== null && typeof value === "object") return Object.entries(value as Record<string, unknown>).map(([k, v]) => `${k} ${v}`).join(" · ");
  return String(value);
}

export function KnowledgePage() {
  const k = useApi(() => api.knowledge());
  const system = useApi(() => api.system());
  const [doc, setDoc] = useState("all");
  const [kind, setKind] = useState("all");
  const [text, setText] = useState("");
  const d = k.data;
  const docs = useMemo(() => (d ? d.documents.map((x) => x.file_name) : []), [d]);
  const passages = useMemo(() => {
    const q = text.trim().toLowerCase();
    return (d?.passages ?? []).filter((p) => (doc === "all" || p.document === doc) && (kind === "all" || p.kind === kind) &&
      (!q || p.text.toLowerCase().includes(q) || (p.clause_id ?? "").includes(q)));
  }, [d, doc, kind, text]);
  const versions = d ? d.versions.map((v) => v.version) : [];
  const clauses = useMemo(() => [...new Set(Object.values(d?.registry ?? {}).flatMap((r) => Object.keys(r)))].sort((a, b) =>
    a.split(".").map(Number).join(".").localeCompare(b.split(".").map(Number).join("."), undefined, { numeric: true })), [d]);
  const clausePassages = d?.passages.filter((p) => p.kind === "clause") ?? [];
  const verified = clausePassages.filter((p) => p.verified).length;
  const embedded = d?.passages.filter((p) => p.embed_model).length ?? 0;
  const params = Object.values(d?.registry ?? {}).reduce((t, r) => t + Object.values(r).reduce((u, c) => u + Object.keys(c.params).length, 0), 0);

  const stages = d ? [
    { title: "Policy PDFs", value: count(d.documents.length), note: `${count(d.documents.reduce((t, x) => t + x.pages, 0))} pages` },
    { title: "PyMuPDF parsing", value: count(d.passages.length), note: "passages with their page and section" },
    { title: "Verified against the registry", value: `${verified}/${clausePassages.length}`, note: "rule passages whose text matches" },
    { title: "Clause registry", value: count(clauses.length), note: `${versions.length} versions · ${params} parameters` },
    { title: "Embeddings", value: `${embedded}/${d.passages.length}`, note: system.data?.embeddings.model ?? "no model" },
    { title: "Used by", value: "4", note: "controls · agents · RAG · knowledge graph" },
  ] : [];

  return (
    <div className="page">
      <header className="page-head">
        <div>
          <span className="eyebrow">Knowledge layer · Knowledge base</span>
          <h1>Knowledge base</h1>
          <p className="muted">
            The policy as the platform knows it: documents read into passages with their pages, each rule's passage checked against the clause registry the controls execute, and every
            passage embedded for search. Add a new policy document on the <Link to="/policy">Policy</Link> page or through the Kafka compliance topic.
          </p>
        </div>
        <div className="page-actions">
          <Link className="btn" to="/graph">Knowledge graph</Link>
          <Link className="btn btn-primary" to="/rag">Trace a question</Link>
        </div>
      </header>

      <ErrorBox error={k.error} onRetry={k.reload} />
      {!d && k.loading && <Loading what="Reading the knowledge base" />}

      {d && (
        <>
          <ol className="pipeline-strip" aria-label="Knowledge pipeline">
            {stages.map((s, i) => (
              <li key={s.title}>
                <span className="num">{i + 1}</span>
                <strong>{s.value}</strong>
                <span>{s.title}</span>
                <small className="muted">{s.note}</small>
              </li>
            ))}
          </ol>

          <div className="kpis eight">
            <Kpi label="Documents" value={count(d.documents.length)} hint={`${count(d.documents.reduce((t, x) => t + x.pages, 0))} pages`} />
            <Kpi label="Passages" value={count(d.passages.length)} hint={`${clausePassages.length} rules, ${d.passages.length - clausePassages.length} text`} tone="accent" />
            <Kpi label="Rules verified" value={`${verified}/${clausePassages.length}`} hint="text matches the registry" tone={verified === clausePassages.length ? "good" : "warn"} share={clausePassages.length ? verified / clausePassages.length : 0} />
            <Kpi label="Embedded" value={`${embedded}/${d.passages.length}`} hint={system.data?.embeddings.model ?? "no embedding model"} tone={embedded === d.passages.length ? "good" : "warn"} share={d.passages.length ? embedded / d.passages.length : 0} />
            <Kpi label="Versions" value={count(versions.length)} hint={`v${d.versions.find((v) => v.is_active)?.version ?? "–"} active`} />
            <Kpi label="Rules per version" value={count(clauses.length)} />
            <Kpi label="Parameters" value={count(params)} hint="across the versions" />
            <Kpi label="Principal components" value={d.explained.length ? `${(d.explained.reduce((t, x) => t + x, 0) * 100).toFixed(0)}%` : "–"} hint="variance kept by the 3D map" />
          </div>

          <div className="grid-2 wide-left">
            <Panel
              title="Embedding map"
              subtitle={`Every passage at the first three principal components of its ${d.embedding_model ?? ""} embedding, coloured by document. Passages about the same subject sit together; hover one to read it.`}
            >
              {d.passages.some((p) => p.point) ? (
                <Suspense fallback={<Loading what="Projecting the vectors" />}>
                  <EmbeddingSpace
                    label="Policy passages in the embedding space"
                    points={d.passages.filter((p) => p.point).map((p) => ({
                      id: p.chunk_id, point: p.point!, color: DOC_COLORS[docs.indexOf(p.document) % DOC_COLORS.length],
                      label: p.clause_id ? `Rule ${p.clause_id} · v${p.version}` : p.section, detail: `${p.document}, page ${p.page}`,
                    }))}
                    explained={d.explained}
                  />
                </Suspense>
              ) : (
                <Empty>The passages are not embedded: run <code>python -m auditiq policy embed</code> with an embedding model.</Empty>
              )}
              <div className="legend">
                {docs.map((x, i) => (
                  <span key={x}>
                    <i style={{ background: DOC_COLORS[i % DOC_COLORS.length] }} /> {x}
                  </span>
                ))}
              </div>
            </Panel>
            <Panel title="Documents">
              <table className="table compact">
                <thead>
                  <tr>
                    <th>Document</th>
                    <th>Version</th>
                    <th className="num">Pages</th>
                    <th className="num">Passages</th>
                  </tr>
                </thead>
                <tbody>
                  {d.documents.map((x, i) => (
                    <tr key={x.doc_id}>
                      <td>
                        <span className="sev">
                          <i style={{ background: DOC_COLORS[i % DOC_COLORS.length] }} />
                          {x.file_name}
                        </span>
                        <div className="muted small">{x.title}</div>
                      </td>
                      <td>{x.version ?? "–"}</td>
                      <td className="num">{x.pages}</td>
                      <td className="num">{x.passages}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </Panel>
          </div>

          <Panel title="The registry across versions" subtitle="What each version sets for every rule: severity, kind and parameters. A value that differs from the version before is highlighted.">
            <div className="scroll-x">
              <table className="table compact registry">
                <thead>
                  <tr>
                    <th>Rule</th>
                    {versions.map((v) => (
                      <th key={v}>
                        v{v}
                        {d.versions.find((x) => x.version === v)?.is_active && <Badge tone="good">active</Badge>}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {clauses.map((c) => (
                    <tr key={c}>
                      <td className="mono strong">
                        {c}
                        <div className="muted small">{d.registry[versions[0]]?.[c]?.title}</div>
                      </td>
                      {versions.map((v, i) => {
                        const now = d.registry[v]?.[c];
                        const before = i ? d.registry[versions[i - 1]]?.[c] : undefined;
                        const changed = i > 0 && JSON.stringify(now) !== JSON.stringify(before);
                        return (
                          <td key={v} className={changed ? "changed" : ""}>
                            {now ? (
                              <>
                                <span className="small">
                                  {now.severity} · {now.kind}
                                </span>
                                {Object.entries(now.params).map(([name, value]) => (
                                  <div key={name} className="small mono">
                                    {name}: {show(value)}
                                  </div>
                                ))}
                              </>
                            ) : (
                              <span className="muted">absent</span>
                            )}
                          </td>
                        );
                      })}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Panel>

          <Panel
            title={`Passages (${count(passages.length)})`}
            subtitle="Every passage as it was read from its document, with its page, rule and whether its text matches the registry."
            actions={
              <div className="filters">
                <input type="search" placeholder="Text or rule" value={text} onChange={(e) => setText(e.target.value)} aria-label="Filter the passages" />
                <select value={doc} onChange={(e) => setDoc(e.target.value)} aria-label="Document">
                  <option value="all">All documents</option>
                  {docs.map((x) => (
                    <option key={x} value={x}>{x}</option>
                  ))}
                </select>
                <select value={kind} onChange={(e) => setKind(e.target.value)} aria-label="Kind of passage">
                  <option value="all">Rules and text</option>
                  <option value="clause">Rules</option>
                  <option value="text">Text</option>
                </select>
              </div>
            }
          >
            <div className="table-wrap">
              <table className="table sticky compact">
                <thead>
                  <tr>
                    <th>Passage</th>
                    <th>Document</th>
                    <th className="num">Page</th>
                    <th>Registry</th>
                    <th>Vector</th>
                  </tr>
                </thead>
                <tbody>
                  {passages.map((p) => (
                    <tr key={p.chunk_id}>
                      <td>
                        <strong>{p.clause_id ? `Rule ${p.clause_id}` : p.section}</strong>
                        <div className="small">{p.text.slice(0, 220)}{p.text.length > 220 ? "…" : ""}</div>
                      </td>
                      <td className="small">{p.document}</td>
                      <td className="num">{p.page}</td>
                      <td>{p.kind === "clause" ? <Badge tone={p.verified ? "good" : "bad"}>{p.verified ? "matches" : "differs"}</Badge> : <span className="muted small">text</span>}</td>
                      <td className="small mono">{p.embed_model ?? "–"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Panel>
        </>
      )}
    </div>
  );
}
