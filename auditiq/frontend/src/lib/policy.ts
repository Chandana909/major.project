import type { Change } from "../api/types";

/** One row per changed value; an approval-limit change becomes one row per role whose limit differs. */
export function changeRows(changes: Change[]): { rule: string; parameter: string; from: string; to: string }[] {
  const rows: { rule: string; parameter: string; from: string; to: string }[] = [];
  for (const c of changes) {
    if (c.to && typeof c.to === "object" && !Array.isArray(c.to)) {
      const from = (c.from ?? {}) as Record<string, unknown>;
      for (const [role, limit] of Object.entries(c.to as Record<string, unknown>)) {
        if (from[role] !== limit) rows.push({ rule: c.clause, parameter: `${c.parameter}: ${role}`, from: JSON.stringify(from[role] ?? null), to: JSON.stringify(limit) });
      }
    } else {
      rows.push({ rule: c.clause, parameter: c.parameter, from: JSON.stringify(c.from), to: JSON.stringify(c.to) });
    }
  }
  return rows;
}
