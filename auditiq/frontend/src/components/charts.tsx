// Charts of the Analytics and Overview pages: SVG drawn from the API's numbers, one axis each, a readout on hover.
import { useState, type ReactNode } from "react";
import type { Analytics, BenfordTest, LimitBand, MonthRow, VendorPoint } from "../api/types";
import { monthLabel, niceMax, percentText, SERIES, short } from "../lib/chart";
import { BLACKLISTED_COLOR, count, inr, RISK_COLORS, riskColor, rupeesCompact } from "../lib/format";

const W = 640;

/** The readout of a hovered mark, placed over the chart at the mark (coordinates in the chart's viewBox). */
function Tip({ x, y, width, height, children }: { x: number; y: number; width: number; height: number; children: ReactNode }) {
  const left = (x / width) * 100;
  return (
    <div className={`viz-tip ${left > 70 ? "left" : left < 30 ? "right" : ""}`} style={{ left: `${left}%`, top: `${(y / height) * 100}%` }} role="status">
      {children}
    </div>
  );
}

function YGrid({ max, top, bottom, left, right, format = short }: { max: number; top: number; bottom: number; left: number; right: number; format?: (v: number) => string }) {
  return (
    <g className="viz-grid">
      {[0, 0.25, 0.5, 0.75, 1].map((f) => {
        const y = bottom - f * (bottom - top);
        return (
          <g key={f}>
            <line x1={left} x2={right} y1={y} y2={y} />
            <text x={left - 6} y={y + 3} textAnchor="end">
              {format(f * max)}
            </text>
          </g>
        );
      })}
    </g>
  );
}

// ------------------------------------------------------------------ monthly volume
/** Invoices per month, split into clean, flagged and escalated: one count axis. */
export function MonthlyChart({ rows }: { rows: MonthRow[] }) {
  const [hover, setHover] = useState<number | null>(null);
  const H = 250, L = 46, R = W - 10, T = 14, B = H - 30;
  const max = niceMax(Math.max(1, ...rows.map((r) => r.invoices)));
  const band = (R - L) / Math.max(1, rows.length);
  const bar = Math.max(2, band * 0.66);
  const y = (v: number) => B - (v / max) * (B - T);
  const h = rows[hover ?? -1];
  return (
    <div className="viz">
      <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label={`Invoices per month over ${rows.length} months, clean, flagged and escalated`}>
        <YGrid max={max} top={T} bottom={B} left={L} right={R} />
        {rows.map((r, i) => {
          const x = L + i * band + (band - bar) / 2;
          const flaggedOnly = r.flagged - r.escalated;
          const segments = [
            { v: r.invoices - r.flagged, c: SERIES.clean },
            { v: flaggedOnly, c: SERIES.flagged },
            { v: r.escalated, c: SERIES.escalated },
          ];
          let base = B;
          return (
            <g key={r.month} onMouseEnter={() => setHover(i)} onMouseLeave={() => setHover(null)} className={hover === i ? "viz-hot" : ""}>
              <rect x={L + i * band} y={T} width={band} height={B - T} className="viz-hit" />
              {segments.map((s, k) => {
                const height = (s.v / max) * (B - T);
                base -= height;
                return s.v > 0 ? <rect key={k} x={x} y={base} width={bar} height={Math.max(0, height - (k ? 1 : 0))} rx={k === 2 ? 2 : 0} fill={s.c} /> : null;
              })}
              {(rows.length <= 14 || i % Math.ceil(rows.length / 12) === 0) && (
                <text x={x + bar / 2} y={B + 16} textAnchor="middle" className="viz-axis">
                  {monthLabel(r.month)}
                </text>
              )}
            </g>
          );
        })}
        <line x1={L} x2={R} y1={B} y2={B} className="viz-base" />
      </svg>
      {h && (
        <Tip x={L + (hover ?? 0) * band + band / 2} y={y(h.invoices)} width={W} height={H}>
          <strong>{monthLabel(h.month)}</strong>
          <span>{count(h.invoices)} invoices · {rupeesCompact(h.amount)}</span>
          <span>{count(h.flagged)} with findings ({percentText(h.flagged / Math.max(1, h.invoices))}) · {count(h.escalated)} escalated</span>
        </Tip>
      )}
      <Legend items={[["Clean", SERIES.clean], ["With findings", SERIES.flagged], ["Escalated", SERIES.escalated]]} />
    </div>
  );
}

export function Legend({ items }: { items: [string, string][] }) {
  return (
    <div className="legend">
      {items.map(([label, color]) => (
        <span key={label}>
          <i style={{ background: color }} /> {label}
        </span>
      ))}
    </div>
  );
}

// ------------------------------------------------------------------ Benford
/** Observed share of each leading digit (bars) against Benford's expected share (line); marked bars differ significantly. */
export function BenfordChart({ test, label }: { test: BenfordTest; label: string }) {
  const [hover, setHover] = useState<number | null>(null);
  const H = 250, L = 46, R = W - 10, T = 14, B = H - 30;
  const digits = test.digits;
  const max = niceMax(Math.max(...digits.map((d) => Math.max(d.observed, d.expected))) * 100) / 100;
  const band = (R - L) / digits.length;
  const bar = Math.max(1.5, band * (digits.length > 20 ? 0.8 : 0.6));
  const x = (i: number) => L + i * band + band / 2;
  const y = (v: number) => B - (v / max) * (B - T);
  const line = digits.map((d, i) => `${i ? "L" : "M"}${x(i).toFixed(1)},${y(d.expected).toFixed(1)}`).join(" ");
  const h = digits[hover ?? -1];
  return (
    <div className="viz">
      <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label={`${label}: observed against Benford's law, ${test.conformity}`}>
        <YGrid max={max} top={T} bottom={B} left={L} right={R} format={(v) => percentText(v, 0)} />
        {digits.map((d, i) => (
          <g key={d.digit} onMouseEnter={() => setHover(i)} onMouseLeave={() => setHover(null)} className={hover === i ? "viz-hot" : ""}>
            <rect x={L + i * band} y={T} width={band} height={B - T} className="viz-hit" />
            <rect x={x(i) - bar / 2} y={y(d.observed)} width={bar} height={Math.max(0, B - y(d.observed))} rx={digits.length > 20 ? 0 : 3}
              fill={d.significant ? SERIES.flagged : SERIES.primary} opacity={d.significant ? 1 : 0.82} />
            {(digits.length <= 10 || d.digit % 10 === 0) && (
              <text x={x(i)} y={B + 16} textAnchor="middle" className="viz-axis">
                {d.digit}
              </text>
            )}
          </g>
        ))}
        <path d={line} className="viz-line" />
        {digits.length <= 10 && digits.map((d, i) => <circle key={d.digit} cx={x(i)} cy={y(d.expected)} r={3.2} className="viz-dot" />)}
        <line x1={L} x2={R} y1={B} y2={B} className="viz-base" />
      </svg>
      {h && (
        <Tip x={x(hover ?? 0)} y={y(Math.max(h.observed, h.expected))} width={W} height={H}>
          <strong>Leading digit{digits.length > 10 ? "s" : ""} {h.digit}</strong>
          <span>{count(h.count)} invoices · {percentText(h.observed, 2)} observed</span>
          <span>{percentText(h.expected, 2)} expected · z {h.z.toFixed(2)}{h.significant ? " · significant" : ""}</span>
        </Tip>
      )}
      <Legend items={[["Observed", SERIES.primary], ["Differs significantly (z > 1.96)", SERIES.flagged], ["Benford's law", SERIES.line]]} />
    </div>
  );
}

// ------------------------------------------------------------------ amounts and limits
/** Invoices per quarter-decade of amount, with the approval limits of the active policy and the band just under each. */
export function AmountHistogram({ amounts }: { amounts: Analytics["amounts"] }) {
  const [hover, setHover] = useState<number | null>(null);
  const H = 270, L = 46, R = W - 10, T = 30, B = H - 30;
  const bins = amounts.bins;
  if (!bins.length) return <p className="muted">No amounts.</p>;
  const lo = Math.log10(bins[0].low), hi = Math.log10(bins[bins.length - 1].high);
  const xv = (v: number) => L + ((Math.log10(v) - lo) / (hi - lo)) * (R - L);
  const max = niceMax(Math.max(...bins.map((b) => b.invoices)));
  const y = (v: number) => B - (v / max) * (B - T);
  const near = amounts.near ?? 0.1;
  const decades = [];
  for (let d = Math.ceil(lo); d <= Math.floor(hi); d++) decades.push(10 ** d);
  const h = bins[hover ?? -1];
  return (
    <div className="viz">
      <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label="Invoices by amount on a logarithmic scale, with the approval limits">
        <YGrid max={max} top={T} bottom={B} left={L} right={R} />
        {amounts.limits.map((l) => (
          <g key={l.role} className="viz-limit">
            <rect x={xv(l.limit * (1 - near))} y={T} width={xv(l.limit) - xv(l.limit * (1 - near))} height={B - T} className="viz-band" />
            <line x1={xv(l.limit)} x2={xv(l.limit)} y1={T - 12} y2={B} />
            <text x={xv(l.limit)} y={T - 16} textAnchor="middle">
              {l.role}
            </text>
          </g>
        ))}
        {bins.map((b, i) => {
          const x0 = xv(b.low) + 1, x1 = xv(b.high) - 1;
          return (
            <g key={i} onMouseEnter={() => setHover(i)} onMouseLeave={() => setHover(null)} className={hover === i ? "viz-hot" : ""}>
              <rect x={x0 - 1} y={T} width={x1 - x0 + 2} height={B - T} className="viz-hit" />
              <rect x={x0} y={y(b.invoices)} width={Math.max(1, x1 - x0)} height={B - y(b.invoices)} fill={SERIES.clean} />
              <rect x={x0} y={y(b.flagged)} width={Math.max(1, x1 - x0)} height={B - y(b.flagged)} fill={SERIES.flagged} />
            </g>
          );
        })}
        {decades.map((d) => (
          <text key={d} x={xv(d)} y={B + 16} textAnchor="middle" className="viz-axis">
            {d >= 1e5 ? rupeesCompact(d).replace(".0 ", " ") : `₹${short(d)}`}
          </text>
        ))}
        <line x1={L} x2={R} y1={B} y2={B} className="viz-base" />
      </svg>
      {h && (
        <Tip x={(xv(h.low) + xv(h.high)) / 2} y={y(h.invoices)} width={W} height={H}>
          <strong>₹{inr(h.low)} to ₹{inr(h.high)}</strong>
          <span>{count(h.invoices)} invoices · {count(h.flagged)} with findings</span>
        </Tip>
      )}
      <Legend items={[["Invoices", SERIES.clean], ["With findings", SERIES.flagged], [`Within ${Math.round(near * 100)}% under a limit`, "rgba(220, 38, 38, 0.16)"]]} />
    </div>
  );
}

/** For each approval limit: invoices just under it (left) against just over it (right). Splitting piles them up on the left. */
export function LimitCliff({ limits, near = 0.1 }: { limits: LimitBand[]; near?: number }) {
  const max = Math.max(1, ...limits.map((l) => Math.max(l.below, l.above)));
  return (
    <div className="cliff" role="table" aria-label="Invoices just under and just over each approval limit">
      <div className="cliff-head" role="row">
        <span role="columnheader">Limit</span>
        <span role="columnheader" className="num">{Math.round(near * 100)}% under</span>
        <span role="columnheader" />
        <span role="columnheader">{Math.round(near * 100)}% over</span>
        <span role="columnheader" className="num">Under ÷ over</span>
      </div>
      {limits.map((l) => {
        const ratio = l.above ? l.below / l.above : null;
        return (
          <div key={l.role} className="cliff-row" role="row">
            <span role="cell">
              <strong>{l.role}</strong>
              <small>₹{inr(l.limit)}</small>
            </span>
            <span role="cell" className="cliff-bar left">
              <i style={{ width: `${(l.below / max) * 100}%` }} />
              <b>{count(l.below)}</b>
            </span>
            <span role="cell" className="cliff-axis" />
            <span role="cell" className="cliff-bar right">
              <i style={{ width: `${(l.above / max) * 100}%` }} />
              <b>{count(l.above)}</b>
            </span>
            <span role="cell" className={`num ${ratio !== null && ratio > 1.25 ? "warn-text" : ""}`}>{ratio === null ? (l.below ? "∞" : "–") : `${ratio.toFixed(2)}×`}</span>
          </div>
        );
      })}
    </div>
  );
}

// ------------------------------------------------------------------ weekdays
export function WeekdayChart({ rows }: { rows: Analytics["weekdays"] }) {
  const [hover, setHover] = useState<number | null>(null);
  const H = 220, L = 46, R = W - 10, T = 14, B = H - 30;
  const max = niceMax(Math.max(1, ...rows.map((r) => r.invoices)));
  const band = (R - L) / rows.length;
  const bar = band * 0.56;
  const y = (v: number) => B - (v / max) * (B - T);
  const h = rows[hover ?? -1];
  return (
    <div className="viz">
      <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label="Invoices by day of the week">
        <defs>
          <pattern id="weekend-hatch" width="6" height="6" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
            <rect width="6" height="6" fill={SERIES.clean} />
            <line x1="0" y1="0" x2="0" y2="6" stroke="#64748b" strokeWidth="2.4" />
          </pattern>
        </defs>
        <YGrid max={max} top={T} bottom={B} left={L} right={R} />
        {rows.map((r, i) => {
          const x = L + i * band + (band - bar) / 2;
          const weekend = i >= 5;
          return (
            <g key={r.weekday} onMouseEnter={() => setHover(i)} onMouseLeave={() => setHover(null)} className={hover === i ? "viz-hot" : ""}>
              <rect x={L + i * band} y={T} width={band} height={B - T} className="viz-hit" />
              <rect x={x} y={y(r.invoices)} width={bar} height={B - y(r.invoices)} rx={3} fill={weekend ? "url(#weekend-hatch)" : SERIES.clean} />
              <rect x={x} y={y(r.flagged)} width={bar} height={B - y(r.flagged)} fill={SERIES.flagged} />
              <text x={x + bar / 2} y={B + 16} textAnchor="middle" className="viz-axis">
                {r.weekday.slice(0, 3)}
              </text>
            </g>
          );
        })}
        <line x1={L} x2={R} y1={B} y2={B} className="viz-base" />
      </svg>
      {h && (
        <Tip x={L + (hover ?? 0) * band + band / 2} y={y(h.invoices)} width={W} height={H}>
          <strong>{h.weekday}</strong>
          <span>{count(h.invoices)} invoices · {rupeesCompact(h.amount)}</span>
          <span>{count(h.flagged)} with findings</span>
        </Tip>
      )}
      <Legend items={[["Weekday invoices", SERIES.clean], ["Weekend (hatched)", "#64748b"], ["With findings", SERIES.flagged]]} />
    </div>
  );
}

// ------------------------------------------------------------------ heatmap
/** Findings by vendor category (rows) and rule (columns): darker cells hold more findings. */
export function Heatmap({ data, titles }: { data: Analytics["categories"]; titles?: Record<string, string | null> }) {
  const max = Math.max(1, ...data.rows.flatMap((r) => r.findings));
  const shade = (v: number) => (v ? 0.12 + 0.88 * Math.sqrt(v / max) : 0);
  return (
    <div className="scroll-x">
      <table className="table heat-grid" aria-label="Findings by vendor category and rule">
        <thead>
          <tr>
            <th>Category</th>
            <th className="num">Invoices</th>
            <th className="num">With findings</th>
            {data.rules.map((r) => (
              <th key={r} className="num mono" title={titles?.[r] ?? undefined}>
                {r}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {data.rows.map((row) => (
            <tr key={row.category}>
              <td className="strong">{row.category}</td>
              <td className="num">{count(row.invoices)}</td>
              <td className="num">
                {count(row.flagged)} <span className="muted small">({percentText(row.flagged / Math.max(1, row.invoices))})</span>
              </td>
              {row.findings.map((v, i) => {
                const a = shade(v);
                return (
                  <td key={data.rules[i]} className="num heat-cell" style={{ background: v ? `rgba(15, 118, 110, ${a.toFixed(3)})` : undefined, color: a > 0.55 ? "#fff" : undefined }}
                    title={`${row.category} · rule ${data.rules[i]}${titles?.[data.rules[i]] ? ` (${titles[data.rules[i]]})` : ""}: ${v} findings`}>
                    {v || ""}
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// ------------------------------------------------------------------ concentration
/** The Lorenz curve of spend over vendors: the further it sags under the diagonal, the more concentrated the spend. */
export function LorenzChart({ data }: { data: Analytics["concentration"] }) {
  const [hover, setHover] = useState<number | null>(null);
  const S = 300, P = 34;
  const x = (v: number) => P + v * (S - P - 10);
  const y = (v: number) => S - P - v * (S - P - 10);
  const pts = data.lorenz;
  const path = pts.map(([a, b], i) => `${i ? "L" : "M"}${x(a).toFixed(1)},${y(b).toFixed(1)}`).join(" ");
  const h = pts[hover ?? -1];
  return (
    <div className="viz square">
      <svg viewBox={`0 0 ${S} ${S}`} role="img" aria-label={`Lorenz curve of spend, Gini ${data.gini?.toFixed(2)}`}>
        <g className="viz-grid">
          {[0, 0.25, 0.5, 0.75, 1].map((f) => (
            <g key={f}>
              <line x1={x(0)} x2={x(1)} y1={y(f)} y2={y(f)} />
              <text x={x(0) - 5} y={y(f) + 3} textAnchor="end">{f * 100}%</text>
              <text x={x(f)} y={y(0) + 14} textAnchor="middle">{f * 100}%</text>
            </g>
          ))}
        </g>
        <path d={`${path} L${x(1)},${y(1)} L${x(0)},${y(0)} Z`} fill="rgba(15, 118, 110, 0.16)" />
        <line x1={x(0)} y1={y(0)} x2={x(1)} y2={y(1)} className="viz-diagonal" />
        <path d={path} className="viz-line teal" />
        {pts.map(([a, b], i) => (
          <circle key={i} cx={x(a)} cy={y(b)} r={8} className="viz-hit" onMouseEnter={() => setHover(i)} onMouseLeave={() => setHover(null)} />
        ))}
        {h && <circle cx={x(h[0])} cy={y(h[1])} r={4} className="viz-dot" />}
        <text x={x(0.5)} y={S - 4} textAnchor="middle" className="viz-axis">vendors, smallest first</text>
      </svg>
      {h && (
        <Tip x={x(h[0])} y={y(h[1])} width={S} height={S}>
          <strong>{percentText(h[0], 0)} of the vendors</strong>
          <span>receive {percentText(h[1])} of the spend</span>
        </Tip>
      )}
    </div>
  );
}

// ------------------------------------------------------------------ vendor risk matrix
/** Every vendor: invoices across, share of its invoices with findings up, size by amount, colour by highest risk. */
export function VendorMatrix({ vendors, limit = 600, onSelect }: { vendors: VendorPoint[]; limit?: number; onSelect?: (v: VendorPoint) => void }) {
  const [hover, setHover] = useState<VendorPoint | null>(null);
  const H = 300, L = 46, R = W - 14, T = 14, B = H - 32;
  const shown = [...vendors].sort((a, b) => b.amount - a.amount).slice(0, limit);
  const maxX = niceMax(Math.max(1, ...shown.map((v) => v.invoices)));
  const rate = (v: VendorPoint) => Math.min(1, v.findings / Math.max(1, v.invoices));
  const maxY = Math.min(1, niceMax(Math.max(0.01, ...shown.map(rate)) * 100) / 100);
  const maxA = Math.max(1, ...shown.map((v) => v.amount));
  const x = (v: number) => L + (v / maxX) * (R - L);
  const y = (v: number) => B - (v / maxY) * (B - T);
  const r = (a: number) => 2.5 + 11 * Math.sqrt(a / maxA);
  const color = (v: VendorPoint) => (v.blacklisted ? BLACKLISTED_COLOR : riskColor(v.max_risk));
  return (
    <div className="viz">
      <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label={`Vendor risk matrix of ${shown.length} vendors`}>
        <YGrid max={maxY} top={T} bottom={B} left={L} right={R} format={(v) => percentText(v, 0)} />
        {[0.25, 0.5, 0.75, 1].map((f) => (
          <text key={f} x={x(f * maxX)} y={B + 16} textAnchor="middle" className="viz-axis">
            {short(f * maxX)}
          </text>
        ))}
        <text x={R} y={B + 28} textAnchor="end" className="viz-axis">invoices →</text>
        {shown.map((v) => (
          <circle key={v.vendor_id} cx={x(v.invoices)} cy={y(rate(v))} r={r(v.amount)} fill={color(v)} className={`viz-bubble ${hover === v ? "hot" : ""}`}
            onMouseEnter={() => setHover(v)} onMouseLeave={() => setHover(null)} onClick={() => onSelect?.(v)} />
        ))}
        <line x1={L} x2={R} y1={B} y2={B} className="viz-base" />
      </svg>
      {hover && (
        <Tip x={x(hover.invoices)} y={y(rate(hover))} width={W} height={H}>
          <strong>{hover.vendor_name}</strong>
          <span>{hover.category} · {count(hover.invoices)} invoices · {rupeesCompact(hover.amount)}</span>
          <span>{count(hover.findings)} findings · highest risk {hover.max_risk.toFixed(0)}{hover.blacklisted ? " · blacklisted" : ""}</span>
        </Tip>
      )}
      <Legend items={[["Risk below 30", RISK_COLORS.LOW], ["30 to 49", RISK_COLORS.MEDIUM], ["50 to 69", RISK_COLORS.HIGH], ["70 and above", RISK_COLORS.CRITICAL], ["Blacklisted", BLACKLISTED_COLOR]]} />
      {vendors.length > shown.length && <p className="muted small">The {count(shown.length)} vendors with the largest spend of {count(vendors.length)}.</p>}
    </div>
  );
}
