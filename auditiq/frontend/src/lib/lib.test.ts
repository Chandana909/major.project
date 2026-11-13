import { describe, expect, it } from "vitest";
import { cell, explainScore, inr, percent, ratio, RISK_COLORS, riskColor, routeLabel, rupeesCompact, scoreBreakdown, stateLabel } from "./format";
import { CLUSTERS, EDGES, edgePoints, NODES, smoothPath } from "./architecture";
import { monthLabel, niceMax, short } from "./chart";
import { changeRows } from "./policy";
import { meanOver } from "./results";
import { results } from "../test/fixtures";

describe("formatting", () => {
  it("writes amounts the Indian way", () => {
    expect(inr(1250000)).toBe("12,50,000");
    expect(inr(694181.12, 2)).toBe("6,94,181.12");
    expect(inr(null)).toBe("–");
    expect(rupeesCompact(25000000)).toBe("₹2.5 Cr");
    expect(rupeesCompact(450000)).toBe("₹4.5 L");
    expect(rupeesCompact(9500)).toBe("₹9,500");
  });

  it("colours a risk score by the risk levels of the scorer", () => {
    expect(riskColor(10)).toBe(RISK_COLORS.LOW);
    expect(riskColor(30)).toBe(RISK_COLORS.MEDIUM);
    expect(riskColor(50)).toBe(RISK_COLORS.HIGH);
    expect(riskColor(70)).toBe(RISK_COLORS.CRITICAL);
  });

  it("says why a score is what it is", () => {
    const one = scoreBreakdown([{ severity: "critical", confidence: null }]);
    expect(one).toMatchObject({ sum: 30, floor: 70, floorFrom: "critical", score: 70 });
    expect(explainScore(one)).toBe("1 critical: weights 30, raised to the critical floor 70");
    // Two invoices at 70 are told apart by what they contain.
    const two = scoreBreakdown([{ severity: "critical", confidence: 1 }, { severity: "high", confidence: 1 }]);
    expect(two.score).toBe(70);
    expect(explainScore(two)).toBe("1 critical, 1 high: weights 50, raised to the critical floor 70");
    expect(explainScore(scoreBreakdown([{ severity: "high", confidence: 1 }, { severity: "high", confidence: 1 }, { severity: "high", confidence: 1 }]))).toBe("3 high: weights 60");
    // Weighted: a flag below confidence 2/3 counts in proportion and lifts nothing.
    const doubtful = scoreBreakdown([{ severity: "critical", confidence: 0.5 }], true);
    expect(doubtful).toMatchObject({ sum: 15, floor: 0, score: 15 });
    expect(explainScore(scoreBreakdown([]))).toBe("No finding");
  });

  it("names routes, states and values", () => {
    expect(routeLabel("sample")).toBe("Sampled review");
    expect(routeLabel(null)).toBe("Not audited");
    expect(stateLabel("PENDING_REVIEW")).toBe("Waiting for review");
    expect(stateLabel("SOMETHING_NEW")).toBe("SOMETHING_NEW");
    expect(ratio(0.71428)).toBe("0.714");
    expect(percent(0.307)).toBe("30.7%");
    expect(cell(true)).toBe("yes");
    expect(cell("")).toBe("–");
    expect(cell({ a: 1 })).toBe('{"a":1}');
  });
});

describe("policy changes", () => {
  it("lists one row per changed value and one per role whose limit changed", () => {
    const rows = changeRows([
      { clause: "2.1.1", parameter: "amount_tolerance_pct", from: 1, to: 0.5 },
      { clause: "5.1.1", parameter: "approval_limits", from: { Manager: 100000, CFO: 1 }, to: { Manager: 50000, CFO: 1 } },
    ]);
    expect(rows).toEqual([
      { rule: "2.1.1", parameter: "amount_tolerance_pct", from: "1", to: "0.5" },
      { rule: "5.1.1", parameter: "approval_limits: Manager", from: "100000", to: "50000" },
    ]);
  });
});

describe("results", () => {
  it("averages a metric over the three benchmark ledgers", () => {
    expect(meanOver(results, "C1", "detection_f1")).toBeCloseTo(0.833);
    expect(meanOver(results, "C9", "detection_f1")).toBeNull();
  });
});

describe("chart scales", () => {
  it("rounds axes up to 1, 2 or 5 times a power of ten and shortens counts", () => {
    expect([niceMax(0), niceMax(7), niceMax(13), niceMax(260), niceMax(5000)]).toEqual([1, 10, 20, 500, 5000]);
    expect([short(950), short(1234), short(34567), short(1_500_000)]).toEqual(["950", "1.2k", "35k", "1.5M"]);
    expect(monthLabel("2025-04")).toBe("Apr 25");
  });
});

describe("the architecture diagram", () => {
  const boxes = [...NODES, ...CLUSTERS];
  const inside = (a: { x: number; y: number; w: number; h: number }, b: { x: number; y: number; w: number; h: number }) =>
    a.x >= b.x && a.y >= b.y && a.x + a.w <= b.x + b.w && a.y + a.h <= b.y + b.h;

  it("connects only components that exist", () => {
    const ids = new Set(boxes.map((b) => b.id));
    expect(EDGES.filter((e) => !ids.has(e.from) || !ids.has(e.to))).toEqual([]);
    expect(new Set(NODES.map((n) => n.id)).size).toBe(NODES.length);
  });

  it("places every component inside a subsystem and no two on top of each other", () => {
    expect(NODES.filter((n) => !CLUSTERS.some((c) => inside(n, c))).map((n) => n.id)).toEqual([]);
    const overlaps = NODES.flatMap((a, i) =>
      NODES.slice(i + 1).filter((b) => a.x < b.x + b.w && b.x < a.x + a.w && a.y < b.y + b.h && b.y < a.y + a.h).map((b) => `${a.id}/${b.id}`),
    );
    expect(overlaps).toEqual([]);
  });

  it("draws every connection as horizontal and vertical runs", () => {
    const slanted = EDGES.filter((e) => {
      const pts = edgePoints(e);
      return pts.slice(1).some(([x, y], i) => Math.abs(x - pts[i][0]) > 2 && Math.abs(y - pts[i][1]) > 2);
    }).map((e) => `${e.from}->${e.to}`);
    expect(slanted).toEqual([]);
    expect(smoothPath([[0, 0], [10, 0], [10, 10]])).toBe("M0,0 L5,0 Q10,0 10,5 L10,10");
  });
});
