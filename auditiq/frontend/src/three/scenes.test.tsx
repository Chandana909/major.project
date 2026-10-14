import ReactThreeTestRenderer from "@react-three/test-renderer";
import type * as THREE from "three";
import { describe, expect, it } from "vitest";
import type { Stage, VendorPoint } from "../api/types";
import { barLayout, layoutVendors, stageEdges, stagePositions } from "./layout";
import { PipelineGraph } from "./PipelineScene";
import { BarField } from "./PolicyBars";
import { VendorField } from "./RiskConstellation";

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
