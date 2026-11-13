import type { Interval, Results } from "../api/types";

export const BENCH = ["bench_seed_101", "bench_seed_202", "bench_seed_303"];

export function v(x: Interval | undefined): number | null {
  return x?.value ?? null;
}

/** The ledgers of the results from the smallest to the largest: the benchmark ledgers, then large, then huge. */
export function ledgersBySize(results: Results): string[] {
  const rank = (name: string) => ["bench", "large", "huge"].findIndex((prefix) => name.startsWith(prefix));
  return Object.keys(results.benchmark).sort((a, b) => rank(a) - rank(b) || a.localeCompare(b));
}

/** The share of an anomaly class a system detects, as the mean over the three benchmark ledgers. */
export function classMean(results: Results, system: string, cls: string): number | null {
  const values = BENCH.map((d) => v(results.benchmark[d]?.per_class[system]?.[cls])).filter((x): x is number => x !== null);
  return values.length ? values.reduce((a, b) => a + b, 0) / values.length : null;
}

/** Mean over the three benchmark ledgers. */
export function meanOver(results: Results, system: string, metric: string): number | null {
  const values = BENCH.map((d) => v(results.benchmark[d]?.metrics[system]?.[metric])).filter((x): x is number => x !== null);
  return values.length ? values.reduce((a, b) => a + b, 0) / values.length : null;
}
