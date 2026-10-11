/**
 * Floor-plan directions inside a library.
 *
 * Drawn as a top-down plan: walls and windows, entrance gates, information counter,
 * self-checkout, double-sided shelf ranges with book spines (non-fiction in Dewey order,
 * three shelf units per bay; fiction A–Z), reading lounge, study tables, children's
 * corner, lift, stairs, toilets. The plan is seeded by the branch (wayfind.ts), so each
 * library looks different but always the same. Schematic, not to scale.
 *
 * Motion (CSS only, reduced-motion safe): "You are here" pulses 3 times, the route draws
 * (900 ms), a walker follows it (1200 ms), then the shelf unit, row and label light up
 * (300 ms). Steps light in sync; tapping a step or Replay runs it again.
 */
import { useMemo, useState, type CSSProperties } from "react";
import {
  FIC_ROWS, FIC_SECTIONS, FIC_W, FIC_X, H, KIDS, MAIN_X, NF_AISLE_Y, NF_H, NF_LABELS, NF_W, NF_Y, ROW_NAMES, UNIT_H, W, DOOR_Y,
  hash, locate, parseCallNumber, planFor, planSignature, routeFor, stepsFor,
} from "../wayfind";
import { t, useLang, type Key } from "../i18n";

export { parseCallNumber, stepsFor };

export interface Target {
  callNumber: string;
  branch: string;
  /** optional branch code; the plan is seeded by it when given, else by the branch name */
  code?: string;
}

const SPINES = ["#6E2A2A", "#1F4D3A", "#223A5E", "#8A6D1F", "#4A4E69", "#5C3D6E", "#2E6B6B", "#A1512A", "#9A3B3B", "#2F5D8A"];

// timeline (ms)
const PATH_AT = 150;
const PATH_MS = 900;
const WALK_AT = PATH_AT + PATH_MS;
const WALK_MS = 1200;
const ARRIVE_AT = WALK_AT + WALK_MS;
const HL_MS = 300;

const SVC_ICON: Record<string, string> = { toilets: "🚻", lift: "🛗", stairs: "" };
const SVC_NAME: Record<string, Key> = { toilets: "wf.svc.toilets", lift: "wf.svc.lift", stairs: "wf.svc.stairs" };

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


/** Front view of the target shelf unit: three rows of spines, the target row glowing. */
function ShelfFace({ x, y, row, slot, label, seed }: { x: number; y: number; row: number; slot: number; label: string; seed: string }) {
  const fw = 172;
  const fh = 104;
  const rowH = 20;
  const inner = fw - 24;
  return (
    <g className="wf-face" transform={`translate(${x} ${y})`} style={{ "--wf-d": `${ARRIVE_AT + 120}ms` } as CSSProperties}>
      <rect width={fw} height={fh} rx="10" className="wf-face-card" />
      <text x="12" y="18" className="wf-face-label">{label}</text>
      {ROW_NAMES.map((_, r) => {
        const ry = 26 + r * (rowH + 4);
        const spines: JSX.Element[] = [];
        let pos = 0;
        let i = 0;
        while (pos < inner - 2) {
          const size = 3 + (hash(seed + r + "s" + i) % 3);
          spines.push(<rect key={i} x={12 + pos} y={ry + 3 + (hash(seed + r + "h" + i) % 4)} width={size} height={rowH - 4 - (hash(seed + r + "h" + i) % 4)} fill={SPINES[hash(seed + r + "c" + i) % SPINES.length]} opacity={0.8} />);
          pos += size + 1;
          i++;
        }
        return (
          <g key={r} className={`wf-face-row ${r === row ? "on" : ""}`}>
            <rect x="8" y={ry} width={fw - 16} height={rowH} rx="3" className="wf-face-shelf" />
            {spines}
          </g>
        );
      })}
      <g transform={`translate(${12 + slot * inner} ${26 + row * (rowH + 4)})`} className="wf-face-marker">
        <rect x="-4" y="-2" width="8" height={rowH + 4} rx="2" />
        <path d={`M -6 ${rowH + 7} L 0 ${rowH + 1} L 6 ${rowH + 7} Z`} />
      </g>
    </g>
  );
}

export default function WayfindMap({ target }: { target: Target }) {
  const lang = useLang();
  const parsed = useMemo(() => parseCallNumber(target.callNumber), [target.callNumber]);
  const seedKey = target.code || target.branch;
  const plan = useMemo(() => planFor(seedKey), [seedKey]);
  const spot = useMemo(() => locate(parsed, plan), [parsed, plan, lang]);
  const route = useMemo(() => routeFor(parsed, plan, spot), [parsed, plan, spot]);
  const steps = useMemo(() => stepsFor(parsed, target.callNumber, seedKey), [parsed, target.callNumber, seedKey, lang]);
  const [run, setRun] = useState(0);
  const replay = () => setRun((r) => r + 1);
  const runKey = `${run}-${target.callNumber}-${planSignature(plan)}`;
  const [tx, ty] = spot.stand.map((v) => Math.round(v));
  const nf = parsed.kind === "nonfiction";
  const marks = route.marks;
  const svcLabel = plan.services.map((s) => t(SVC_NAME[s])).join(" · ");
  const faceX = Math.min(W - 24 - 172, Math.max(24, (spot.bayLabelX ?? tx) - 86));

  return (
    <div className="wayfind wf2">
      <div className="wf-map-wrap">
      <svg className="map floorplan" viewBox={`0 0 ${W} ${H}`} role="img" aria-label={t("wf.svg", { call: target.callNumber, branch: target.branch, label: spot.label })}>
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
        <rect x={FIC_X - 12} y={FIC_ROWS[0] - 20} width={FIC_W + 60} height={FIC_ROWS[4] - FIC_ROWS[0] + 64} rx="12" className="carpet-fiction" />
        <rect x={440} y={204} width={316} height={192} rx="12" className="carpet-reading" />
        <rect x={KIDS.x} y={KIDS.y} width={KIDS.w} height={KIDS.h} rx="14" className="carpet-kids" />
        {/* aisles (wood) */}
        <rect x={MAIN_X - 22} y={NF_AISLE_Y - 14} width="44" height={H - NF_AISLE_Y - 20} rx="8" fill="url(#wood)" className="aisle" />
        <rect x={28} y={NF_AISLE_Y - 14} width={W - 56} height="28" rx="8" fill="url(#wood)" className="aisle" />
        {plan.doorX !== MAIN_X && <rect x={Math.min(plan.doorX, MAIN_X) - 22} y={506} width={Math.abs(plan.doorX - MAIN_X) + 44} height="28" rx="8" fill="url(#wood)" className="aisle" />}

        {/* walls + windows */}
        <rect x="12" y="12" width={W - 24} height={H - 24} rx="10" className="wall" />
        {plan.windows.map(([a, b]) => (
          <line key={a} x1={a} x2={b} y1="12" y2="12" className="window" />
        ))}
        <line x1={plan.flip ? W - 12 : 12} x2={plan.flip ? W - 12 : 12} y1="200" y2="400" className="window" />

        {/* non-fiction bays: three shelf units each */}
        {NF_LABELS.map((label, i) => {
          const active = nf && parsed.bayIndex === i;
          const bx = plan.bayX[i];
          return (
            <g key={label}>
              <Range x={bx} y={NF_Y} w={NF_W} h={NF_H} vertical seed={`nf${i}`} active={active} />
              {[1, 2].map((u) => (
                <line key={u} x1={bx - 1} x2={bx + NF_W + 1} y1={NF_Y + u * UNIT_H} y2={NF_Y + u * UNIT_H} className="wf-unit-split" />
              ))}
              <text x={bx + NF_W / 2} y={NF_Y - 8} textAnchor="middle" className={`bay-label ${active ? "on" : ""}`}>
                {i}00s
              </text>
            </g>
          );
        })}
        <text x={plan.servicesX + 80} y={NF_Y + 78} textAnchor="middle" className="wf-dewey-dir">
          {t(plan.flip ? "wf.dewey.rev" : "wf.dewey.fwd")}
        </text>

        {/* toilets, lift, stairs */}
        <g className="service">
          {plan.services.map((s, k) => {
            const sx = plan.servicesX + k * 56;
            return (
              <g key={s}>
                <rect x={sx} y={NF_Y} width="48" height="40" rx="6" />
                {s === "stairs" ? (
                  [0, 1, 2, 3, 4].map((j) => <line key={j} x1={sx + 6} x2={sx + 42} y1={NF_Y + 8 + j * 6} y2={NF_Y + 8 + j * 6} className="stair" />)
                ) : (
                  <text x={sx + 24} y={NF_Y + 26} textAnchor="middle" className="svc-label">{SVC_ICON[s]}</text>
                )}
              </g>
            );
          })}
          <text x={plan.servicesX + 80} y={NF_Y + 58} textAnchor="middle" className="svc-caption">{svcLabel}</text>
        </g>

        {/* fiction stacks */}
        <g className={`zone ${parsed.kind === "fiction" ? "active" : ""}`}>
          {FIC_ROWS.map((y, r) => (
            <g key={y}>
              <Range x={FIC_X} y={y} w={FIC_W} h={18} vertical={false} seed={`fic${r}`} active={parsed.kind === "fiction" && parsed.row === r} />
              <text x={FIC_X + FIC_W + 8} y={y + 13} className="row-label">{FIC_SECTIONS[r]}</text>
            </g>
          ))}
          <text x={FIC_X} y={FIC_ROWS[0] - 26} className="zone-title">{t("wf.fiction")}</text>
          <Armchair x={FIC_X + 200} y={FIC_ROWS[4] + 26} />
          <Armchair x={FIC_X + 228} y={FIC_ROWS[4] + 26} />
        </g>

        {/* reading lounge + study (right) */}
        <g className="zone">
          <RoundTable x={490} y={246} />
          <RoundTable x={560} y={246} />
          <RoundTable x={630} y={246} />
          <Armchair x={690} y={224} />
          <Armchair x={716} y={224} />
          <Armchair x={690} y={254} />
          <Armchair x={716} y={254} />
          <text x={456} y={220} className="zone-title">{t("wf.lounge")}</text>
          <LongTable x={470} y={318} w={270} />
          <LongTable x={470} y={360} w={270} />
          <text x={456} y={303} className="zone-title">{t("wf.study")}</text>
        </g>

        {/* children's corner */}
        <g className={`zone ${parsed.kind === "children" ? "active" : ""}`}>
          <circle cx={KIDS.x + 110} cy={KIDS.y + 60} r="42" fill="url(#rug)" className="rug" />
          {[0, 1, 2].map((k) => (
            <Range key={k} x={KIDS.x + 180} y={KIDS.y + 16 + k * 28} w={100} h={14} vertical={false} seed={`k${k + 1}`} active={parsed.kind === "children"} />
          ))}
          <circle cx={KIDS.x + 36} cy={KIDS.y + 90} r="10" className="beanbag" />
          <circle cx={KIDS.x + 62} cy={KIDS.y + 98} r="10" className="beanbag" />
          <text x={KIDS.x + 14} y={KIDS.y + 24} className="zone-title">{t("wf.kids")}</text>
        </g>

        {/* counter, self-checkout, new arrivals (near entrance) */}
        <g className="service">
          <path d="M 150 460 Q 150 434 176 434 L 330 434 Q 356 434 356 460 L 356 478 L 150 478 Z" className="counter" />
          <text x="253" y="462" textAnchor="middle" className="counter-label">{t("wf.info")}</text>
          {[0, 1, 2].map((i) => (
            <g key={i}>
              <rect x={440 + i * 36} y="448" width="24" height="24" rx="5" className="kiosk" />
              <rect x={446 + i * 36} y="453" width="12" height="9" rx="1" className="screen" />
            </g>
          ))}
          <text x="490" y="490" textAnchor="middle" className="svc-caption">{t("wf.selfco")}</text>
          <rect x="44" y="438" width="84" height="40" rx="6" className="display" />
          <text x="86" y="462" textAnchor="middle" className="svc-caption">{t("wf.new")}</text>
        </g>

        {/* entrance: security gates + sliding doors */}
        <g className="service">
          <rect x={plan.doorX - 34} y="508" width="8" height="20" rx="2" className="gate" />
          <rect x={plan.doorX + 26} y="508" width="8" height="20" rx="2" className="gate" />
          <rect x={plan.doorX - 40} y={H - 16} width="36" height="8" rx="2" className="door" />
          <rect x={plan.doorX + 4} y={H - 16} width="36" height="8" rx="2" className="door" />
          <text x={plan.doorX + (plan.doorX > MAIN_X ? -54 : 54)} y={H - 24} textAnchor={plan.doorX > MAIN_X ? "end" : "start"} className="zone-title">{t("wf.entrance")}</text>
        </g>

        {plan.plants.map(([px, py]) => (
          <Plant key={`${px}-${py}`} x={px} y={py} />
        ))}

        {/* the run: remounted on Replay / new target so every animation restarts */}
        <g key={runKey} className="wf-run">
          {spot.unitRect && (
            <g className="wf-target" style={{ "--wf-d": `${ARRIVE_AT}ms`, "--wf-hl": `${HL_MS}ms` } as CSSProperties}>
              <rect x={spot.unitRect.x - 3} y={spot.unitRect.y - 3} width={spot.unitRect.w + 6} height={spot.unitRect.h + 6} rx="5" className="wf-unit" />
            </g>
          )}
          <path d={route.d} className="map-path-shadow wf-shadow" style={{ "--wf-d": `${PATH_AT}ms` } as CSSProperties} />
          <path d={route.d} pathLength={1} className="wf-path" style={{ "--wf-d": `${PATH_AT}ms`, "--wf-ms": `${PATH_MS}ms` } as CSSProperties} />
          <g className="wf-here" transform={`translate(${plan.doorX} ${DOOR_Y})`}>
            <circle r="16" className="wf-here-pulse" />
            <circle r="7" className="wf-here-dot" />
            <g transform={`translate(${plan.doorX > MAIN_X ? 22 : -22} -16)`}>
              <rect x={plan.doorX > MAIN_X ? 0 : -86} y="-12" width="86" height="22" rx="11" className="wf-here-tag" />
              <text x={plan.doorX > MAIN_X ? 43 : -43} y="4" textAnchor="middle" className="wf-here-text">{t("wf.here")}</text>
            </g>
          </g>
          <g className="wf-walker" style={{ offsetPath: `path("${route.d}")`, "--wf-d": `${WALK_AT}ms`, "--wf-ms": `${WALK_MS}ms` } as CSSProperties}>
            <circle r="9" className="wf-walker-halo" />
            <circle r="5.5" className="wf-walker-dot" />
          </g>
          <g className="map-pin wf-pin" transform={`translate(${tx} ${ty})`} style={{ "--wf-d": `${ARRIVE_AT}ms` } as CSSProperties}>
            <circle r="13" className="pin-ring wf-pin-ring" />
            <circle r="5.5" className="pin-dot" />
          </g>
          {nf && spot.unitRect && (
            <>
              <line x1={spot.bayLabelX} y1={spot.unitRect.y + spot.unitRect.h} x2={faceX + 86} y2={NF_AISLE_Y + 24} className="wf-face-link" style={{ "--wf-d": `${ARRIVE_AT + 80}ms` } as CSSProperties} />
              <ShelfFace x={faceX} y={NF_AISLE_Y + 24} row={parsed.shelfRow ?? 1} slot={parsed.slot ?? 0.5} label={spot.label} seed={`face${parsed.dewey}`} />
            </>
          )}
          {!nf && spot.unitRect && (
            <g className="wf-face wf-chip" transform={`translate(${Math.min(W - 180, Math.max(20, tx - 80))} ${Math.max(20, ty - 52)})`} style={{ "--wf-d": `${ARRIVE_AT + 120}ms` } as CSSProperties}>
              <rect width="160" height="26" rx="13" className="wf-face-card" />
              <text x="80" y="17" textAnchor="middle" className="wf-face-label">{spot.label}</text>
            </g>
          )}
        </g>
        {nf && (
          <g className="flag" transform={`translate(${Math.min(W - 160, Math.max(20, (spot.bayLabelX ?? tx) - 70))} 16)`}>
            <rect width="140" height="24" rx="12" />
            <text x="70" y="16" textAnchor="middle">📍 {target.callNumber.replace(/^English\s+/i, "")}</text>
          </g>
        )}
      </svg>
      <button type="button" className="wf-replay" onClick={replay} aria-label={t("wf.replayAria")}>
        <span aria-hidden="true">↻</span> {t("wf.replay")}
      </button>
      </div>

      <ol className="steps wf-steps" key={`steps-${runKey}`}>
        {steps.map((s, i) => {
          const from = WALK_AT + (marks[i] ?? 1) * WALK_MS;
          const to = i + 1 < steps.length ? WALK_AT + (marks[i + 1] ?? 1) * WALK_MS : from + 400;
          const last = i === steps.length - 1;
          return (
            <li key={i} className={last ? "wf-last" : ""} style={{ "--wf-d": `${i === 0 ? WALK_AT - 200 : Math.round(from)}ms`, "--wf-ms": `${Math.max(300, Math.round(to - from))}ms`, animationDelay: `${120 + i * 80}ms` } as CSSProperties}>
              <button type="button" className="wf-step" onClick={replay} title={t("wf.replayAria")}>
                <span className="step-icon" aria-hidden="true">{s.icon}</span>
                <span>{s.text}</span>
              </button>
            </li>
          );
        })}
      </ol>
      <p className="hint map-note">
        {t("wf.note", { place: target.branch ? target.branch.replace(/\s+(public|regional)?\s*library$/i, "") : t("wf.thisLibrary") })}
      </p>
    </div>
  );
}
