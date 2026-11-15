// The architecture of the platform as an interactive React Flow canvas, drawn from lib/architecture.ts.
//
// It follows React Flow's own patterns: subsystems are parent (group) nodes and components their children; every
// component is a custom node with a handle on each side; edges are smoothstep paths; the tooltip is a NodeToolbar,
// so it stays attached to its component at any zoom; inputs and outputs are traced the way getIncomers and
// getOutgoers define them. Hover (or focus) a component: what flows into it turns blue, what it sends out turns
// amber, everything else fades. Click to pin the trace and open the details below the canvas.
import "@xyflow/react/dist/style.css";
import { Background, BackgroundVariant, Controls, Handle, MarkerType, MiniMap, NodeToolbar, Panel, Position, ReactFlow, ReactFlowProvider, useReactFlow, useStore, type Edge, type Node, type NodeProps } from "@xyflow/react";
import { createContext, memo, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import {
  absoluteBox, EDGE_STYLE, EDGES, edgeSides, GROUPS, groupSize, KIND_STYLE, localPosition, neighbours, NODE_H, NODE_W, NODES, TRACE,
  type ArchGroup, type ArchNode, type NodeKind, type Side,
} from "../lib/architecture";

export interface DiagramProps {
  /** Short live figures shown on the components, by component id. */
  live?: Record<string, string>;
  /** Stage ids run by the chosen configuration; components of other stages are dimmed. */
  active?: Set<string> | null;
  selected?: string | null;
  onSelect?: (id: string | null) => void;
}

type Trace = "rest" | "focus" | "in" | "out" | "both" | "faded";

interface CardData extends Record<string, unknown> {
  node: ArchNode;
  trace: Trace;
  off: boolean;
  selected: boolean;
  tip: boolean;
  /** Where the tooltip opens: the side with the fewest traced components, so it hides as little of the trace as it can. */
  tipSide: Position;
  badge?: string;
}

interface LaneData extends Record<string, unknown> {
  group: ArchGroup;
  faded: boolean;
}

const Hover = createContext<{ enter: (id: string) => void; leave: () => void; toggle: (id: string) => void }>({ enter: () => {}, leave: () => {}, toggle: () => {} });

const Z_CARD = 10;
const SIDE: Record<Side, Position> = { l: Position.Left, r: Position.Right, t: Position.Top, b: Position.Bottom };
const TITLE = new Map(NODES.map((n) => [n.id, n.title]));

const ICON: Record<NodeKind, ReactNode> = {
  external: <><circle cx="12" cy="12" r="8.5" /><path d="M3.5 12h17M12 3.5c3 3.2 3 13.8 0 17M12 3.5c-3 3.2-3 13.8 0 17" /></>,
  code: <path d="M8.5 7 3.5 12l5 5M15.5 7l5 5-5 5" />,
  llm: <path d="M12 3.2 13.9 9 19.8 11l-5.9 2L12 18.8 10.1 13 4.2 11l5.9-2z" />,
  person: <><circle cx="12" cy="8" r="3.8" /><path d="M4.5 20.5c.6-3.9 3.7-5.8 7.5-5.8s6.9 1.9 7.5 5.8" /></>,
  queue: <><path d="m12 3.5 8.5 4.6L12 12.7 3.5 8.1z" /><path d="m3.5 12.2 8.5 4.6 8.5-4.6M3.5 16.2l8.5 4.6 8.5-4.6" /></>,
  store: <><ellipse cx="12" cy="5.8" rx="7.5" ry="2.8" /><path d="M4.5 5.8v12.4c0 1.5 3.4 2.8 7.5 2.8s7.5-1.3 7.5-2.8V5.8M4.5 12c0 1.5 3.4 2.8 7.5 2.8s7.5-1.3 7.5-2.8" /></>,
  graph: <><circle cx="6" cy="6.5" r="2.4" /><circle cx="18" cy="8" r="2.4" /><circle cx="10.5" cy="18" r="2.4" /><path d="m8.4 6.8 7.2.9M7 8.7l2.5 7M16.6 10l-4.6 6.1" /></>,
  serve: <><rect x="3.5" y="4.5" width="17" height="12" rx="2" /><path d="M8.5 20.5h7M12 16.5v4" /></>,
  model: <><rect x="6.5" y="6.5" width="11" height="11" rx="2" /><path d="M9.5 3v3.5M14.5 3v3.5M9.5 17.5V21M14.5 17.5V21M3 9.5h3.5M3 14.5h3.5M17.5 9.5H21M17.5 14.5H21" /></>,
  ops: <><path d="m12 3 8.5 4.7v8.6L12 21l-8.5-4.7V7.7z" /><path d="m3.5 7.7 8.5 4.7 8.5-4.7M12 12.4V21" /></>,
};

function Glyph({ kind, size = 16 }: { kind: NodeKind; size?: number }) {
  return (
    <svg viewBox="0 0 24 24" width={size} height={size} fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      {ICON[kind]}
    </svg>
  );
}

function Flow({ title, edges, side }: { title: string; edges: { id: string; label: string }[]; side: "in" | "out" }) {
  const shown = edges.slice(0, 6);
  return (
    <div className="arch-tip-flow">
      <span className="arch-tip-head">
        <i style={{ background: TRACE[side] }} /> {title} · {edges.length}
      </span>
      {edges.length === 0 ? (
        <span className="arch-tip-none">nothing</span>
      ) : (
        <ul>
          {shown.map((e, i) => (
            <li key={`${e.id}-${i}`}>
              <b>{TITLE.get(e.id)}</b>
              <span>{e.label}</span>
            </li>
          ))}
          {edges.length > shown.length && <li className="arch-tip-more">+ {edges.length - shown.length} more</li>}
        </ul>
      )}
    </div>
  );
}

const Card = memo(function Card({ data }: NodeProps<Node<CardData>>) {
  const { node, trace, off, selected, tip, tipSide, badge } = data;
  const hover = useContext(Hover);
  const style = KIND_STYLE[node.kind];
  const { inputs, outputs } = neighbours(node.id);
  const dim = off || trace === "faded";
  return (
    <>
      <NodeToolbar isVisible={tip} position={tipSide} offset={14} className="arch-tip" align="center">
        <div className="arch-tip-kind" style={{ color: style.color }}>
          <Glyph kind={node.kind} size={13} /> {style.label}
          {node.stage && <span className="arch-tip-stage">stage {node.stage}</span>}
        </div>
        <strong className="arch-tip-title">{node.title}</strong>
        <p>{node.detail}</p>
        {badge && <p className="arch-tip-live">Now: {badge}</p>}
        {node.files && (
          <div className="arch-tip-files">
            {node.files.slice(0, 3).map((f) => (
              <code key={f}>{f}</code>
            ))}
          </div>
        )}
        <div className="arch-tip-flows">
          <Flow title="Receives from" side="in" edges={inputs.map((e) => ({ id: e.from, label: e.label }))} />
          <Flow title="Sends to" side="out" edges={outputs.map((e) => ({ id: e.to, label: e.label }))} />
        </div>
      </NodeToolbar>
      {(["l", "r", "t", "b"] as Side[]).map((s) => (
        <Handle key={`t-${s}`} id={`t-${s}`} type="target" position={SIDE[s]} isConnectable={false} className="arch-handle" />
      ))}
      {(["l", "r", "t", "b"] as Side[]).map((s) => (
        <Handle key={`s-${s}`} id={`s-${s}`} type="source" position={SIDE[s]} isConnectable={false} className="arch-handle" />
      ))}
      <div
        className={`arch-card nopan nodrag ${node.kind} trace-${trace} ${dim ? "dim" : ""} ${off ? "off" : ""} ${selected ? "selected" : ""}`}
        style={{ ["--kind" as string]: style.color, pointerEvents: "all" }}
        role="button"
        tabIndex={0}
        aria-pressed={selected}
        aria-label={`${node.title}: ${node.detail}`}
        onMouseEnter={() => hover.enter(node.id)}
        onMouseLeave={hover.leave}
        onFocus={() => hover.enter(node.id)}
        onBlur={hover.leave}
        onClick={() => hover.toggle(node.id)}
        onKeyDown={(ev) => {
          if (ev.key === "Enter" || ev.key === " ") {
            ev.preventDefault();
            hover.toggle(node.id);
          }
        }}
      >
        <span className="arch-icon">
          <Glyph kind={node.kind} />
        </span>
        <span className="arch-text">
          <span className={`arch-title ${node.kind === "queue" ? "mono" : ""}`}>{node.title}</span>
          <span className="arch-sub">{node.sub}</span>
        </span>
        {badge && <span className="arch-badge">{badge}</span>}
        {(trace === "in" || trace === "out" || trace === "both") && (
          <span className={`arch-flag ${trace}`}>{trace === "in" ? "input" : trace === "out" ? "output" : "in · out"}</span>
        )}
      </div>
    </>
  );
});

const Lane = memo(function Lane({ data }: NodeProps<Node<LaneData>>) {
  const { group, faded } = data;
  return (
    <div className={`arch-lane ${faded ? "faded" : ""}`} style={{ ["--tone" as string]: group.tone }}>
      <div className="arch-lane-head">
        <span className="arch-lane-title">{group.title}</span>
        <span className="arch-lane-note">{group.note}</span>
      </div>
    </div>
  );
});

const nodeTypes = { card: Card, lane: Lane };

const TIP_W = 344;
const TIP_H = 450;

/**
 * Where a component's tooltip opens: among the sides where it fits inside the canvas, the one with the fewest of the
 * component's traced neighbours (so it hides as little of the trace as it can); below, above, right, left on a tie.
 * When it fits nowhere, the side with the most room.
 */
function quietSide(id: string, view: { x: number; y: number; zoom: number; width: number; height: number }): Position {
  const at = absoluteBox(NODES.find((n) => n.id === id)!);
  const { inputs, outputs } = neighbours(id);
  const count: Record<Side, number> = { b: 0, t: 0, r: 0, l: 0 };
  for (const other of new Set([...inputs.map((e) => e.from), ...outputs.map((e) => e.to)])) {
    const b = absoluteBox(NODES.find((n) => n.id === other)!);
    const dx = b.x - at.x, dy = b.y - at.y;
    if (Math.abs(dy) >= Math.abs(dx) * 0.5 && dy !== 0) count[dy > 0 ? "b" : "t"] += 1;
    else count[dx > 0 ? "r" : "l"] += 1;
  }
  const left = at.x * view.zoom + view.x, top = at.y * view.zoom + view.y;
  const right = left + at.w * view.zoom, bottom = top + at.h * view.zoom;
  const room: Record<Side, number> = { b: view.height - bottom - TIP_H, t: top - TIP_H, r: view.width - right - TIP_W, l: left - TIP_W };
  const order: Side[] = ["b", "t", "r", "l"];
  const fits = order.filter((s) => room[s] >= 0);
  const best = fits.length
    ? fits.reduce((a, s) => (count[s] < count[a] ? s : a))
    : order.reduce((a, s) => (room[s] > room[a] ? s : a));
  return SIDE[best];
}

function Canvas({ live = {}, active = null, selected = null, onSelect, full, setFull }: DiagramProps & { full: boolean; setFull: (f: boolean) => void }) {
  const [hover, setHover] = useState<string | null>(null);
  const focus = hover ?? selected;
  const flow = useReactFlow();

  const width = useStore((s) => s.width);
  const height = useStore((s) => s.height);
  const [tx, ty, zoom] = useStore((s) => s.transform);

  const off = useMemo(() => new Set(NODES.filter((n) => active && n.stage && !active.has(n.stage)).map((n) => n.id)), [active]);

  const trace = useMemo(() => {
    const t = new Map<string, Trace>();
    if (!focus) return t;
    for (const n of NODES) t.set(n.id, "faded");
    t.set(focus, "focus");
    for (const e of EDGES) {
      if (e.to === focus && e.from !== focus) t.set(e.from, t.get(e.from) === "out" ? "both" : "in");
      if (e.from === focus && e.to !== focus) t.set(e.to, t.get(e.to) === "in" ? "both" : "out");
    }
    return t;
  }, [focus]);

  const nodes = useMemo<Node[]>(() => {
    const lanes: Node<LaneData>[] = GROUPS.map((g) => {
      const { w, h } = groupSize(g);
      const faded = !!focus && !NODES.some((n) => n.group === g.id && trace.get(n.id) !== "faded");
      return { id: `g-${g.id}`, type: "lane", position: { x: g.x, y: g.y }, data: { group: g, faded }, style: { width: w, height: h }, width: w, height: h,
        draggable: false, selectable: false, focusable: false, zIndex: 0 };
    });
    const cards: Node<CardData>[] = NODES.map((n) => ({
      id: n.id,
      type: "card",
      parentId: `g-${n.group}`,
      extent: "parent",
      position: localPosition(n),
      width: NODE_W,
      height: NODE_H,
      style: { width: NODE_W, height: NODE_H },
      draggable: false,
      selectable: false,
      focusable: false,
      zIndex: n.id === hover ? Z_CARD + 1 : Z_CARD,
      data: { node: n, trace: trace.get(n.id) ?? "rest", off: off.has(n.id), selected: selected === n.id, tip: hover === n.id,
        tipSide: hover === n.id ? quietSide(n.id, { x: tx, y: ty, zoom, width, height }) : Position.Bottom, badge: live[n.id] },
    }));
    return [...lanes, ...cards];
    // The viewport is read when the hover changes; panning with a tooltip open keeps its side.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [focus, hover, selected, trace, off, live]);

  const edges = useMemo<Edge[]>(() => EDGES.map((e, i) => {
    const kind = e.kind ?? "data";
    const base = EDGE_STYLE[kind];
    const dir = !focus ? null : e.to === focus ? "in" : e.from === focus ? "out" : null;
    const faded = (focus && !dir) || off.has(e.from) || off.has(e.to);
    const color = dir ? TRACE[dir] : base.color;
    const { source, target } = edgeSides(e);
    return {
      id: `e${i}`,
      source: e.from,
      target: e.to,
      sourceHandle: `s-${source}`,
      targetHandle: `t-${target}`,
      type: "smoothstep",
      pathOptions: { borderRadius: 14, offset: 16 },
      animated: !!dir,
      selectable: false,
      focusable: false,
      // React Flow lifts an edge between child nodes to the higher of its two nodes' layers plus its own zIndex:
      // a negative offset keeps every line under the cards (and the traced ones above the rest).
      zIndex: dir ? 2 - Z_CARD : 1 - Z_CARD,
      className: `arch-edge ${dir ? `hot ${dir}` : ""} ${faded ? "faded" : ""}`,
      style: { stroke: color, strokeWidth: dir ? 2.2 : 1.3, strokeDasharray: dir ? undefined : base.dash },
      markerEnd: { type: MarkerType.ArrowClosed, color, width: 14, height: 14 },
      label: dir ? e.label : undefined,
      labelStyle: { fill: color, fontWeight: 650, fontSize: 11 },
      labelBgStyle: { fill: "#ffffff", fillOpacity: 0.96, stroke: `${color}55`, strokeWidth: 1 },
      labelBgPadding: [6, 3] as [number, number],
      labelBgBorderRadius: 6,
    };
  }), [focus, off]);

  const hoverApi = useMemo(() => ({
    enter: (id: string) => setHover(id),
    leave: () => setHover(null),
    toggle: (id: string) => onSelect?.(selected === id ? null : id),
  }), [onSelect, selected]);

  // Fit the whole platform whenever the canvas changes size (entering or leaving full screen, a resized window).
  useEffect(() => {
    if (!width || !height) return;
    const t = window.setTimeout(() => flow.fitView({ padding: 0.04, duration: 250 }), 40);
    return () => window.clearTimeout(t);
  }, [width, height, flow]);

  useEffect(() => {
    const key = (ev: KeyboardEvent) => {
      if (ev.key === "Escape") {
        if (full) setFull(false);
        else onSelect?.(null);
      }
    };
    window.addEventListener("keydown", key);
    return () => window.removeEventListener("keydown", key);
  }, [full, setFull, onSelect]);

  const minimapColor = useCallback((n: Node) => (n.type === "lane" ? "transparent" : KIND_STYLE[(n.data as CardData).node.kind].color), []);

  return (
    <Hover.Provider value={hoverApi}>
      <ReactFlow
        nodes={nodes}
        edges={edges}
        nodeTypes={nodeTypes}
        fitView
        fitViewOptions={{ padding: 0.04 }}
        minZoom={0.2}
        maxZoom={2.2}
        nodesDraggable={false}
        nodesConnectable={false}
        elementsSelectable={false}
        zoomOnScroll={false}
        zoomOnDoubleClick={false}
        preventScrolling={false}
        panOnScroll={false}
        onPaneClick={() => onSelect?.(null)}
        proOptions={{ hideAttribution: true }}
        aria-label="Architecture of AuditIQ"
      >
        <Background variant={BackgroundVariant.Dots} gap={22} size={1.3} color="#c7d2e0" />
        <Controls showInteractive={false} position="bottom-right" />
        <MiniMap pannable zoomable position="bottom-left" style={{ width: 168, height: 84 }} nodeColor={minimapColor} nodeBorderRadius={6} maskColor="rgba(241, 245, 249, 0.72)" className="arch-minimap" />
        <Panel position="top-left" className="arch-hint">
          <span><i style={{ background: TRACE.in }} /> feeds in</span>
          <span><i style={{ background: TRACE.out }} /> feeds out</span>
          <span className="muted">Hover to trace · click to pin · Ctrl + scroll to zoom</span>
          <button type="button" className="arch-expand" onClick={() => setFull(!full)} aria-pressed={full}>
            {full ? "Exit full screen" : "Full screen"}
          </button>
        </Panel>
      </ReactFlow>
    </Hover.Provider>
  );
}

export function ArchitectureDiagram(props: DiagramProps) {
  const [full, setFull] = useState(false);
  return (
    <div className={`arch-canvas ${full ? "full" : ""}`}>
      <ReactFlowProvider>
        <Canvas {...props} full={full} setFull={setFull} />
      </ReactFlowProvider>
    </div>
  );
}
