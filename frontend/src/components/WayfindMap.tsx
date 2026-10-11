/**
 * Floor-plan directions inside a library.
 *
 * Drawn as a real top-down plan: walls and windows, entrance gates, information
 * counter, self-checkout, double-sided shelf ranges with book spines (non-fiction
 * in Dewey order, fiction A–Z), reading lounge, study tables, children's corner,
 * lift, stairs, toilets. The route is animated from the doors to the exact range.
 *
 * It is a schematic of the layout every NLB branch shares (not to scale).
 */
import { useMemo } from "react";

export interface Target {
  callNumber: string;
  branch: string;
}

const W = 800;
const H = 560;

// --- layout constants -------------------------------------------------------
const MAIN_X = 390;                 // centre aisle
const NF_Y = 58;                    // non-fiction ranges top
const NF_H = 92;
const NF_W = 34;
const NF_X0 = 56;
const NF_STEP = 54;
const NF_AISLE_Y = 164;             // aisle under the non-fiction ranges
const FIC_ROWS = [214, 258, 302, 346, 390];
const FIC_X = 44;
const FIC_W = 260;
const KIDS = { x: 450, y: 406, w: 300, h: 112 };
const ENTRANCE: [number, number] = [MAIN_X, 538];

const NF_LABELS = [
  "General & computing", "Philosophy & psychology", "Religion", "Social sciences", "Language",
  "Science & maths", "Technology & health", "Arts & recreation", "Literature", "History & geography",
];

const SPINES = ["#6E2A2A", "#1F4D3A", "#223A5E", "#8A6D1F", "#4A4E69", "#5C3D6E", "#2E6B6B", "#A1512A", "#9A3B3B", "#2F5D8A"];

function hash(s: string): number {
  let h = 2166136261;
  for (let i = 0; i < s.length; i++) h = Math.imul(h ^ s.charCodeAt(i), 16777619);
  return Math.abs(h);
}

const nfX = (i: number) => NF_X0 + i * NF_STEP;

interface Parsed {
  kind: "nonfiction" | "fiction" | "children" | "unknown";
  dewey?: string;
  author?: string;
  bayIndex?: number;
  row?: number;
  end: [number, number];
  zoneLabel: string;
}

export function parseCallNumber(callNumber: string): Parsed {
  const cn = callNumber.trim();
  const upper = cn.toUpperCase();
  const dewey = cn.match(/(\d{3})(\.\d+)?/);
  const author = (cn.match(/\s([A-Z]{2,4})\s*$/i) || [])[1];
  if (/^(J|JS|JP|JE)\b/.test(upper) || /CHILD/i.test(upper)) {
    return { kind: "children", author, dewey: dewey?.[0], end: [KIDS.x - 12, KIDS.y + 56], zoneLabel: "Children's corner" };
  }
  if (/\bFIC\b|FICTION/i.test(upper) || !dewey) {
    // A–Z across the five rows: pick a row by the author's first letter
    const letter = (author || "M").toUpperCase().charCodeAt(0) - 65;
    const row = Math.min(4, Math.max(0, Math.floor((letter / 26) * 5)));
    return { kind: "fiction", author, row, end: [FIC_X + FIC_W + 14, FIC_ROWS[row] + 9], zoneLabel: "Fiction A–Z" };
  }
  const idx = Math.min(9, Math.max(0, Math.floor(parseInt(dewey[1], 10) / 100)));
  return { kind: "nonfiction", dewey: dewey[0], author, bayIndex: idx, end: [nfX(idx) + NF_W / 2, NF_Y + NF_H + 8], zoneLabel: `${idx}00s · ${NF_LABELS[idx]}` };
}

function pathFor(p: Parsed): string {
  const [ex, ey] = ENTRANCE;
  const [tx, ty] = p.end;
  if (p.kind === "nonfiction") return `M ${ex} ${ey} L ${MAIN_X} ${NF_AISLE_Y} L ${tx} ${NF_AISLE_Y} L ${tx} ${ty}`;
  if (p.kind === "fiction") return `M ${ex} ${ey} L ${MAIN_X} ${ty} L ${tx} ${ty}`;
  if (p.kind === "children") return `M ${ex} ${ey} L ${MAIN_X} ${ty} L ${tx} ${ty}`;
  return `M ${ex} ${ey} L ${MAIN_X} 470`;
}

export function stepsFor(p: Parsed, callNumber: string): { icon: string; text: string }[] {
  const look = { icon: "🔎", text: `Look for ${callNumber} on the spines — they run in order, usually at eye level.` };
  if (p.kind === "nonfiction") {
    const dir = (p.bayIndex ?? 5) < 6 ? "left" : "right";
    return [
      { icon: "🚪", text: "Go through the gates and walk straight up the main aisle, past the counter." },
      { icon: dir === "left" ? "↰" : "↱", text: `At the top of the aisle, turn ${dir} along the non-fiction ranges.` },
      { icon: "📚", text: `Stop at the ${p.bayIndex}00s range — ${NF_LABELS[p.bayIndex ?? 0]}.` },
      look,
    ];
  }
  if (p.kind === "children") {
    return [
      { icon: "🚪", text: "Go through the gates and walk up the main aisle." },
      { icon: "↱", text: "Turn right into the children's corner — the one with the round rug." },
      p.author ? { icon: "🔎", text: `The low shelves run by author — look for ${p.author}.` } : look,
    ];
  }
  if (p.kind === "fiction") {
    const rows = ["A–E", "F–J", "K–O", "P–T", "U–Z"];
    return [
      { icon: "🚪", text: "Go through the gates and walk up the main aisle." },
      { icon: "↰", text: `Turn left into the fiction stacks and go to the ${rows[p.row ?? 2]} range.` },
      p.author ? { icon: "🔎", text: `Fiction is shelved A–Z by author surname — find ${p.author}.` } : look,
    ];
  }
  return [{ icon: "🛎️", text: "Ask at the counter — this call number doesn't match a zone on the map." }];
}

// --- drawing helpers -----------------------------------------------------------
/** A double-sided shelf range with book spines on both faces. */
function Range({ x, y, w, h, vertical, seed, active }: { x: number; y: number; w: number; h: number; vertical: boolean; seed: string; active?: boolean }) {
  const spines: JSX.Element[] = [];
  const len = vertical ? h : w;
  const thick = vertical ? w : h;
  let pos = 3;
  let i = 0;
  while (pos < len - 3) {
    const size = 3 + (hash(seed + i) % 4);
    const colour = SPINES[hash(seed + "c" + i) % SPINES.length];
    const sideA = vertical ? { x: x + 2, y: y + pos, width: thick / 2 - 3, height: size } : { x: x + pos, y: y + 2, width: size, height: thick / 2 - 3 };
    const sideB = vertical ? { x: x + thick / 2 + 1, y: y + pos, width: thick / 2 - 3, height: size } : { x: x + pos, y: y + thick / 2 + 1, width: size, height: thick / 2 - 3 };
    spines.push(<rect key={`a${i}`} {...sideA} fill={colour} opacity={0.85} />);
    spines.push(<rect key={`b${i}`} {...sideB} fill={SPINES[hash(seed + "d" + i) % SPINES.length]} opacity={0.85} />);
    pos += size + 1;
    i++;
  }
  return (
    <g className={`range ${active ? "active" : ""}`}>
      <rect x={x} y={y} width={w} height={h} rx="3" className="range-body" />
      {spines}
      {vertical ? <line x1={x + w / 2} x2={x + w / 2} y1={y} y2={y + h} className="range-mid" /> : <line x1={x} x2={x + w} y1={y + h / 2} y2={y + h / 2} className="range-mid" />}
    </g>
  );
}

function RoundTable({ x, y, r = 16 }: { x: number; y: number; r?: number }) {
  return (
    <g className="furniture">
      {[45, 135, 225, 315].map((a) => (
        <rect key={a} x={x + (r + 9) * Math.cos((a * Math.PI) / 180) - 5} y={y + (r + 9) * Math.sin((a * Math.PI) / 180) - 5} width="10" height="10" rx="3" className="chair" />
      ))}
      <circle cx={x} cy={y} r={r} className="table" />
    </g>
  );
}

function LongTable({ x, y, w }: { x: number; y: number; w: number }) {
  const seats = Math.floor(w / 30);
  return (
    <g className="furniture">
      {Array.from({ length: seats }, (_, i) => (
        <g key={i}>
          <rect x={x + 10 + i * 30} y={y - 12} width="12" height="8" rx="3" className="chair" />
          <rect x={x + 10 + i * 30} y={y + 22} width="12" height="8" rx="3" className="chair" />
          <rect x={x + 12 + i * 30} y={y + 3} width="8" height="6" rx="1" className="screen" />
        </g>
      ))}
      <rect x={x} y={y} width={w} height="18" rx="4" className="table" />
    </g>
  );
}

function Armchair({ x, y }: { x: number; y: number }) {
  return (
    <g className="furniture">
      <rect x={x} y={y} width="22" height="20" rx="7" className="armchair" />
      <rect x={x + 4} y={y + 6} width="14" height="10" rx="4" className="armchair-seat" />
    </g>
  );
}

function Plant({ x, y }: { x: number; y: number }) {
  return (
    <g className="plant">
      <circle cx={x} cy={y} r="9" />
      <circle cx={x - 4} cy={y - 3} r="5" />
      <circle cx={x + 4} cy={y - 2} r="5" />
    </g>
  );
}

export default function WayfindMap({ target }: { target: Target }) {
  const parsed = useMemo(() => parseCallNumber(target.callNumber), [target.callNumber]);
  const d = useMemo(() => pathFor(parsed), [parsed]);
  const steps = useMemo(() => stepsFor(parsed, target.callNumber), [parsed, target.callNumber]);
  const [tx, ty] = parsed.end;

  return (
    <div className="wayfind">
      <svg className="map floorplan" viewBox={`0 0 ${W} ${H}`} role="img" aria-label={`Floor-plan directions to ${target.callNumber} at ${target.branch}`}>
        <defs>
          <pattern id="carpet" width="8" height="8" patternUnits="userSpaceOnUse">
            <rect width="8" height="8" fill="#eef1f5" />
            <circle cx="4" cy="4" r="0.8" fill="#dfe4ea" />
          </pattern>
          <pattern id="rug" width="14" height="14" patternUnits="userSpaceOnUse">
            <rect width="14" height="14" fill="#ffe9cf" />
            <circle cx="7" cy="7" r="3" fill="#ffd5a6" />
          </pattern>
          <pattern id="wood" width="60" height="6" patternUnits="userSpaceOnUse">
            <rect width="60" height="6" fill="#efe6d8" />
            <line x1="0" x2="60" y1="5.5" y2="5.5" stroke="#e3d6c2" strokeWidth="1" />
          </pattern>
        </defs>

        {/* floor */}
        <rect x="12" y="12" width={W - 24} height={H - 24} rx="10" fill="url(#carpet)" />
        {/* zone carpets */}
        <rect x={FIC_X - 12} y={FIC_ROWS[0] - 20} width={FIC_W + 60} height={FIC_ROWS[4] - FIC_ROWS[0] + 64} rx="12" className="carpet-fiction" />
        <rect x={440} y={196} width={316} height={200} rx="12" className="carpet-reading" />
        <rect x={KIDS.x} y={KIDS.y} width={KIDS.w} height={KIDS.h} rx="14" className="carpet-kids" />
        {/* aisles (wood) */}
        <rect x={MAIN_X - 22} y={NF_AISLE_Y - 14} width="44" height={H - NF_AISLE_Y - 20} rx="8" fill="url(#wood)" className="aisle" />
        <rect x={28} y={NF_AISLE_Y - 14} width={W - 56} height="28" rx="8" fill="url(#wood)" className="aisle" />

        {/* walls + windows */}
        <rect x="12" y="12" width={W - 24} height={H - 24} rx="10" className="wall" />
        {[[60, 280], [320, 560], [600, 740]].map(([a, b]) => (
          <line key={a} x1={a} x2={b} y1="12" y2="12" className="window" />
        ))}
        <line x1="12" x2="12" y1="80" y2="400" className="window" />

        {/* non-fiction ranges */}
        {NF_LABELS.map((label, i) => {
          const active = parsed.kind === "nonfiction" && parsed.bayIndex === i;
          return (
            <g key={label}>
              <Range x={nfX(i)} y={NF_Y} w={NF_W} h={NF_H} vertical seed={`nf${i}`} active={active} />
              <text x={nfX(i) + NF_W / 2} y={NF_Y - 8} textAnchor="middle" className={`bay-label ${active ? "on" : ""}`}>
                {i}00s
              </text>
            </g>
          );
        })}
        <text x={NF_X0} y={NF_AISLE_Y + 34} className="zone-title">📚 Non-fiction · Dewey order 000 → 999</text>

        {/* toilets, lift, stairs (top right) */}
        <g className="service">
          <rect x="606" y={NF_Y} width="64" height="40" rx="6" />
          <text x="638" y={NF_Y + 25} textAnchor="middle" className="svc-label">🚻</text>
          <rect x="680" y={NF_Y} width="40" height="40" rx="6" />
          <text x="700" y={NF_Y + 25} textAnchor="middle" className="svc-label">🛗</text>
          <rect x="730" y={NF_Y} width="42" height="40" rx="6" />
          {[0, 1, 2, 3, 4].map((i) => (
            <line key={i} x1="734" x2="768" y1={NF_Y + 8 + i * 7} y2={NF_Y + 8 + i * 7} className="stair" />
          ))}
          <text x="688" y={NF_Y + 60} textAnchor="middle" className="svc-caption">Toilets · Lift · Stairs</text>
        </g>

        {/* fiction stacks */}
        <g className={`zone ${parsed.kind === "fiction" ? "active" : ""}`}>
          {FIC_ROWS.map((y, r) => (
            <g key={y}>
              <Range x={FIC_X} y={y} w={FIC_W} h={18} vertical={false} seed={`fic${r}`} active={parsed.kind === "fiction" && parsed.row === r} />
              <text x={FIC_X + FIC_W + 8} y={y + 13} className="row-label">{["A–E", "F–J", "K–O", "P–T", "U–Z"][r]}</text>
            </g>
          ))}
          <text x={FIC_X} y={FIC_ROWS[4] + 40} className="zone-title">📖 Fiction · A–Z by author</text>
          <Armchair x={FIC_X + 200} y={FIC_ROWS[4] + 24} />
          <Armchair x={FIC_X + 228} y={FIC_ROWS[4] + 24} />
        </g>

        {/* reading lounge + study (right) */}
        <g className="zone">
          <RoundTable x={490} y={238} />
          <RoundTable x={560} y={238} />
          <RoundTable x={630} y={238} />
          <Armchair x={690} y={216} />
          <Armchair x={716} y={216} />
          <Armchair x={690} y={246} />
          <Armchair x={716} y={246} />
          <text x={456} y={212} className="zone-title">☕ Reading lounge</text>
          <LongTable x={470} y={312} w={270} />
          <LongTable x={470} y={356} w={270} />
          <text x={456} y={297} className="zone-title">💻 Study & computers</text>
        </g>

        {/* children's corner */}
        <g className={`zone ${parsed.kind === "children" ? "active" : ""}`}>
          <circle cx={KIDS.x + 110} cy={KIDS.y + 60} r="42" fill="url(#rug)" className="rug" />
          <Range x={KIDS.x + 180} y={KIDS.y + 16} w={100} h={14} vertical={false} seed="k1" active={parsed.kind === "children"} />
          <Range x={KIDS.x + 180} y={KIDS.y + 44} w={100} h={14} vertical={false} seed="k2" active={parsed.kind === "children"} />
          <Range x={KIDS.x + 180} y={KIDS.y + 72} w={100} h={14} vertical={false} seed="k3" active={parsed.kind === "children"} />
          <circle cx={KIDS.x + 36} cy={KIDS.y + 90} r="10" className="beanbag" />
          <circle cx={KIDS.x + 62} cy={KIDS.y + 98} r="10" className="beanbag" />
          <text x={KIDS.x + 14} y={KIDS.y + 24} className="zone-title">🧸 Children's corner</text>
        </g>

        {/* counter, self-checkout, new arrivals (near entrance) */}
        <g className="service">
          <path d="M 150 468 Q 150 442 176 442 L 330 442 Q 356 442 356 468 L 356 486 L 150 486 Z" className="counter" />
          <text x="253" y="470" textAnchor="middle" className="counter-label">🛎️ Information & returns</text>
          {[0, 1, 2].map((i) => (
            <g key={i}>
              <rect x={440 + i * 36} y="456" width="24" height="24" rx="5" className="kiosk" />
              <rect x={446 + i * 36} y="461" width="12" height="9" rx="1" className="screen" />
            </g>
          ))}
          <text x="490" y="498" textAnchor="middle" className="svc-caption">Self-checkout</text>
          <rect x="44" y="446" width="84" height="40" rx="6" className="display" />
          <text x="86" y="470" textAnchor="middle" className="svc-caption">✨ New arrivals</text>
        </g>

        {/* entrance: security gates + sliding doors */}
        <g className="service">
          <rect x={MAIN_X - 34} y="506" width="8" height="22" rx="2" className="gate" />
          <rect x={MAIN_X + 26} y="506" width="8" height="22" rx="2" className="gate" />
          <rect x={MAIN_X - 40} y={H - 16} width="36" height="8" rx="2" className="door" />
          <rect x={MAIN_X + 4} y={H - 16} width="36" height="8" rx="2" className="door" />
          <text x={MAIN_X + 54} y={H - 26} className="zone-title">🚪 Entrance</text>
        </g>

        <Plant x={30} y={30} />
        <Plant x={770} y={530} />
        <Plant x={420} y={180} />

        {/* route */}
        <path key={`s-${d}`} d={d} className="map-path-shadow" />
        <path key={d} d={d} className="map-path" />
        <g className="map-walker" style={{ offsetPath: `path("${d}")` } as React.CSSProperties}>
          <circle r="12" className="walker-bg" />
          <text y="5" textAnchor="middle" className="walker-emoji">🚶</text>
        </g>
        <g className="map-pin" transform={`translate(${tx} ${ty})`}>
          <circle r="14" className="pin-ring" />
          <circle r="6" className="pin-dot" />
        </g>
        {parsed.kind === "nonfiction" && (
          <g className="flag" transform={`translate(${Math.min(W - 160, Math.max(20, tx - 70))} 18)`}>
            <rect width="140" height="24" rx="12" />
            <text x="70" y="16" textAnchor="middle">📍 {target.callNumber}</text>
          </g>
        )}
      </svg>

      <ol className="steps">
        {steps.map((s, i) => (
          <li key={i} style={{ animationDelay: `${400 + i * 260}ms` }}>
            <span className="step-icon" aria-hidden="true">{s.icon}</span>
            <span>{s.text}</span>
          </li>
        ))}
      </ol>
      <p className="hint map-note">
        Schematic of the layout every NLB branch shares (not to scale): non-fiction in Dewey order, fiction A–Z, children's in its own corner. Follow the call-number signs for the exact range.
      </p>
    </div>
  );
}
