// The platform as a 3D city: every subsystem a glowing platform, every component a piece on it shaped by what it
// is (a database is a stack of discs, a Kafka topic a stack of slabs, a model stage a turning crystal), and every
// connection an arc with data flowing along it. Hover a component: what feeds it glows blue, what it feeds glows
// amber, the rest fades. Click it: the page that shows it at work opens. The pitch tour flies the camera from one
// subsystem to the next. Laid out from the same data as the 2D map (lib/architecture.ts).
import { Grid, Html, Line, OrbitControls, RoundedBox } from "@react-three/drei";
import { Canvas, useFrame, useThree } from "@react-three/fiber";
import { memo, useEffect, useMemo, useRef, useState } from "react";
import * as THREE from "three";
import type { OrbitControls as OrbitControlsImpl } from "three-stdlib";
import { absoluteBox, bounds, demoOf, EDGES, GROUPS, groupSize, KIND_STYLE, neighbours, NODES, type ArchNode, type NodeKind } from "../lib/architecture";

/** Colours of the kinds on the dark scene: the 2D palette, lifted for a dark background. */
const GLOW: Record<NodeKind, string> = {
  external: "#94a3b8", code: "#2dd4bf", llm: "#a78bfa", person: "#fbbf24", queue: "#fb923c",
  store: "#60a5fa", graph: "#818cf8", serve: "#4ade80", model: "#e879f9", ops: "#cbd5e1",
};
const IN = "#38bdf8";
const OUT = "#fbbf24";
const TOUR = "#5eead4";
const S = 1 / 100;                       // canvas units of the 2D layout to world units
const BOX = bounds();
const CX = BOX.x + BOX.w / 2, CZ = BOX.y + BOX.h / 2;

type Trace = "rest" | "focus" | "in" | "out" | "both" | "tour" | "faded";

function world(n: ArchNode): THREE.Vector3 {
  const b = absoluteBox(n);
  return new THREE.Vector3((b.x + b.w / 2 - CX) * S, 0, (b.y + b.h / 2 - CZ) * S);
}
const POS = new Map(NODES.map((n) => [n.id, world(n)]));

/**
 * The city is laid out on a floor (x across, z down the page, y up) and then stood upright, facing the viewer like
 * the 2D map: a quarter turn about x takes z (down the page) to -y (down the screen) and height to depth, so every
 * piece stands out towards the camera. This gives a point of the layout its place in the world.
 */
const UPRIGHT: [number, number, number] = [Math.PI / 2, 0, 0];
function onWall(v: THREE.Vector3): THREE.Vector3 {
  return new THREE.Vector3(v.x, -v.z, v.y);
}

/** The arc of a connection: up from the source, over, down into the target; higher when it goes further. */
function arc(from: string, to: string): THREE.QuadraticBezierCurve3 {
  const a = POS.get(from)!.clone().setY(0.42), b = POS.get(to)!.clone().setY(0.42);
  const mid = a.clone().lerp(b, 0.5);
  mid.y = 0.6 + a.distanceTo(b) * 0.16;
  return new THREE.QuadraticBezierCurve3(a, mid, b);
}
const CURVES = EDGES.map((e) => arc(e.from, e.to));
const CURVE_POINTS = CURVES.map((c) => c.getPoints(28));

export interface SceneProps {
  /** Components of the current tour step; the rest fades. */
  tour?: string[] | null;
  /** A path drawn through the platform (the last tour step). */
  path?: string[] | null;
  live?: Record<string, string>;
  onOpen: (id: string) => void;
}

function useTrace(hover: string | null, tour: string[] | null | undefined, path: string[] | null | undefined) {
  return useMemo(() => {
    const nodes = new Map<string, Trace>();
    const edges = new Map<number, "in" | "out" | "tour">();
    if (hover) {
      for (const n of NODES) nodes.set(n.id, "faded");
      nodes.set(hover, "focus");
      EDGES.forEach((e, i) => {
        if (e.to === hover && e.from !== hover) {
          nodes.set(e.from, nodes.get(e.from) === "out" ? "both" : "in");
          edges.set(i, "in");
        }
        if (e.from === hover && e.to !== hover) {
          nodes.set(e.to, nodes.get(e.to) === "in" ? "both" : "out");
          edges.set(i, "out");
        }
      });
    } else if (path?.length) {
      for (const n of NODES) nodes.set(n.id, "faded");
      for (const id of path) nodes.set(id, "tour");
      const pairs = new Set(path.slice(1).map((id, i) => `${path[i]}>${id}`));
      EDGES.forEach((e, i) => pairs.has(`${e.from}>${e.to}`) && edges.set(i, "tour"));
    } else if (tour?.length) {
      const on = new Set(tour);
      for (const n of NODES) nodes.set(n.id, on.has(n.id) ? "tour" : "faded");
      EDGES.forEach((e, i) => on.has(e.from) && on.has(e.to) && edges.set(i, "tour"));
    }
    return { nodes, edges };
  }, [hover, tour, path]);
}

/** The piece standing on a component's tile: its shape says what kind of thing it is. */
function Piece({ kind, color, glow, opacity }: { kind: NodeKind; color: string; glow: number; opacity: number }) {
  const spin = useRef<THREE.Group>(null);
  useFrame(({ clock }, dt) => {
    if (!spin.current) return;
    if (kind === "llm" || kind === "graph") spin.current.rotation.y += dt * 0.8;
    if (kind === "model") spin.current.rotation.z += dt * 0.9;
    if (kind === "llm") spin.current.position.y = 0.42 + Math.sin(clock.elapsedTime * 2) * 0.04;
  });
  const mat = <meshStandardMaterial color={color} emissive={color} emissiveIntensity={glow} roughness={0.35} metalness={0.25} transparent opacity={opacity} />;
  switch (kind) {
    case "store":
      return (
        <group>
          {[0.1, 0.22, 0.34].map((y) => (
            <mesh key={y} position={[0, y, 0]}>
              <cylinderGeometry args={[0.2, 0.2, 0.09, 28]} />
              {mat}
            </mesh>
          ))}
        </group>
      );
    case "queue":
      return (
        <group>
          {[0.08, 0.18, 0.28].map((y, i) => (
            <mesh key={y} position={[0, y, 0]}>
              <boxGeometry args={[0.46 - i * 0.06, 0.06, 0.32]} />
              {mat}
            </mesh>
          ))}
        </group>
      );
    case "llm":
      return (
        <group ref={spin} position={[0, 0.42, 0]}>
          <mesh>
            <octahedronGeometry args={[0.22, 0]} />
            {mat}
          </mesh>
          <mesh scale={1.35}>
            <octahedronGeometry args={[0.22, 0]} />
            <meshBasicMaterial color={color} wireframe transparent opacity={opacity * 0.35} />
          </mesh>
        </group>
      );
    case "model":
      return (
        <group position={[0, 0.34, 0]}>
          <mesh>
            <sphereGeometry args={[0.17, 28, 28]} />
            {mat}
          </mesh>
          <group ref={spin} rotation={[Math.PI / 2.6, 0, 0]}>
            <mesh>
              <torusGeometry args={[0.28, 0.018, 8, 48]} />
              <meshBasicMaterial color={color} transparent opacity={opacity} toneMapped={false} />
            </mesh>
          </group>
        </group>
      );
    case "person":
      return (
        <group position={[0, 0.06, 0]}>
          <mesh position={[0, 0.17, 0]}>
            <capsuleGeometry args={[0.1, 0.16, 6, 16]} />
            {mat}
          </mesh>
          <mesh position={[0, 0.42, 0]}>
            <sphereGeometry args={[0.09, 20, 20]} />
            {mat}
          </mesh>
        </group>
      );
    case "graph":
      return (
        <group ref={spin} position={[0, 0.34, 0]}>
          <mesh>
            <icosahedronGeometry args={[0.2, 0]} />
            <meshBasicMaterial color={color} wireframe transparent opacity={opacity} toneMapped={false} />
          </mesh>
          <mesh>
            <sphereGeometry args={[0.08, 16, 16]} />
            {mat}
          </mesh>
        </group>
      );
    case "serve":
      return (
        <group>
          <mesh position={[0, 0.3, 0]}>
            <boxGeometry args={[0.46, 0.3, 0.05]} />
            {mat}
          </mesh>
          <mesh position={[0, 0.1, 0]}>
            <boxGeometry args={[0.06, 0.12, 0.06]} />
            {mat}
          </mesh>
        </group>
      );
    case "ops":
      return (
        <mesh position={[0, 0.18, 0]}>
          <cylinderGeometry args={[0.22, 0.22, 0.3, 6]} />
          {mat}
        </mesh>
      );
    case "external":
      return (
        <group position={[0, 0.2, 0]}>
          <mesh>
            <boxGeometry args={[0.34, 0.34, 0.34]} />
            <meshBasicMaterial color={color} wireframe transparent opacity={opacity} toneMapped={false} />
          </mesh>
          <mesh>
            <boxGeometry args={[0.18, 0.18, 0.18]} />
            {mat}
          </mesh>
        </group>
      );
    default:
      return (
        <RoundedBox args={[0.4, 0.3, 0.4]} radius={0.06} smoothness={3} position={[0, 0.2, 0]}>
          {mat}
        </RoundedBox>
      );
  }
}

const Component3D = memo(function Component3D({ n, trace, badge, hovered, onHover, onOpen }: {
  n: ArchNode; trace: Trace; badge?: string; hovered: boolean; onHover: (id: string | null) => void; onOpen: (id: string) => void;
}) {
  const p = POS.get(n.id)!;
  const color = GLOW[n.kind];
  const faded = trace === "faded";
  const ring = trace === "in" ? IN : trace === "out" ? OUT : trace === "both" ? "#c4b5fd" : trace === "tour" ? TOUR : trace === "focus" ? color : null;
  const glow = faded ? 0.04 : trace === "rest" ? 0.35 : 0.9;
  const lift = useRef<THREE.Group>(null);
  useFrame((_, dt) => {
    if (!lift.current) return;
    const goal = hovered ? 0.12 : 0;
    lift.current.position.y += (goal - lift.current.position.y) * Math.min(1, dt * 10);
  });
  return (
    <group position={[p.x, 0, p.z]}>
      <group ref={lift}>
        <RoundedBox
          args={[1.96, 0.1, 0.66]}
          radius={0.05}
          smoothness={3}
          position={[0, 0.05, 0]}
          onPointerOver={(e) => { e.stopPropagation(); onHover(n.id); document.body.style.cursor = "pointer"; }}
          onPointerOut={() => { onHover(null); document.body.style.cursor = ""; }}
          onClick={(e) => { e.stopPropagation(); onOpen(n.id); }}
        >
          <meshStandardMaterial color={faded ? "#0b1220" : "#111a2e"} emissive={ring ?? color} emissiveIntensity={ring ? 0.32 : 0.06} roughness={0.55} metalness={0.35} transparent opacity={faded ? 0.35 : 0.96} />
        </RoundedBox>
        {ring && (
          <mesh position={[0, 0.006, 0]} rotation={[-Math.PI / 2, 0, 0]}>
            <planeGeometry args={[2.3, 0.98]} />
            <meshBasicMaterial color={ring} transparent opacity={0.22} blending={THREE.AdditiveBlending} depthWrite={false} toneMapped={false} />
          </mesh>
        )}
        <group position={[-0.7, 0.1, 0]}
          onPointerOver={(e) => { e.stopPropagation(); onHover(n.id); document.body.style.cursor = "pointer"; }}
          onPointerOut={() => { onHover(null); document.body.style.cursor = ""; }}
          onClick={(e) => { e.stopPropagation(); onOpen(n.id); }}>
          <Piece kind={n.kind} color={color} glow={glow} opacity={faded ? 0.18 : 1} />
        </group>
        <Html transform rotation={[-Math.PI / 2, 0, 0]} position={[0.26, 0.106, 0]} distanceFactor={4} pointerEvents="none" zIndexRange={[20, 0]}>
          <div className={`a3-label ${faded ? "faded" : ""} ${ring ? "lit" : ""}`} style={{ ["--kind" as string]: color }}>
            <b className={n.kind === "queue" ? "mono" : ""}>{n.title}</b>
            <span>{n.sub}</span>
          </div>
        </Html>
        {badge && !faded && (
          <Html transform rotation={[-Math.PI / 2, 0, 0]} position={[0.62, 0.106, -0.27]} distanceFactor={4} pointerEvents="none" zIndexRange={[20, 0]}>
            <div className="a3-badge" style={{ ["--kind" as string]: color }}>{badge}</div>
          </Html>
        )}
      </group>
    </group>
  );
});

function Plates({ faded }: { faded: Set<string> }) {
  return (
    <>
      {GROUPS.map((g) => {
        const { w, h } = groupSize(g);
        const x = (g.x + w / 2 - CX) * S, z = (g.y + h / 2 - CZ) * S;
        const W = w * S, H = h * S;
        const dim = faded.has(g.id);
        const outline: [number, number, number][] = [[-W / 2, 0, -H / 2], [W / 2, 0, -H / 2], [W / 2, 0, H / 2], [-W / 2, 0, H / 2], [-W / 2, 0, -H / 2]];
        return (
          <group key={g.id} position={[x, -0.04, z]}>
            <mesh rotation={[-Math.PI / 2, 0, 0]}>
              <planeGeometry args={[W, H]} />
              <meshBasicMaterial color={g.tone} transparent opacity={dim ? 0.03 : 0.09} depthWrite={false} />
            </mesh>
            <Line points={outline} color={g.tone} lineWidth={1.4} transparent opacity={dim ? 0.15 : 0.7} />
            {/* The caption lies along the plate's near edge, where no piece stands in front of it. A label in transform
                mode is centred on its position: the caption is 420 px (4.2 units) wide. */}
            <Html transform rotation={[-Math.PI / 2, 0, 0]} position={[-W / 2 + 0.1 + 2.1, 0.01, H / 2 + 0.22]} distanceFactor={4} pointerEvents="none" zIndexRange={[10, 0]}>
              <div className={`a3-plate ${dim ? "faded" : ""}`} style={{ ["--tone" as string]: g.tone }}>
                <b>{g.title}</b>
                <span>{g.note}</span>
              </div>
            </Html>
          </group>
        );
      })}
    </>
  );
}

function Edges({ edges }: { edges: Map<number, "in" | "out" | "tour"> }) {
  const any = edges.size > 0;
  return (
    <>
      {EDGES.map((e, i) => {
        const hot = edges.get(i);
        const color = hot === "in" ? IN : hot === "out" ? OUT : hot === "tour" ? TOUR : e.kind === "model" ? "#e879f9" : e.kind === "config" ? "#818cf8" : e.kind === "control" ? "#2dd4bf" : "#64748b";
        return (
          <Line key={i} points={CURVE_POINTS[i]} color={color} lineWidth={hot ? 2.4 : 1} transparent opacity={hot ? 0.95 : any ? 0.04 : 0.15}
            dashed={!hot && (e.kind === "variant" || e.kind === "config")} dashSize={0.12} gapSize={0.1} />
        );
      })}
    </>
  );
}

/** Data moving along every connection: two particles each, faster and brighter on the traced ones. */
function Particles({ edges }: { edges: Map<number, "in" | "out" | "tour"> }) {
  const mesh = useRef<THREE.InstancedMesh>(null);
  const per = 2;
  const tmp = useMemo(() => new THREE.Object3D(), []);
  const any = edges.size > 0;
  useEffect(() => {
    if (!mesh.current) return;
    const c = new THREE.Color();
    EDGES.forEach((_, i) => {
      const hot = edges.get(i);
      c.set(hot === "in" ? IN : hot === "out" ? OUT : hot === "tour" ? TOUR : "#a5f3fc");
      for (let k = 0; k < per; k++) mesh.current!.setColorAt(i * per + k, c);
    });
    if (mesh.current.instanceColor) mesh.current.instanceColor.needsUpdate = true;
  }, [edges]);
  useFrame(({ clock }) => {
    if (!mesh.current) return;
    const t0 = clock.elapsedTime;
    EDGES.forEach((_, i) => {
      const hot = edges.has(i);
      for (let k = 0; k < per; k++) {
        const t = (t0 * (hot ? 0.45 : 0.18) + k / per + i * 0.137) % 1;
        tmp.position.copy(CURVES[i].getPoint(t));
        const s = hot ? 1.5 : any ? 0 : 0.65;
        tmp.scale.setScalar(s);
        tmp.updateMatrix();
        mesh.current!.setMatrixAt(i * per + k, tmp.matrix);
      }
    });
    mesh.current.instanceMatrix.needsUpdate = true;
  });
  return (
    <instancedMesh ref={mesh} args={[undefined, undefined, EDGES.length * per]} frustumCulled={false}>
      <sphereGeometry args={[0.045, 10, 10]} />
      <meshBasicMaterial toneMapped={false} />
    </instancedMesh>
  );
}

/** The tooltip of the hovered component, floating above it. */
function Tip({ id, badge }: { id: string; badge?: string }) {
  const n = NODES.find((x) => x.id === id)!;
  const p = POS.get(id)!;
  const { inputs, outputs } = neighbours(id);
  const demo = demoOf(id);
  const title = (x: string) => NODES.find((m) => m.id === x)?.title ?? x;
  // Open above the component, or below it when it stands in the upper half of the view; slide sideways near an edge.
  const { camera, size } = useThree();
  const at = onWall(p.clone().setY(0.5)).project(camera);
  const sx = ((at.x + 1) / 2) * size.width, sy = ((1 - at.y) / 2) * size.height;
  const below = sy < size.height * 0.5;
  const shift = Math.max(180 - sx, Math.min(0, size.width - 180 - sx));
  return (
    <Html position={[p.x, 0.7, p.z]} center pointerEvents="none" zIndexRange={[100, 50]}>
      <div className={`a3-tip ${below ? "below" : ""}`} style={{ ["--kind" as string]: GLOW[n.kind], ["--shift" as string]: `${shift}px` }}>
        <span className="a3-tip-kind">{KIND_STYLE[n.kind].label}</span>
        <strong>{n.title}</strong>
        <p>{n.detail}</p>
        {badge && <p className="a3-tip-live">Now: {badge}</p>}
        <div className="a3-tip-flows">
          <div>
            <em style={{ color: IN }}>Receives from · {inputs.length}</em>
            {inputs.slice(0, 5).map((e, i) => <span key={i}>{title(e.from)}</span>)}
            {inputs.length > 5 && <span className="more">+ {inputs.length - 5} more</span>}
          </div>
          <div>
            <em style={{ color: OUT }}>Sends to · {outputs.length}</em>
            {outputs.slice(0, 5).map((e, i) => <span key={i}>{title(e.to)}</span>)}
            {outputs.length > 5 && <span className="more">+ {outputs.length - 5} more</span>}
          </div>
        </div>
        <div className="a3-tip-open">Click to open {demo.page} →</div>
      </div>
    </Html>
  );
}

/** Flies the camera to frame the components of a tour step, or the whole platform; gives way when the user drags. */
function CameraRig({ nodes }: { nodes: string[] | null }) {
  const { camera, controls } = useThree() as unknown as { camera: THREE.PerspectiveCamera; controls: OrbitControlsImpl | null };
  const goal = useRef<{ pos: THREE.Vector3; target: THREE.Vector3 } | null>(null);
  useEffect(() => {
    const ids = nodes?.length ? nodes : NODES.map((n) => n.id);
    const pts = ids.map((id) => POS.get(id)).filter((v): v is THREE.Vector3 => !!v).map(onWall);
    const box = new THREE.Box3().setFromPoints(pts);
    const center = box.getCenter(new THREE.Vector3());
    const size = box.getSize(new THREE.Vector3());
    // Distance at which the box fills the view across (the horizontal field of view) and up and down (the vertical
    // one); the camera stands back almost square to the wall, a little above and to the right for depth.
    const half = Math.tan((camera.fov * Math.PI) / 360);
    const across = (size.x / 2 + 2.9) / (half * camera.aspect);
    const deep = (size.y / 2 + 1.6) / half;
    // A step about a few subsystems is framed loosely and left of the narration card; one spanning the platform, whole.
    const step = !!nodes?.length && size.x < 12;
    const d = step ? Math.max(across, deep, 9) * 1.2 : Math.max(across, deep);
    const dir = new THREE.Vector3(0.07, 0.16, 1).normalize();
    // During the tour the narration card covers the lower left: aim left of the subject so it sits right of centre.
    const aim = center.clone().setZ(0).add(new THREE.Vector3(step ? -d * 0.2 : 0, 0, 0));
    goal.current = { target: aim, pos: aim.clone().add(dir.multiplyScalar(d)) };
  }, [nodes, camera]);
  useEffect(() => {
    if (!controls) return;
    const stop = () => (goal.current = null);
    controls.addEventListener("start", stop);
    return () => controls.removeEventListener("start", stop);
  }, [controls]);
  useFrame((_, dt) => {
    const g = goal.current;
    if (!g || !controls) return;
    const k = 1 - Math.exp(-dt * 3.2);
    camera.position.lerp(g.pos, k);
    controls.target.lerp(g.target, k);
    controls.update();
    if (camera.position.distanceTo(g.pos) < 0.02 && controls.target.distanceTo(g.target) < 0.02) goal.current = null;
  });
  return null;
}

function Scene({ tour, path, live = {}, onOpen }: SceneProps) {
  const [hover, setHover] = useState<string | null>(null);
  const { nodes, edges } = useTrace(hover, tour, path);
  // A click navigates away while the pointer is still over a component: give the cursor back on the way out.
  useEffect(() => () => void (document.body.style.cursor = ""), []);
  const fadedGroups = useMemo(() => {
    if (!nodes.size) return new Set<string>();
    return new Set(GROUPS.filter((g) => NODES.every((n) => n.group !== g.id || nodes.get(n.id) === "faded")).map((g) => g.id));
  }, [nodes]);
  const frame = path?.length ? path : tour?.length ? tour : null;
  return (
    <>
      <color attach="background" args={["#050914"]} />
      <fog attach="fog" args={["#050914", 26, 60]} />
      <ambientLight intensity={0.45} />
      <directionalLight position={[6, 10, 18]} intensity={1.2} />
      <pointLight position={[-14, 6, 8]} intensity={60} color="#818cf8" />
      <pointLight position={[14, -5, 9]} intensity={50} color="#2dd4bf" />
      <group rotation={UPRIGHT}>
        <Grid position={[0, -0.06, 0]} args={[80, 80]} cellSize={0.5} cellThickness={0.5} cellColor="#0f1b33" sectionSize={2.5} sectionThickness={0.9}
          sectionColor="#1d3557" fadeDistance={55} fadeStrength={1.6} infiniteGrid />
        <Plates faded={fadedGroups} />
        <Edges edges={edges} />
        <Particles edges={edges} />
        {NODES.map((n) => (
          <Component3D key={n.id} n={n} trace={nodes.get(n.id) ?? "rest"} badge={live[n.id]} hovered={hover === n.id} onHover={setHover} onOpen={onOpen} />
        ))}
        {hover && <Tip id={hover} badge={live[hover]} />}
      </group>
      <CameraRig nodes={frame} />
      {/* Turning is kept in front of the wall: up to about 50 degrees either way, never round to its back. */}
      <OrbitControls makeDefault enableDamping dampingFactor={0.08} minDistance={3} maxDistance={42} minPolarAngle={Math.PI * 0.22} maxPolarAngle={Math.PI * 0.78}
        minAzimuthAngle={-0.9} maxAzimuthAngle={0.9} screenSpacePanning />
    </>
  );
}

/** The 3D architecture. The caller checks WebGL first (three/layout.ts webglAvailable). */
export function ArchitectureScene(props: SceneProps & { height?: number | string }) {
  return (
    <div className="a3-scene" style={{ height: props.height ?? 680 }} role="img" aria-label="AuditIQ architecture in 3D: subsystems, components and the data flowing between them">
      <Canvas dpr={[1, 2]} camera={{ position: [2.5, 3.5, 24], fov: 38, near: 0.1, far: 200 }} gl={{ antialias: true }} onPointerMissed={() => (document.body.style.cursor = "")}>
        <Scene {...props} />
      </Canvas>
    </div>
  );
}
