// The colours of the kinds of link between vendors and approvers, shared by the network and the page around it.

/** The colour of each kind of link; a link of several kinds takes the first of this order. */
export const LINK_COLORS: Record<string, string> = {
  "shared PAN": "#a78bfa",
  "shared GSTIN": "#2dd4bf",
  "another vendor's GSTIN": "#f472b6",
  "above own limit": "#f87171",
  "repeated findings": "#fbbf24",
  "approver hotspot": "#a3e635",
  "concentrated approvals": "#60a5fa",
  "unusual approvals": "#fcd34d",
};

export function linkColor(kinds: string[]): string {
  const first = Object.keys(LINK_COLORS).find((k) => kinds.includes(k));
  return first ? LINK_COLORS[first] : "#94a3b8";
}
