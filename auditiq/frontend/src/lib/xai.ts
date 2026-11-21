// Helpers of the explainable-AI views.

/** A value in [0, 1] as a colour from blue (low) through violet to red (high). */
export function rankColor(rank: number): string {
  const r = Math.round(37 + (220 - 37) * rank);
  const g = Math.round(99 + (38 - 99) * rank);
  const b = Math.round(235 + (38 - 235) * rank);
  return `rgb(${r}, ${g}, ${b})`;
}

/** The sigmoid of log-odds: a probability. */
export function probability(logOdds: number): number {
  return 1 / (1 + Math.exp(-logOdds));
}
