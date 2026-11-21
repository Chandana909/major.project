// Charts of the explainable-AI views: a SHAP waterfall for one invoice, feature importance and a dot plot over the
// ledger, the distribution of the screen's probability, and the story of an invoice. Plain SVG, no chart library.
import type { ImportanceHead, ScreenHead, StoryStep } from "../api/types";
import { probability, rankColor } from "../lib/xai";

const UP = "#dc2626"; // pushes toward "anomalous"
const DOWN = "#2563eb"; // pushes toward "clean"


/** The SHAP values of one head as a waterfall: from the expected output (base) through each feature to the output. */
export function ShapWaterfall({ head }: { head: ScreenHead }) {
  const rows = [
    ...head.contributions.map((c) => ({ label: c.feature, note: `= ${formatValue(c.value)}`, delta: c.shap, title: c.meaning })),
    ...(Math.abs(head.other) > 1e-6 ? [{ label: "other features", note: "", delta: head.other, title: "the remaining features together" }] : []),
  ];
  let running = head.base;
  const steps = rows.map((r) => {
    const start = running;
    running += r.delta;
    return { ...r, start, end: running };
  });
  const values = [head.base, head.raw, ...steps.flatMap((s) => [s.start, s.end])];
  const lo = Math.min(...values);
  const hi = Math.max(...values);
  const pad = (hi - lo) * 0.08 || 1;
  const min = lo - pad;
  const max = hi + pad;
  const W = 640;
  const left = ROW_LEFT;
  const right = 70;
  const rowH = ROW_H;
  const H = (steps.length + 2) * rowH + 34;
  const x = (v: number) => left + ((v - min) / (max - min)) * (W - left - right);
  const ticks = niceTicks(min, max, 5);
  return (
    <svg className="shap-waterfall" viewBox={`0 0 ${W} ${H}`} role="img" aria-label={`SHAP waterfall: from ${head.base.toFixed(2)} to ${head.raw.toFixed(2)} log-odds`}>
      {ticks.map((t) => (
        <g key={t}>
          <line x1={x(t)} x2={x(t)} y1={6} y2={H - 26} className="grid-line" />
          <text x={x(t)} y={H - 10} textAnchor="middle" className="axis-label">
            {t.toFixed(1)}
          </text>
        </g>
      ))}
      <Row y={10} label="expected (base)" note={`p = ${probability(head.base).toFixed(3)}`} />
      <line x1={x(head.base)} x2={x(head.base)} y1={10} y2={10 + rowH * 0.7} stroke="#64748b" strokeWidth={3} />
      {steps.map((s, i) => {
        const y = 10 + (i + 1) * rowH;
        const a = x(Math.min(s.start, s.end));
        const b = x(Math.max(s.start, s.end));
        return (
          <g key={`${s.label}-${i}`}>
            <title>{`${s.title}: ${s.delta >= 0 ? "+" : ""}${s.delta.toFixed(3)} log-odds`}</title>
            <Row y={y} label={s.label} note={s.note} />
            <rect x={a} y={y + 3} width={Math.max(1.5, b - a)} height={rowH - 10} rx={3} fill={s.delta >= 0 ? UP : DOWN} opacity={0.85} />
            <text x={b + 4} y={y + rowH / 2 + 2} className="bar-value">
              {s.delta >= 0 ? "+" : ""}
              {s.delta.toFixed(2)}
            </text>
          </g>
        );
      })}
      <Row y={10 + (steps.length + 1) * rowH} label="output" note={`p = ${head.probability.toFixed(3)}`} strong />
      <line x1={x(head.raw)} x2={x(head.raw)} y1={10 + (steps.length + 1) * rowH} y2={10 + (steps.length + 1.7) * rowH} stroke="#0f172a" strokeWidth={3} />
      <text x={W - right + 8} y={H - 10} className="axis-label">
        log-odds
      </text>
    </svg>
  );
}

const ROW_H = 26;
const ROW_LEFT = 190;

function Row({ y, label, note, strong = false }: { y: number; label: string; note: string; strong?: boolean }) {
  return (
    <>
      <text x={8} y={y + ROW_H / 2 + 2} className={strong ? "row-label strong" : "row-label"}>
        {label}
      </text>
      <text x={ROW_LEFT - 8} y={y + ROW_H / 2 + 2} textAnchor="end" className="row-note">
        {note}
      </text>
    </>
  );
}

function formatValue(v: number): string {
  if (Number.isInteger(v)) return v.toLocaleString("en-IN");
  return Math.abs(v) >= 100 ? v.toFixed(0) : v.toFixed(3);
}

function niceTicks(min: number, max: number, count: number): number[] {
  const step = (max - min) / count;
  const magnitude = 10 ** Math.floor(Math.log10(step || 1));
  const nice = [1, 2, 5, 10].map((m) => m * magnitude).find((s) => s >= step) ?? step;
  const out: number[] = [];
  for (let t = Math.ceil(min / nice) * nice; t <= max; t += nice) out.push(Number(t.toFixed(6)));
  return out;
}

/** Mean absolute SHAP value of each feature: how much it moves the head's output over the ledger. */
export function ImportanceBars({ head, top = 12 }: { head: ImportanceHead; top?: number }) {
  const rows = head.features.slice(0, top);
  const max = Math.max(1e-9, ...rows.map((r) => r.mean_abs_shap));
  return (
    <ul className="barlist importance">
      {rows.map((r) => (
        <li key={r.feature} title={r.meaning}>
          <span className="barlist-label mono">{r.feature}</span>
          <span className="barlist-track">
            <span className="barlist-fill" style={{ width: `${(r.mean_abs_shap / max) * 100}%`, background: "#7c3aed" }} />
          </span>
          <span className="barlist-value">{r.mean_abs_shap.toFixed(3)}</span>
        </li>
      ))}
    </ul>
  );
}

/** sign(v) · ln(1 + |v|): small values keep their room beside a few very large ones. */
const symlog = (v: number) => Math.sign(v) * Math.log1p(Math.abs(v));
const SYMLOG_TICKS = [-20, -10, -5, -2, -1, 0, 1, 2, 5, 10, 20];

/** One dot per invoice and feature: where the feature's SHAP value lies (on a symmetric log scale, since a few
 * invoices move the output by several log-odds and most by a fraction of one), coloured by how high its value is. */
export function Beeswarm({ head }: { head: ImportanceHead }) {
  const rows = head.points;
  const all = rows.flatMap((r) => r.shap);
  const min = Math.min(0, ...all);
  const max = Math.max(0, ...all);
  const lo = symlog(min);
  const hi = symlog(max);
  const W = 640;
  const left = 170;
  const rowH = 26;
  const H = rows.length * rowH + 34;
  const x = (v: number) => left + ((symlog(v) - lo) / (hi - lo || 1)) * (W - left - 16);
  const ticks = SYMLOG_TICKS.filter((t) => t >= min && t <= max);
  return (
    <svg className="beeswarm" viewBox={`0 0 ${W} ${H}`} role="img" aria-label={`SHAP values of the ${rows.length} most important features for ${head.rows} invoices`}>
      {ticks.map((t) => (
        <line key={t} x1={x(t)} x2={x(t)} y1={4} y2={H - 26} className={t === 0 ? "zero-line" : "grid-line"} />
      ))}
      {rows.map((r, i) => {
        const y = 4 + i * rowH + rowH / 2;
        return (
          <g key={r.feature}>
            <text x={8} y={y + 4} className="row-label mono">
              {r.feature}
            </text>
            {r.shap.map((v, k) => (
              <circle key={k} cx={x(v)} cy={y + (((k * 37) % 11) - 5) * 1.4} r={2.4} fill={rankColor(r.rank[k] ?? 0.5)} opacity={0.75} />
            ))}
          </g>
        );
      })}
      {ticks.map((t) => (
        <text key={t} x={x(t)} y={H - 10} textAnchor="middle" className="axis-label">
          {t > 0 ? `+${t}` : t}
        </text>
      ))}
      <text x={W - 4} y={H - 22} textAnchor="end" className="axis-label">
        log-odds (symmetric log scale)
      </text>
    </svg>
  );
}

const ROUTE_COLORS: Record<string, string> = { approve: "#34d399", sample: "#fbbf24", escalate: "#f87171", unaudited: "#cbd5e1" };

/** The screen's probability of "anomalous" over the ledger, in bins, stacked by the audit's route (log scale). */
export function ProbabilityHistogram({ bins, byRoute }: { bins: number; byRoute: Record<string, number[]> }) {
  const routes = Object.keys(byRoute).sort((a, b) => ["approve", "sample", "escalate", "unaudited"].indexOf(a) - ["approve", "sample", "escalate", "unaudited"].indexOf(b));
  const totals = Array.from({ length: bins }, (_, i) => routes.reduce((t, r) => t + (byRoute[r][i] ?? 0), 0));
  const top = Math.log10(1 + Math.max(1, ...totals));
  const W = 640;
  const H = 200;
  const bw = (W - 40) / bins;
  return (
    <figure className="viz">
      <svg viewBox={`0 0 ${W} ${H + 24}`} role="img" aria-label="Distribution of the screen's probability by route">
        {totals.map((total, i) => {
          let y = H;
          const height = (Math.log10(1 + total) / top) * (H - 10);
          return (
            <g key={i}>
              <title>{`${(i / bins).toFixed(2)} to ${((i + 1) / bins).toFixed(2)}: ${total.toLocaleString("en-IN")} invoices`}</title>
              {routes.map((r) => {
                const n = byRoute[r][i] ?? 0;
                const h = total ? (n / total) * height : 0;
                y -= h;
                return <rect key={r} x={30 + i * bw + 1} y={y} width={bw - 2} height={h} fill={ROUTE_COLORS[r] ?? "#94a3b8"} />;
              })}
            </g>
          );
        })}
        {[0, 0.25, 0.5, 0.75, 1].map((t) => (
          <text key={t} x={30 + t * (W - 40)} y={H + 16} textAnchor="middle" className="axis-label">
            {t.toFixed(2)}
          </text>
        ))}
      </svg>
      <figcaption className="legend">
        {routes.map((r) => (
          <span key={r}>
            <i style={{ background: ROUTE_COLORS[r] ?? "#94a3b8" }} /> {r}
          </span>
        ))}
        <span className="muted">probability of an anomaly · invoices on a log scale</span>
      </figcaption>
    </figure>
  );
}

/** The paper's score over the latest results: a few values hold almost every invoice (the floors of 50 and 70). */
export function ScoreValues({ values }: { values: Record<string, number> }) {
  const rows = Object.entries(values).sort((a, b) => Number(a[0]) - Number(b[0]));
  const top = Math.log10(1 + Math.max(1, ...rows.map(([, n]) => n)));
  return (
    <ul className="barlist">
      {rows.map(([score, n]) => (
        <li key={score}>
          <span className="barlist-label mono">score {score}</span>
          <span className="barlist-track">
            <span className="barlist-fill" style={{ width: `${(Math.log10(1 + n) / top) * 100}%`, background: Number(score) >= 70 ? "#f87171" : Number(score) >= 50 ? "#fb923c" : "#94a3b8" }} />
          </span>
          <span className="barlist-value">{n.toLocaleString("en-IN")}</span>
        </li>
      ))}
    </ul>
  );
}

const STORY_COLORS: Record<string, string> = { ledger: "#64748b", approval: "#0d9488", email: "#7c3aed", audit: "#047857", review: "#ea580c" };

/** The life of one invoice, in order. */
export function StoryTimeline({ steps }: { steps: StoryStep[] }) {
  return (
    <ol className="story">
      {steps.map((s, i) => (
        <li key={`${s.at}-${i}`}>
          <span className="story-dot" style={{ background: STORY_COLORS[s.kind] ?? "#94a3b8" }} aria-hidden />
          <div>
            <span className="muted small mono">{s.at.slice(0, 19) || "undated"}</span> <span className="story-kind">{s.kind}</span>
            <div className="small">{s.what}</div>
          </div>
        </li>
      ))}
    </ol>
  );
}
