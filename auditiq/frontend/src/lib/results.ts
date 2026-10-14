import type { Interval, Results } from "../api/types";

export const BENCH = ["bench_seed_101", "bench_seed_202", "bench_seed_303"];

export function v(x: Interval | undefined): number | null {
  return x?.value ?? null;
}

/** Mean over the three benchmark ledgers. */
export function meanOver(results: Results, system: string, metric: string): number | null {
  const values = BENCH.map((d) => v(results.benchmark[d]?.metrics[system]?.[metric])).filter((x): x is number => x !== null);
  return values.length ? values.reduce((a, b) => a + b, 0) / values.length : null;
}
