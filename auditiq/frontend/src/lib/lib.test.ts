import { describe, expect, it } from "vitest";
import { cell, inr, percent, ratio, riskColor, routeLabel, rupeesCompact, stateLabel } from "./format";
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
    expect(riskColor(10)).toBe("#34d399");
    expect(riskColor(30)).toBe("#fbbf24");
    expect(riskColor(50)).toBe("#fb923c");
    expect(riskColor(70)).toBe("#f87171");
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
