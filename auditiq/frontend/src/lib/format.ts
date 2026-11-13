// Formatting shared by every page.

/** Indian digit grouping: 1250000 -> "12,50,000". */
export function inr(value: number | null | undefined, decimals = 0): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "–";
  return value.toLocaleString("en-IN", { minimumFractionDigits: decimals, maximumFractionDigits: decimals });
}

/** Compact rupees: 1250000 -> "₹12.5 L", 25000000 -> "₹2.5 Cr". */
export function rupeesCompact(value: number): string {
  if (value >= 1e7) return `₹${(value / 1e7).toFixed(value >= 1e8 ? 0 : 1)} Cr`;
  if (value >= 1e5) return `₹${(value / 1e5).toFixed(value >= 1e6 ? 0 : 1)} L`;
  return `₹${inr(value)}`;
}

export function count(value: number | null | undefined): string {
  if (value === null || value === undefined) return "–";
  return value.toLocaleString("en-IN");
}

export function ratio(value: number | null | undefined, digits = 3): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "n/a";
  return value.toFixed(digits);
}

export function percent(value: number | null | undefined, digits = 1): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "n/a";
  return `${(value * 100).toFixed(digits)}%`;
}

/** The colours of the risk levels of the scorer (below 30, 30 to 49, 50 to 69, 70 and above), and of blacklisted vendors. */
export const RISK_COLORS = { LOW: "#34d399", MEDIUM: "#fbbf24", HIGH: "#fb923c", CRITICAL: "#f87171" } as const;
export const BLACKLISTED_COLOR = "#a78bfa";
/** Severities of findings, in the colours of the risk levels they lead to; low is grey, as it never escalates. */
export const SEVERITY_COLORS: Record<string, string> = { critical: "#f87171", high: "#fb923c", medium: "#fbbf24", low: "#94a3b8" };

/** Colour of a risk score from 0 to 100: green, amber, orange, red. */
export function riskColor(score: number): string {
  if (score >= 70) return RISK_COLORS.CRITICAL;
  if (score >= 50) return RISK_COLORS.HIGH;
  if (score >= 30) return RISK_COLORS.MEDIUM;
  return RISK_COLORS.LOW;
}

/** The weights and floors of the scorer (auditiq/scoring.py): a flag adds its weight, and any critical or high
 * flag lifts the score to at least its floor. Only flags with confidence of at least 2/3 lift a weighted score. */
export const SEVERITY_WEIGHTS = { critical: 30, high: 20, medium: 10, low: 5 } as const;
export const SEVERITY_FLOORS = { critical: 70, high: 50 } as const;
const THETA = 2 / 3 - 1e-9;

export interface ScoreBreakdown {
  counts: Record<keyof typeof SEVERITY_WEIGHTS, number>;
  /** What each severity adds before the cap of 100 (weighted by confidence for a weighted score). */
  parts: Record<keyof typeof SEVERITY_WEIGHTS, number>;
  sum: number;
  floor: number;
  floorFrom: "critical" | "high" | null;
  score: number;
}

/** How a score is made from the findings: the weights summed, and the floor if one applies. */
export function scoreBreakdown(flags: { severity: string; confidence: number | null }[], weighted = false): ScoreBreakdown {
  const counts = { critical: 0, high: 0, medium: 0, low: 0 };
  const parts = { critical: 0, high: 0, medium: 0, low: 0 };
  let sum = 0;
  let floorFrom: ScoreBreakdown["floorFrom"] = null;
  for (const f of flags) {
    const severity = f.severity as keyof typeof SEVERITY_WEIGHTS;
    if (!(severity in SEVERITY_WEIGHTS)) continue;
    const confidence = f.confidence ?? 1;
    counts[severity] += 1;
    const added = SEVERITY_WEIGHTS[severity] * (weighted ? confidence : 1);
    parts[severity] += added;
    sum += added;
    if ((severity === "critical" || severity === "high") && (!weighted || confidence >= THETA)) {
      if (severity === "critical" || floorFrom === null) floorFrom = severity;
    }
  }
  sum = Math.min(100, sum);
  const floor = floorFrom ? SEVERITY_FLOORS[floorFrom] : 0;
  return { counts, parts, sum, floor, floorFrom, score: Math.max(sum, floor) };
}

/** One line that says why a score is what it is, e.g. "1 critical, 1 high: weights 50, critical floor 70". */
export function explainScore(b: ScoreBreakdown): string {
  const parts = (Object.keys(b.counts) as (keyof typeof b.counts)[]).filter((k) => b.counts[k]).map((k) => `${b.counts[k]} ${k}`);
  if (!parts.length) return "No finding";
  const weights = `weights ${Number(b.sum.toFixed(1))}`;
  if (b.floorFrom && b.floor > b.sum) return `${parts.join(", ")}: ${weights}, raised to the ${b.floorFrom} floor ${b.floor}`;
  return `${parts.join(", ")}: ${weights}`;
}

export function routeLabel(route: string | null | undefined): string {
  return { approve: "Approved", sample: "Sampled review", escalate: "Escalated" }[route ?? ""] ?? "Not audited";
}

export const STATES: Record<string, string> = {
  AUTO_APPROVED: "Approved automatically",
  PENDING_REVIEW: "Waiting for review",
  NOT_SAMPLED: "Sampled queue, not selected",
  REVIEW_APPROVED: "Approved by reviewer",
  REVIEW_REJECTED: "Rejected by reviewer",
  REVIEW_OVERRIDDEN: "Overridden by reviewer",
};

export function stateLabel(state: string | null | undefined): string {
  return state ? STATES[state] ?? state : "Not audited";
}

/** Any record value as short text. */
export function cell(value: unknown): string {
  if (value === null || value === undefined || value === "") return "–";
  if (typeof value === "number") return Number.isInteger(value) ? count(value) : inr(value, 2);
  if (typeof value === "boolean") return value ? "yes" : "no";
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}
