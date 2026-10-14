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

/** Colour of a risk score from 0 to 100: green, amber, orange, red, as the risk levels of the scorer. */
export function riskColor(score: number): string {
  if (score >= 70) return "#f87171";
  if (score >= 50) return "#fb923c";
  if (score >= 30) return "#fbbf24";
  return "#34d399";
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
