import ReactThreeTestRenderer from "@react-three/test-renderer";
import type * as THREE from "three";
import { describe, expect, it } from "vitest";
import type { QueueItem, RingEdge, RingNode, Stage, VendorPoint } from "../api/types";
import { caseGraph, policyGraph } from "../test/fixtures";
import { caseLayout } from "./caseLayout";
import { barLayout, graphLayout, layoutQueue, layoutVendors, networkLayout, SKYLINE_STEP, skylineLayout, stageEdges, stagePositions } from "./layout";
import { PipelineGraph } from "./PipelineScene";
import { BarField } from "./PolicyBars";
import { PointField, VendorField } from "./RiskConstellation";

const vendors: VendorPoint[] = Array.from({ length: 24 }, (_, i) => ({
  vendor_id: `VEND${1001 + i}`,
  vendor_name: `Vendor ${i}`,
  category: ["Logistics", "MRO", "Utilities"][i % 3],
  invoices: 1 + i,
  amount: 1000 * (i + 1),
  waiting: i % 5 === 0 ? 1 : 0,
  findings: i % 5 === 0 ? 1 : 0,
  max_risk: i % 5 === 0 ? 70 : 0,
  blacklisted: i === 23 ? 1 : 0,
}));

const stages: Stage[] = [
  { id: "extraction", label: "Evidence extraction", kind: "code" },
  { id: "controls", label: "Deterministic controls", kind: "code", feature: true },
  { id: "math_approvals", label: "Math", kind: "llm" },
  { id: "tax_identity", label: "Tax", kind: "llm" },
  { id: "vendor_intelligence", label: "Vendor", kind: "llm" },
  { id: "challenger", label: "Challenger", kind: "llm" },
  { id: "risk_score", label: "Risk score", kind: "code" },
];

describe("the geometry of the 3D views", () => {
  it("places every vendor once, in its category's sector, higher when riskier", () => {
    const { placed, categories } = layoutVendors(vendors);
    expect(placed).toHaveLength(24);
    expect(categories.map((c) => c.name)).toEqual(["Logistics", "MRO", "Utilities"]);
    const risky = placed.filter((v) => v.max_risk === 70);
    const calm = placed.filter((v) => v.max_risk === 0);
    expect(Math.min(...risky.map((v) => v.position[1]))).toBeGreaterThan(Math.max(...calm.map((v) => v.position[1])));
    expect(layoutVendors(vendors).placed.map((v) => v.position)).toEqual(placed.map((v) => v.position)); // stable
  });

  it("draws the points of a large ledger smaller, so that they do not merge", () => {
    const many = Array.from({ length: 1000 }, (_, i) => ({ ...vendors[i % 24], vendor_id: `VEND${100000 + i}` }));
    const sizeOf = (list: VendorPoint[], id: string) => layoutVendors(list).placed.find((v) => v.vendor_id === id)!.size;
    const few = layoutVendors(vendors).placed[0];
    expect(sizeOf(many, "VEND100000") / sizeOf(vendors, few.vendor_id)).toBeCloseTo(0.5, 5); // sqrt(250 / 1,000)
  });

  it("places each invoice waiting in the sector of the most severe rule it breaks, higher when riskier", () => {
    const items = ["5.1.1", "2.1.1", "5.1.1"].map((rule, i) => ({
      ...({} as QueueItem), result_id: i, invoice_id: `INV${i}`, amount: 1000 * (i + 1), rc: [70, 50, 90][i], rules: [rule, "2.2.1"],
    }));
    const { placed, sectors } = layoutQueue(items);
    expect(sectors.map((s) => s.name)).toEqual(["2.1.1", "5.1.1"]);
    const height = (id: string) => placed.find((p) => p.invoice_id === id)!.position[1];
    expect(height("INV2")).toBeGreaterThan(height("INV0"));
    expect(height("INV0")).toBeGreaterThan(height("INV1"));
  });

  it("connects consecutive stages and fans out to the parallel agents", () => {
    const active = ["extraction", "controls", "math_approvals", "tax_identity", "vendor_intelligence", "challenger", "risk_score"];
    const edges = stageEdges(active);
    expect(edges).toContainEqual(["controls", "math_approvals"]);
    expect(edges).toContainEqual(["vendor_intelligence", "challenger"]);
    expect(edges).not.toContainEqual(["math_approvals", "tax_identity"]);
    expect(edges).toHaveLength(1 + 3 + 3 + 1);
    const positions = Object.values(stagePositions(stages)).map((p) => p.join(","));
    expect(new Set(positions).size).toBe(stages.length);
  });

  it("orders the bars and scales the tallest to the same height", () => {
    const placed = barLayout([{ label: "a", value: 0.3, count: 3 }, { label: "b", value: 0.01, count: 1 }]);
    expect(placed.map((p) => p.bar.label)).toEqual(["b", "a"]);
    expect(placed[1].height).toBeCloseTo(6.08);
  });
});

describe("the 3D scenes", () => {
  it("draws one instance per vendor and a stem per vendor with invoices waiting", async () => {
    const { placed } = layoutVendors(vendors);
    const renderer = await ReactThreeTestRenderer.create(<VendorField placed={placed} />);
    const spheres = renderer.scene.find((node) => node.props.name === "vendors").instance as THREE.InstancedMesh;
    const stems = renderer.scene.find((node) => node.props.name === "stems").instance as THREE.InstancedMesh;
    expect(spheres.isInstancedMesh).toBe(true);
    expect(spheres.count).toBe(24);
    expect(spheres.instanceColor?.count).toBe(24);   // one risk colour per vendor
    expect(stems.count).toBe(vendors.filter((v) => v.waiting).length);
    await ReactThreeTestRenderer.act(async () => renderer.advanceFrames(2, 0.016));
  });

  it("draws a stem only for the points that ask for one", async () => {
    const points = layoutVendors(vendors).placed.map((v, i) => ({ ...v, color: "#34d399", stem: i < 5, pulse: i === 0 }));
    const renderer = await ReactThreeTestRenderer.create(<PointField points={points} name="invoices" />);
    const spheres = renderer.scene.find((node) => node.props.name === "invoices").instance as THREE.InstancedMesh;
    const stems = renderer.scene.find((node) => node.props.name === "stems").instance as THREE.InstancedMesh;
    expect(spheres.count).toBe(24);
    expect(stems.count).toBe(5);
    await ReactThreeTestRenderer.act(async () => renderer.advanceFrames(2, 0.016));
  });

  it("hands the clicked point to the page", async () => {
    const points = layoutVendors(vendors).placed.map((v) => ({ ...v, color: "#34d399", stem: true, pulse: false }));
    const chosen: string[] = [];
    const renderer = await ReactThreeTestRenderer.create(
      <PointField points={points} name="invoices" onSelect={(p) => chosen.push(p.vendor_id)} />,
    );
    const spheres = renderer.scene.find((node) => node.props.name === "invoices");
    await renderer.fireEvent(spheres, "click", { instanceId: 3, stopPropagation: () => undefined });
    expect(chosen).toEqual([points[3].vendor_id]);
  });

  it("draws every stage and lights only those of the configuration", async () => {
    const active = ["extraction", "controls", "risk_score"];
    const renderer = await ReactThreeTestRenderer.create(<PipelineGraph stages={stages} active={active} />);
    const groups = renderer.scene.findAll((node) => typeof node.props.name === "string" && node.props.name.startsWith("stage-"));
    expect(groups).toHaveLength(stages.length);
    await ReactThreeTestRenderer.act(async () => renderer.advanceFrames(3, 0.016));
  });

  it("draws one bar per policy", async () => {
    const bars = Array.from({ length: 14 }, (_, i) => ({ label: `policy ${i}`, value: i / 50, count: i }));
    const renderer = await ReactThreeTestRenderer.create(<BarField bars={bars} />);
    const meshes = renderer.scene.findAll((node) => typeof node.props.name === "string" && node.props.name.startsWith("bar-"));
    expect(meshes).toHaveLength(14);
  });
});

describe("the spend skyline", () => {
  it("raises one bar per category and month, the largest five units tall", () => {
    const bars = skylineLayout({ months: ["2025-04", "2025-05", "2025-06"], categories: ["MRO", "Logistics"], amounts: [[10, 20, 40], [0, 5, 10]] });
    expect(bars).toHaveLength(6);
    expect(Math.max(...bars.map((b) => b.height))).toBe(SKYLINE_STEP.height);
    expect(bars.find((b) => b.category === "Logistics" && b.month === "2025-04")!.height).toBeGreaterThan(0);     // a floor tile, not nothing
    const xs = [...new Set(bars.map((b) => b.position[0]))];
    expect(xs.reduce((t, x) => t + x, 0)).toBeCloseTo(0);                                                       // centred
  });
});

describe("the collusion network", () => {
  const nodes: RingNode[] = [1, 2, 3].flatMap((ring) => [
    { id: `a:A${ring}`, kind: "approver", ring, label: `A${ring}` },
    ...[0, 1, 2].map((k) => ({ id: `v:V${ring}${k}`, kind: "vendor" as const, ring, label: `V${ring}${k}`, amount: 1000 * (k + 1) })),
  ]);
  const edges: RingEdge[] = nodes
    .filter((n) => n.kind === "vendor")
    .map((n) => ({ source: `a:A${n.ring}`, target: n.id, ring: n.ring, kinds: ["above own limit"], invoices: 1, amount: 1, rules: { "5.1.1": 1 } }));

  it("places every member near its own ring, the same way every time", () => {
    const { placed, centres } = networkLayout(nodes, edges);
    expect(placed).toHaveLength(nodes.length);
    expect(networkLayout(nodes, edges).placed.map((n) => n.position)).toEqual(placed.map((n) => n.position));
    for (const n of placed) {
      const distance = (c: [number, number, number]) => Math.hypot(n.position[0] - c[0], n.position[2] - c[2]);
      const own = distance(centres[n.ring]);
      expect(own).toBeLessThan(Math.min(...Object.entries(centres).filter(([r]) => Number(r) !== n.ring).map(([, c]) => distance(c))));
      expect(n.position[1]).toBeGreaterThan(0);
    }
  });
});

describe("the policy graph layout", () => {
  it("places every node, the same way every time, with linked nodes nearer than the rest", () => {
    const placed = graphLayout(policyGraph.nodes, policyGraph.edges);
    expect(placed).toHaveLength(policyGraph.nodes.length);
    expect(graphLayout(policyGraph.nodes, policyGraph.edges).map((n) => n.position)).toEqual(placed.map((n) => n.position));
    const at = new Map(placed.map((n) => [n.id, n.position]));
    const distance = (a: string, b: string) => Math.hypot(...at.get(a)!.map((v, k) => v - at.get(b)![k]));
    const linked = policyGraph.edges.map((e) => distance(e.source, e.target));
    const all = placed.flatMap((a, i) => placed.slice(i + 1).map((b) => distance(a.id, b.id)));
    const mean = (xs: number[]) => xs.reduce((t, x) => t + x, 0) / xs.length;
    expect(mean(linked)).toBeLessThan(mean(all));
    expect(placed.every((n) => n.position.every(Number.isFinite))).toBe(true);
  });
});

describe("the ledger graph layout", () => {
  it("places every node, the same way every time, with rules inside and invoices outside", () => {
    const nodes = [
      ...caseGraph.nodes,
      { id: "i:INV1", kind: "invoice" as const, label: "INV1", amount: 5, risk: 70 },
    ];
    const edges = [...caseGraph.edges, { source: "i:INV1", target: "r:5.1.1", kind: "violates" }, { source: "v:VEND1041", target: "i:INV1", kind: "billed" }];
    const placed = caseLayout(nodes, edges);
    expect(placed).toHaveLength(nodes.length);
    expect(caseLayout(nodes, edges).map((n) => n.position)).toEqual(placed.map((n) => n.position));
    for (const n of placed) expect(n.position.every(Number.isFinite)).toBe(true);
    const radius = (id: string) => {
      const n = placed.find((x) => x.id === id)!;
      return Math.hypot(n.position[0], n.position[2]);
    };
    expect(radius("r:5.1.1")).toBeLessThan(radius("i:INV1"));
    expect(caseLayout([], [])).toEqual([]);
  });
});
