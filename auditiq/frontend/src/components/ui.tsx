import type { ReactNode } from "react";
import type { Job } from "../api/types";
import { riskColor } from "../lib/format";

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

export function Kpi({ label, value, hint, tone = "default" }: {
  label: string;
  value: ReactNode;
  hint?: ReactNode;
  tone?: "default" | "good" | "warn" | "bad" | "accent";
}) {
  return (
    <div className={`kpi kpi-${tone}`}>
      <span className="kpi-label">{label}</span>
      <span className="kpi-value">{value}</span>
      {hint && <span className="kpi-hint">{hint}</span>}
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
