import type { ReactNode } from "react";
import type { Job } from "../api/types";
import { explainScore, riskColor, scoreBreakdown, SEVERITY_COLORS, SEVERITY_FLOORS } from "../lib/format";

export function Panel({ title, subtitle, actions, children, className = "" }: {
  title?: ReactNode;
  subtitle?: ReactNode;
  actions?: ReactNode;
  children: ReactNode;
  className?: string;
}) {
  return (
    <section className={`panel ${className}`}>
      {(title || actions) && (
        <header className="panel-head">
          <div>
            {title && <h2>{title}</h2>}
            {subtitle && <p className="muted">{subtitle}</p>}
          </div>
          {actions && <div className="panel-actions">{actions}</div>}
        </header>
      )}
      {children}
    </section>
  );
}

export function Kpi({ label, value, hint, tone = "default", share, shareLabel }: {
  label: string;
  value: ReactNode;
  hint?: ReactNode;
  tone?: "default" | "good" | "warn" | "bad" | "accent";
  /** A part of a whole, from 0 to 1, drawn as a thin bar under the value. */
  share?: number;
  shareLabel?: string;
}) {
  return (
    <div className={`kpi kpi-${tone}`}>
      <span className="kpi-label">{label}</span>
      <span className="kpi-value">{value}</span>
      {hint && <span className="kpi-hint">{hint}</span>}
      {share !== undefined && (
        <span className="kpi-share" title={shareLabel} aria-hidden>
          <i style={{ width: `${Math.min(100, Math.max(0, share * 100))}%` }} />
        </span>
      )}
    </div>
  );
}

/** How a whole divides into parts: one bar with a segment per part, and a legend with counts and shares. */
export function StackedBar({ label, parts }: { label: string; parts: { key: string; label: string; value: number; color: string }[] }) {
  const total = parts.reduce((t, p) => t + p.value, 0);
  const shown = parts.filter((p) => p.value > 0);
  return (
    <div className="stacked">
      <div className="stacked-head">
        <span className="stacked-label">{label}</span>
        <span className="muted small">{total.toLocaleString("en-IN")}</span>
      </div>
      <div className="stacked-track" role="img" aria-label={`${label}: ${shown.map((p) => `${p.label} ${p.value}`).join(", ")}`}>
        {shown.map((p) => (
          <span key={p.key} style={{ flexGrow: p.value, background: p.color }} title={`${p.label}: ${p.value.toLocaleString("en-IN")}`} />
        ))}
      </div>
      <ul className="stacked-legend">
        {parts.map((p) => (
          <li key={p.key}>
            <i style={{ background: p.color }} />
            <span>{p.label}</span>
            <strong>{p.value.toLocaleString("en-IN")}</strong>
            <span className="muted">{total ? `${((p.value / total) * 100).toFixed(1)}%` : "–"}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

/** The rules an invoice breaks, as compact chips; the title of each rule on hover. */
export function RuleChips({ rules, titles }: { rules: string[]; titles?: Record<string, string | null> }) {
  if (!rules.length) return null;
  return (
    <span className="rule-chips">
      {rules.map((r) => (
        <span key={r} className="rule-chip" title={titles?.[r] ?? undefined}>
          {r}
        </span>
      ))}
    </span>
  );
}

/** A score taken apart: what each severity adds, the lift to a floor, the threshold of 50 and the result. */
export function ScoreComposition({ title, flags, score, weighted = false }: {
  title: string;
  flags: { severity: string; confidence: number | null }[];
  score: number;
  weighted?: boolean;
}) {
  const b = scoreBreakdown(flags, weighted);
  const order = ["critical", "high", "medium", "low"] as const;
  let left = 0;
  const segments = order
    .filter((k) => b.parts[k] > 0)
    .map((k) => {
      const width = Math.max(0, Math.min(b.parts[k], 100 - left));
      const seg = { key: k, left, width, color: SEVERITY_COLORS[k] };
      left += width;
      return seg;
    });
  const lift = b.floor > b.sum ? { left: b.sum, width: b.floor - b.sum } : null;
  return (
    <div className="composition">
      <div className="composition-head">
        <span className="muted">{title}</span>
        <strong style={{ color: riskColor(score) }}>{score.toFixed(1)}</strong>
      </div>
      <div className="composition-track" role="img" aria-label={`${title} ${score.toFixed(1)}: ${explainScore(b)}`}>
        {segments.map((s) => (
          <span key={s.key} className="composition-seg" style={{ left: `${s.left}%`, width: `${s.width}%`, background: s.color }} />
        ))}
        {lift && <span className="composition-lift" style={{ left: `${lift.left}%`, width: `${lift.width}%` }} title={`lifted to the ${b.floorFrom} floor`} />}
        <span className="composition-mark" style={{ left: "50%" }} title="threshold 50" />
        {[SEVERITY_FLOORS.high, SEVERITY_FLOORS.critical].map((f) => (
          <span key={f} className="composition-tick" style={{ left: `${f}%` }} />
        ))}
      </div>
      <div className="composition-scale" aria-hidden>
        <span>0</span>
        <span style={{ left: "50%" }}>τ 50</span>
        <span style={{ left: "70%" }}>70</span>
        <span style={{ right: 0 }}>100</span>
      </div>
      <p className="score-why">{explainScore(b)}</p>
    </div>
  );
}

export function Badge({ children, tone = "neutral" }: { children: ReactNode; tone?: "neutral" | "good" | "warn" | "bad" | "accent" | "violet" }) {
  return <span className={`badge badge-${tone}`}>{children}</span>;
}

export function RouteBadge({ route }: { route: string | null | undefined }) {
  if (route === "escalate") return <Badge tone="bad">Escalated</Badge>;
  if (route === "sample") return <Badge tone="warn">Sampled review</Badge>;
  if (route === "approve") return <Badge tone="good">Approved</Badge>;
  return <Badge>Not audited</Badge>;
}

export function SeverityBadge({ severity }: { severity: string }) {
  const tone = ({ critical: "bad", high: "warn", medium: "accent", low: "neutral" } as const)[severity as "critical"] ?? "neutral";
  return <Badge tone={tone}>{severity}</Badge>;
}

/** A score from 0 to 100 as a short bar. */
export function RiskMeter({ score, label }: { score: number; label?: string }) {
  return (
    <div className="meter" aria-label={label ?? `risk ${score}`}>
      <div className="meter-track">
        <div className="meter-fill" style={{ width: `${Math.min(100, Math.max(0, score))}%`, background: riskColor(score) }} />
        <div className="meter-threshold" style={{ left: "50%" }} title="threshold 50" />
      </div>
      <span className="meter-value">{score.toFixed(1)}</span>
    </div>
  );
}

export function Loading({ what = "Loading" }: { what?: string }) {
  return (
    <div className="loading" role="status">
      <span className="spinner" aria-hidden />
      {what}…
    </div>
  );
}

export function ErrorBox({ error, onRetry }: { error: Error | null; onRetry?: () => void }) {
  if (!error) return null;
  const problems = (error as { problems?: string[] }).problems ?? [];
  return (
    <div className="error" role="alert">
      <strong>{error.message}</strong>
      {problems.length > 0 && (
        <ul>
          {problems.map((p) => (
            <li key={p}>{p}</li>
          ))}
        </ul>
      )}
      {onRetry && (
        <button className="btn btn-ghost" onClick={onRetry}>
          Try again
        </button>
      )}
    </div>
  );
}

export function JobProgress({ job }: { job: Job | null }) {
  if (!job || job.status === "done") return null;
  const share = job.total ? job.done / job.total : null;
  return (
    <div className="job" role="status">
      <div className="job-bar">
        <div className={`job-fill ${share === null ? "indeterminate" : ""}`} style={share === null ? undefined : { width: `${share * 100}%` }} />
      </div>
      <span className="muted">
        {job.status === "failed" ? `Failed: ${job.error}` : share === null ? `Working… ${job.seconds.toFixed(0)} s` : `${job.done.toLocaleString("en-IN")} of ${job.total.toLocaleString("en-IN")} · ${job.seconds.toFixed(0)} s`}
      </span>
    </div>
  );
}

/** Horizontal bars for a short list of labelled counts. */
export function BarList({ rows, max }: { rows: { key: string; label: ReactNode; value: number; color?: string; note?: ReactNode }[]; max?: number }) {
  const top = max ?? Math.max(1, ...rows.map((r) => r.value));
  return (
    <ul className="barlist">
      {rows.map((r) => (
        <li key={r.key}>
          <span className="barlist-label">{r.label}</span>
          <span className="barlist-track">
            <span className="barlist-fill" style={{ width: `${(r.value / top) * 100}%`, background: r.color }} />
          </span>
          <span className="barlist-value">{r.value.toLocaleString("en-IN")}</span>
          {r.note && <span className="barlist-note">{r.note}</span>}
        </li>
      ))}
    </ul>
  );
}

export function Empty({ children }: { children: ReactNode }) {
  return <div className="empty">{children}</div>;
}
