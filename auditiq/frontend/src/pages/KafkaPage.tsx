import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { api, waitForJob } from "../api/client";
import type { Job, PeekMessage, StreamLogRow, StreamStatus } from "../api/types";
import { KafkaTopology } from "../components/KafkaTopology";
import { Badge, Empty, ErrorBox, JobProgress, Kpi, Loading, Panel } from "../components/ui";
import { short } from "../lib/chart";
import { count } from "../lib/format";
import { notifyStoreChanged, useApi } from "../lib/useApi";

const KINDS = ["vendor", "invoice", "email", "compliance"] as const;
const OUTCOME_TONE: Record<string, "good" | "warn" | "bad" | "accent" | "neutral" | "violet"> = {
  stored: "good", audited: "good", linked: "accent", waiting: "warn", unlinked: "neutral", skipped: "neutral", error: "bad",
  "audited again": "violet",
};

type Sample = { t: number; messages: number; processed: number };

function time(ms: number | null): string {
  return ms ? new Date(ms).toLocaleTimeString("en-IN", { hour12: false }) : "–";
}

/** Messages produced and processed over the samples taken while the page is open. */
function Throughput({ samples }: { samples: Sample[] }) {
  if (samples.length < 2) return <p className="muted small">Throughput appears after a few seconds on the page.</p>;
  const W = 560, H = 150, L = 44, B = H - 22, T = 10;
  const max = Math.max(1, ...samples.map((s) => s.messages));
  const x = (i: number) => L + (i / (samples.length - 1)) * (W - L - 8);
  const y = (v: number) => B - (v / max) * (B - T);
  const line = (key: "messages" | "processed") => samples.map((s, i) => `${i ? "L" : "M"}${x(i).toFixed(1)},${y(s[key]).toFixed(1)}`).join(" ");
  const last = samples[samples.length - 1], first = samples[0];
  const rate = ((last.processed - first.processed) / Math.max(1, (last.t - first.t) / 1000)).toFixed(1);
  return (
    <div className="viz">
      <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label="Messages produced and processed over time">
        {[0, 0.5, 1].map((f) => (
          <g key={f} className="viz-grid">
            <line x1={L} x2={W - 8} y1={y(f * max)} y2={y(f * max)} />
            <text x={L - 6} y={y(f * max) + 3} textAnchor="end">{short(f * max)}</text>
          </g>
        ))}
        <path d={line("messages")} className="tp-line produced" />
        <path d={line("processed")} className="tp-line processed" />
      </svg>
      <div className="legend">
        <span><i style={{ background: "#f97316" }} /> produced (in the topics)</span>
        <span><i style={{ background: "#0f766e" }} /> processed by the workers</span>
        <span className="muted">{rate} messages/s over the last {Math.round((last.t - first.t) / 1000)} s</span>
      </div>
    </div>
  );
}

function Preview({ preview }: { preview: Record<string, unknown> }) {
  return (
    <span className="kv">
      {Object.entries(preview)
        .filter(([, v]) => v !== null && v !== undefined && v !== "")
        .map(([k, v]) => (
          <span key={k}>
            <b>{k}</b> {String(v).slice(0, 60)}
          </span>
        ))}
    </span>
  );
}

export function KafkaPage() {
  const system = useApi(() => api.system());
  const sources = useApi(() => api.streamSources());
  const [status, setStatus] = useState<StreamStatus | null>(null);
  const [log, setLog] = useState<StreamLogRow[]>([]);
  const [samples, setSamples] = useState<Sample[]>([]);
  const [error, setError] = useState<Error | null>(null);
  const [publishJob, setPublishJob] = useState<Job | null>(null);
  const [workJob, setWorkJob] = useState<Job | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [source, setSource] = useState<"ledger" | "mailbox" | "policy">("ledger");
  const [name, setName] = useState("");
  const [limit, setLimit] = useState("500");
  const [kinds, setKinds] = useState<string[]>([...KINDS]);
  const [peekKind, setPeekKind] = useState<(typeof KINDS)[number]>("invoice");
  const [peek, setPeek] = useState<PeekMessage[] | null>(null);
  const busy = Boolean(publishJob) || Boolean(workJob);
  const lag = (status?.topics ?? []).reduce((t, x) => t + x.lag, 0);
  const timer = useRef<number | null>(null);

  const refresh = useCallback(async () => {
    try {
      const [s, l] = await Promise.all([api.stream(), api.streamLog(40)]);
      setStatus(s);
      setLog(l.messages);
      setSamples((prev) => [...prev.slice(-89), {
        t: Date.now(),
        messages: s.topics.reduce((t, x) => t + x.messages, 0),
        processed: s.topics.reduce((t, x) => t + x.processed, 0),
      }]);
    } catch (err) {
      setError(err as Error);
    }
  }, []);

  useEffect(() => {
    void refresh();
    const period = busy || lag ? 1500 : 6000;              // faster while messages move
    timer.current = window.setInterval(() => void refresh(), period);
    return () => {
      if (timer.current) window.clearInterval(timer.current);
    };
  }, [refresh, busy, lag]);

  const options = useMemo(() => {
    const s = sources.data;
    if (!s) return [];
    return source === "ledger" ? s.ledgers.map((l) => ({ name: l.name, note: `${count(l.invoices ?? 0)} invoices · ${count(l.vendors ?? 0)} vendors` }))
      : source === "mailbox" ? s.mailboxes.map((m) => ({ name: m.name, note: `${(m.bytes / 1e6).toFixed(1)} MB` }))
        : s.policies.map((p) => ({ name: p.name, note: `${(p.bytes / 1e3).toFixed(0)} kB` }));
  }, [sources.data, source]);
  const own = system.data?.store.ledger;          // the store's own ledger first: another reuses its invoice numbers
  const chosen = options.some((o) => o.name === name) ? name : options.find((o) => o.name === own)?.name ?? options[0]?.name ?? "";

  const publish = async () => {
    setError(null);
    setNotice(null);
    try {
      const body = { source, name: chosen, ...(source === "ledger" && limit ? { limit: Number(limit) } : {}) };
      const out = await waitForJob(await api.streamPublish(body), setPublishJob as (j: Job<unknown>) => void, 800);
      setNotice(`Published ${chosen}: ${Object.entries(out.sent).map(([k, n]) => `${count(n)} to ${k}`).join(", ") || "nothing"}.`);
    } catch (err) {
      setError(err as Error);
    } finally {
      setPublishJob(null);
      void refresh();
    }
  };

  const work = async () => {
    setError(null);
    setNotice(null);
    try {
      const out = await waitForJob(await api.streamWork({ kinds, idle_exit: 4 }), setWorkJob as (j: Job<unknown>) => void, 1000);
      const done = Object.entries(out.counts).map(([k, c]) => `${k}: ${Object.entries(c).map(([o, n]) => `${count(n)} ${o}`).join(", ") || "nothing new"}`);
      setNotice(`The workers caught up. ${done.join(" · ")}.`);
      notifyStoreChanged();
    } catch (err) {
      setError(err as Error);
    } finally {
      setWorkJob(null);
      void refresh();
    }
  };

  const peekCount = status?.topics.find((t) => t.kind === peekKind)?.messages;
  useEffect(() => {
    let live = true;
    setPeek(null);
    api.streamPeek(peekKind).then((r) => live && setPeek(r.messages)).catch(() => live && setPeek([]));
    return () => {
      live = false;
    };
  }, [peekKind, peekCount]);

  const kafka = system.data?.kafka;
  const topics = status?.topics ?? [];
  const totals = topics.reduce((t, x) => ({ m: t.m + x.messages, p: t.p + x.processed, l: t.l + x.lag }), { m: 0, p: 0, l: 0 });

  return (
    <div className="page">
      <header className="page-head">
        <div>
          <span className="eyebrow">Ingestion · Kafka streams</span>
          <h1>Kafka streams</h1>
          <p className="muted">
            Ledgers, vendor e-mails and policy documents arrive through four partitioned topics. Publish a source, run the workers and watch each message move from the producer through
            its partition to the worker that stores it, links it or audits it, exactly once (the offsets are written in the same transaction as the data).
          </p>
        </div>
        <div className="page-actions">
          <span className={`status-chip ${kafka?.connected ? "good" : "bad"}`}>
            <span className={`dot ${kafka?.connected ? "dot-good" : "dot-bad"}`} />
            {kafka?.connected ? `Broker live · ${kafka.bootstrap}` : kafka?.configured ? "Broker not answering" : "No broker configured"}
          </span>
        </div>
      </header>

      <ErrorBox error={error} />
      {status && !status.configured && (
        <div className="banner">
          <span>
            No broker is configured. Start one with <code>python scripts/kafka_local.py start</code>; it writes <code>AUDITIQ_KAFKA_BOOTSTRAP</code> to <code>.env</code>.
          </span>
        </div>
      )}
      {status?.error && <div className="error">The broker at {status.bootstrap} does not answer: {status.error}</div>}

      <div className="kpis eight">
        <Kpi label="Topics" value={count(topics.length)} hint={`${count(topics.reduce((t, x) => t + x.partitions, 0))} partitions`} />
        <Kpi label="Messages in Kafka" value={short(totals.m)} hint="across the four topics" tone="accent" />
        <Kpi label="Processed" value={short(totals.p)} hint={totals.m ? `${((totals.p / totals.m) * 100).toFixed(1)}% of the messages` : "nothing yet"} tone="good" share={totals.m ? totals.p / totals.m : 0} />
        <Kpi label="Consumer lag" value={short(totals.l)} hint={totals.l ? "waiting for the workers" : "caught up"} tone={totals.l ? "warn" : "good"} />
        {KINDS.map((k) => {
          const t = topics.find((x) => x.kind === k);
          return <Kpi key={k} label={t?.topic ?? k} value={short(t?.processed ?? 0)} hint={`of ${short(t?.messages ?? 0)} · lag ${short(t?.lag ?? 0)}`} tone={t?.lag ? "warn" : "default"} />;
        })}
      </div>

      <Panel title="Live topology" subtitle="Sources on the left, the broker's topics and partitions (filled as the workers process them) in the middle, the consumer groups and what they write on the right. Dots move while messages are being produced or consumed.">
        {status ? (
          <div className="topology-wrap">
            <KafkaTopology topics={topics} bootstrap={status.bootstrap} prefix={kafka?.prefix} publishing={Boolean(publishJob)} consuming={Boolean(workJob)} />
          </div>
        ) : (
          <Loading what="Asking the broker" />
        )}
      </Panel>

      <div className="grid-2">
        <Panel title="1. Publish to Kafka" subtitle="Choose what to send. A ledger goes out as its vendors and then its invoices, each with its purchase order, goods receipt and approvals, keyed by vendor so one vendor's history stays in order.">
          <div className="form-grid">
            <label>
              Source
              <select value={source} onChange={(e) => setSource(e.target.value as typeof source)} aria-label="Source">
                <option value="ledger">Ledger (CSV dataset)</option>
                <option value="mailbox">Vendor mailbox (.mbox)</option>
                <option value="policy">Policy document (PDF)</option>
              </select>
            </label>
            <label>
              {source === "ledger" ? "Dataset" : "File"}
              <select value={chosen} onChange={(e) => setName(e.target.value)} aria-label="What to publish">
                {options.map((o) => (
                  <option key={o.name} value={o.name}>
                    {o.name} · {o.note}
                  </option>
                ))}
              </select>
            </label>
            {source === "ledger" && (
              <label>
                Invoices (first n; empty for all)
                <input value={limit} onChange={(e) => setLimit(e.target.value.replace(/\D/g, ""))} inputMode="numeric" aria-label="How many invoices" />
              </label>
            )}
          </div>
          <div className="row">
            <button className="btn btn-primary" onClick={publish} disabled={busy || !chosen || !kafka?.connected}>
              Publish to Kafka
            </button>
          </div>
          <JobProgress job={publishJob} />
        </Panel>
        <Panel title="2. Run the workers" subtitle="Each topic's consumer group reads its partitions, writes each batch with its offsets in one transaction, audits invoices with the controls as they arrive, links e-mails to their invoices and stores policy versions. They stop when a topic has been idle for 4 s.">
          <div className="checks-row">
            {KINDS.map((k) => (
              <label key={k} className="toggle">
                <input type="checkbox" checked={kinds.includes(k)} onChange={(e) => setKinds((prev) => (e.target.checked ? [...prev, k] : prev.filter((x) => x !== k)))} />
                {k}
              </label>
            ))}
          </div>
          <div className="row">
            <button className="btn btn-primary" onClick={work} disabled={busy || !kinds.length || !kafka?.connected}>
              Run the workers
            </button>
            <Link className="btn btn-ghost" to="/review">
              See the audited invoices
            </Link>
          </div>
          <JobProgress job={workJob} />
          {notice && (
            <div className="notice" role="status">
              {notice}
            </div>
          )}
        </Panel>
      </div>

      <div className="grid-2">
        <Panel title="Throughput" subtitle="Sampled while this page is open: what is in the topics against what the workers have processed.">
          <Throughput samples={samples} />
        </Panel>
        <Panel title="Outcomes by topic" subtitle="What the workers did with every message they processed.">
          {topics.length ? (
            <table className="table compact">
              <thead>
                <tr>
                  <th>Topic</th>
                  <th className="num">Partitions</th>
                  <th>Outcomes</th>
                </tr>
              </thead>
              <tbody>
                {topics.map((t) => (
                  <tr key={t.topic}>
                    <td className="mono">{t.topic}</td>
                    <td className="num">{t.partitions}</td>
                    <td>
                      {Object.keys(t.outcomes).length
                        ? Object.entries(t.outcomes).map(([o, n]) => (
                            <Badge key={o} tone={OUTCOME_TONE[o] ?? "neutral"}>
                              {o} {count(n)}
                            </Badge>
                          ))
                        : <span className="muted">nothing processed yet</span>}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : (
            <Empty>No topic yet: publish a source.</Empty>
          )}
        </Panel>
      </div>

      <Panel title="Worker log" subtitle="The newest messages the workers processed, with the partition and offset they came from and how long after they were produced they were handled.">
        {log.length ? (
          <div className="table-wrap short">
            <table className="table sticky compact">
              <thead>
                <tr>
                  <th>Processed</th>
                  <th>Topic</th>
                  <th className="num">Partition · offset</th>
                  <th>Key</th>
                  <th>Outcome</th>
                  <th>Detail</th>
                  <th className="num">Latency</th>
                </tr>
              </thead>
              <tbody>
                {log.map((m) => (
                  <tr key={`${m.topic}-${m.partition_no}-${m.kafka_offset}`}>
                    <td className="mono small">{time(m.processed_ms)}</td>
                    <td className="mono small">{m.topic}</td>
                    <td className="num mono small">
                      p{m.partition_no} · {m.kafka_offset}
                    </td>
                    <td className="mono small">{m.topic.endsWith(".invoice") && m.doc_key ? <Link to={`/invoice/${m.doc_key}`}>{m.doc_key}</Link> : m.doc_key}</td>
                    <td>
                      <Badge tone={OUTCOME_TONE[m.outcome] ?? "neutral"}>{m.outcome}</Badge>
                    </td>
                    <td className="small muted">{m.detail ?? ""}</td>
                    <td className="num small">{m.latency_ms === null ? "–" : `${(m.latency_ms / 1000).toFixed(1)} s`}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <Empty>The workers have not processed anything yet.</Empty>
        )}
      </Panel>

      <Panel
        title="Inside a topic"
        subtitle="The newest messages as they sit in Kafka, read from the end of each partition without joining a worker's group."
        actions={
          <div className="segmented" role="tablist" aria-label="Topic to inspect">
            {KINDS.map((k) => (
              <button key={k} role="tab" aria-selected={peekKind === k} className={peekKind === k ? "active" : ""} onClick={() => setPeekKind(k)}>
                {k}
              </button>
            ))}
          </div>
        }
      >
        {peek === null ? (
          <Loading what="Reading the topic" />
        ) : peek.length ? (
          <table className="table compact">
            <thead>
              <tr>
                <th className="num">Partition · offset</th>
                <th>Key</th>
                <th>Produced</th>
                <th className="num">Bytes</th>
                <th>Content</th>
              </tr>
            </thead>
            <tbody>
              {peek.map((m) => (
                <tr key={`${m.partition}-${m.offset}`}>
                  <td className="num mono small">
                    p{m.partition} · {m.offset}
                  </td>
                  <td className="mono small">{m.key}</td>
                  <td className="mono small">{time(m.timestamp)}</td>
                  <td className="num small">{count(m.bytes)}</td>
                  <td>
                    <Preview preview={m.preview} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          <Empty>This topic is empty: publish a source to it.</Empty>
        )}
      </Panel>
    </div>
  );
}
