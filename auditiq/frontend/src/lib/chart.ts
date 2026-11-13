// Scales and labels shared by the charts.
import { RISK_COLORS } from "./format";

export const SERIES = { clean: "#94a3b8", flagged: RISK_COLORS.HIGH, escalated: RISK_COLORS.CRITICAL, primary: "#0f766e", line: "#0f172a" };
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

/** A round number at or above `value`: 1, 2 or 5 times a power of ten. */
export function niceMax(value: number): number {
  if (value <= 0) return 1;
  const power = 10 ** Math.floor(Math.log10(value));
  return ([1, 2, 5, 10].find((m) => m * power >= value) ?? 10) * power;
}

/** Short counts for axes: 950, 1.2k, 34k, 1.5M. */
export function short(value: number): string {
  if (value >= 1e6) return `${(value / 1e6).toFixed(value >= 1e7 ? 0 : 1)}M`;
  if (value >= 1e3) return `${(value / 1e3).toFixed(value >= 1e4 ? 0 : 1)}k`;
  return `${Math.round(value)}`;
}

export function percentText(value: number, digits = 1): string {
  return `${(value * 100).toFixed(digits)}%`;
}

export function monthLabel(month: string): string {
  const [year, m] = month.split("-");
  return `${MONTHS[Number(m) - 1] ?? m} ${year?.slice(2)}`;
}
