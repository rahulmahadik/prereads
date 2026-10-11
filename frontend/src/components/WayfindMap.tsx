/**
 * Floor-plan directions inside a library.
 *
 * Drawn as a top-down plan: walls and windows, entrance gates, information counter,
 * self-checkout, double-sided shelf ranges with book spines (non-fiction in Dewey order,
 * three shelf units per bay; fiction A–Z), reading lounge, study tables, children's
 * corner, lift, stairs, toilets. The plan is seeded by the branch (wayfind.ts), so each
 * library looks different but always the same. Schematic, not to scale.
 *
 * Motion loops (timeline in wayfind.ts LOOP/frameAt, driven by requestAnimationFrame):
 * "You are here" pulses, the route draws, a walker follows it, the shelf unit, row and label
 * light up, it holds ~1.5 s, the trail fades and it runs again. Steps light in sync; tapping a
 * step puts the walker there. The loop pauses off-screen and in a hidden tab; with reduced
 * motion the finished route is shown still. "Full screen" opens the same map over the page.
 */
import { useEffect, useId, useLayoutEffect, useMemo, useRef, useState, type CSSProperties, type ReactNode, type RefObject } from "react";
import { createPortal } from "react-dom";
import {
  FIC_ROWS, FIC_SECTIONS, FIC_W, FIC_X, H, KIDS, MAIN_X, NF_AISLE_Y, NF_H, NF_LABELS, NF_W, NF_Y, ROW_NAMES, UNIT_H, W, DOOR_Y,
  LOOP, STILL_MS, frameAt, hash, locate, parseCallNumber, planFor, planSignature, pointAlong, routeFor, stepsFor, timeForStep,
  type Parsed, type Plan, type Route, type Spot, type Step,
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
function ShelfFace({ x, y, row, slot, label, seed, gRef }: { x: number; y: number; row: number; slot: number; label: string; seed: string; gRef: RefObject<SVGGElement> }) {
  const fw = 172;
  const fh = 104;
  const rowH = 20;
  const inner = fw - 24;
  return (
    <g className="wf-face" ref={gRef} transform={`translate(${x} ${y})`}>
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

// --- loop helpers ----------------------------------------------------------------
function useMedia(query: string): boolean {
  const [on, setOn] = useState(() => typeof window !== "undefined" && !!window.matchMedia?.(query).matches);
  useEffect(() => {
    const mq = window.matchMedia?.(query);
    if (!mq) return;
    const f = () => setOn(mq.matches);
    f();
    mq.addEventListener?.("change", f);
    return () => mq.removeEventListener?.("change", f);
  }, [query]);
  return on;
}

function usePageVisible(): boolean {
  const [on, setOn] = useState(() => typeof document === "undefined" || document.visibilityState !== "hidden");
  useEffect(() => {
    const f = () => setOn(document.visibilityState !== "hidden");
    document.addEventListener("visibilitychange", f);
    return () => document.removeEventListener("visibilitychange", f);
  }, []);
  return on;
}

function useOnScreen(ref: RefObject<Element>): boolean {
  const [on, setOn] = useState(true);
  useEffect(() => {
    const el = ref.current;
    if (!el || typeof IntersectionObserver === "undefined") return;
    const io = new IntersectionObserver((entries) => setOn(entries.some((e) => e.isIntersecting)));
    io.observe(el);
    return () => io.disconnect();
  }, [ref]);
  return on;
}

interface ViewProps {
  target: Target;
  parsed: Parsed;
  plan: Plan;
  spot: Spot;
  route: Route;
  steps: Step[];
  /** false pauses the loop (e.g. the inline map while full screen covers it) */
  live: boolean;
  children?: ReactNode;
}

/** The floor plan and its written steps, with the looping route animation. */
function MapView({ target, parsed, plan, spot, route, steps, live, children }: ViewProps) {
  const uid = "wf" + useId().replace(/[^a-zA-Z0-9_-]/g, "");
  const rootRef = useRef<HTMLDivElement>(null);
  const runRef = useRef<SVGGElement>(null);
  const pulseRef = useRef<SVGCircleElement>(null);
  const shadowRef = useRef<SVGPathElement>(null);
  const pathRef = useRef<SVGPathElement>(null);
  const walkerRef = useRef<SVGGElement>(null);
  const unitRef = useRef<SVGGElement>(null);
  const pinRef = useRef<SVGGElement>(null);
  const linkRef = useRef<SVGLineElement>(null);
  const faceRef = useRef<SVGGElement>(null);
  const stepsRef = useRef<HTMLOListElement>(null);
  const timeRef = useRef(0);
  const shown = useRef<{ step: number; arrived: boolean | null }>({ step: -2, arrived: null });

  const reduced = useMedia("(prefers-reduced-motion: reduce)");
  const pageVisible = usePageVisible();
  const onScreen = useOnScreen(rootRef);
  const running = live && pageVisible && onScreen && !reduced;

  const [tx, ty] = spot.stand.map((v) => Math.round(v));
  const nf = parsed.kind === "nonfiction";
  const svcLabel = plan.services.map((s) => t(SVC_NAME[s])).join(" · ");
  const faceX = Math.min(W - 24 - 172, Math.max(24, (spot.bayLabelX ?? tx) - 86));
  const loopKey = `${target.callNumber}-${planSignature(plan)}`;

  /** Draw the loop at `ms`: only styles and attributes change, React never re-renders per frame. */
  const draw = (ms: number) => {
    const f = frameAt(ms, route.marks);
    const fade = (el: Element | null, v: number) => el && ((el as SVGElement).style.opacity = String(+v.toFixed(3)));
    const pulse = pulseRef.current;
    if (pulse) {
      pulse.style.opacity = f.pulse < 0 ? "0" : String(+(0.45 * (1 - f.pulse)).toFixed(3));
      pulse.style.transform = `scale(${(0.5 + 1.5 * (1 - (1 - Math.max(0, f.pulse)) ** 2)).toFixed(3)})`;
    }
    if (pathRef.current) pathRef.current.style.strokeDashoffset = String(+(1 - f.draw).toFixed(4));
    fade(pathRef.current, f.trail);
    fade(shadowRef.current, f.shadow * f.trail);
    if (walkerRef.current) {
      const [x, y] = pointAlong(route.points, f.walk);
      walkerRef.current.setAttribute("transform", `translate(${x.toFixed(1)} ${y.toFixed(1)})`);
      fade(walkerRef.current, f.walker * f.trail);
    }
    fade(unitRef.current, f.unit * f.trail);
    fade(pinRef.current, f.pin * f.trail);
    fade(linkRef.current, f.link * f.trail);
    if (faceRef.current) {
      fade(faceRef.current, f.face * f.trail);
      faceRef.current.style.setProperty("scale", f.faceScale.toFixed(3));
    }
    if (f.arrived !== shown.current.arrived) {
      shown.current.arrived = f.arrived;
      runRef.current?.classList.toggle("arrived", f.arrived);
    }
    if (f.step !== shown.current.step) {
      shown.current.step = f.step;
      stepsRef.current?.querySelectorAll(".wf-step").forEach((b, i) => b.classList.toggle("on", i === f.step));
    }
  };
  const drawRef = useRef(draw);
  drawRef.current = draw;

  // a new book or branch starts the loop from the beginning
  useLayoutEffect(() => {
    timeRef.current = reduced ? STILL_MS : 0;
    shown.current = { step: -2, arrived: null };
  }, [loopKey, reduced]);

  useLayoutEffect(() => {
    drawRef.current(timeRef.current);
    if (!running) return;
    let raf = 0;
    let last = -1;
    const tick = (now: number) => {
      if (last >= 0) timeRef.current = (timeRef.current + Math.min(64, now - last)) % LOOP.cycle;
      last = now;
      drawRef.current(timeRef.current);
      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [running, loopKey]);

  const jump = (i: number) => {
    timeRef.current = timeForStep(route.marks, i);
    drawRef.current(timeRef.current);
  };

  return (
    <div className={`wayfind wf2 wf-loop ${running ? "" : "paused"}`} ref={rootRef}>
      <div className="wf-map-wrap">
      <svg className="map floorplan" viewBox={`0 0 ${W} ${H}`} role="img" aria-label={t("wf.svg", { call: target.callNumber, branch: target.branch, label: spot.label })}>
        <defs>
          <pattern id={`${uid}carpet`} width="8" height="8" patternUnits="userSpaceOnUse">
            <rect width="8" height="8" fill="#eef1f5" />
            <circle cx="4" cy="4" r="0.8" fill="#dfe4ea" />
          </pattern>
          <pattern id={`${uid}rug`} width="14" height="14" patternUnits="userSpaceOnUse">
            <rect width="14" height="14" fill="#ffe9cf" />
            <circle cx="7" cy="7" r="3" fill="#ffd5a6" />
          </pattern>
          <pattern id={`${uid}wood`} width="60" height="6" patternUnits="userSpaceOnUse">
            <rect width="60" height="6" fill="#efe6d8" />
            <line x1="0" x2="60" y1="5.5" y2="5.5" stroke="#e3d6c2" strokeWidth="1" />
          </pattern>
        </defs>

        {/* floor */}
        <rect x="12" y="12" width={W - 24} height={H - 24} rx="10" fill={`url(#${uid}carpet)`} />
        <rect x={FIC_X - 12} y={FIC_ROWS[0] - 20} width={FIC_W + 60} height={FIC_ROWS[4] - FIC_ROWS[0] + 64} rx="12" className="carpet-fiction" />
        <rect x={440} y={204} width={316} height={192} rx="12" className="carpet-reading" />
        <rect x={KIDS.x} y={KIDS.y} width={KIDS.w} height={KIDS.h} rx="14" className="carpet-kids" />
        {/* aisles (wood) */}
        <rect x={MAIN_X - 22} y={NF_AISLE_Y - 14} width="44" height={H - NF_AISLE_Y - 20} rx="8" fill={`url(#${uid}wood)`} className="aisle" />
        <rect x={28} y={NF_AISLE_Y - 14} width={W - 56} height="28" rx="8" fill={`url(#${uid}wood)`} className="aisle" />
        {plan.doorX !== MAIN_X && <rect x={Math.min(plan.doorX, MAIN_X) - 22} y={506} width={Math.abs(plan.doorX - MAIN_X) + 44} height="28" rx="8" fill={`url(#${uid}wood)`} className="aisle" />}

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
          <circle cx={KIDS.x + 110} cy={KIDS.y + 60} r="42" fill={`url(#${uid}rug)`} className="rug" />
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

        {/* the run: drawn frame by frame by draw(); starts hidden */}
        <g className="wf-run" ref={runRef} data-loop={loopKey}>
          {spot.unitRect && (
            <g className="wf-target" ref={unitRef} style={{ opacity: 0 }}>
              <rect x={spot.unitRect.x - 3} y={spot.unitRect.y - 3} width={spot.unitRect.w + 6} height={spot.unitRect.h + 6} rx="5" className="wf-unit" />
            </g>
          )}
          <path d={route.d} ref={shadowRef} className="map-path-shadow wf-shadow" style={{ opacity: 0 }} />
          <path d={route.d} ref={pathRef} pathLength={1} className="wf-path" style={{ strokeDashoffset: 1 }} />
          <g className="wf-here" transform={`translate(${plan.doorX} ${DOOR_Y})`}>
            <circle r="16" ref={pulseRef} className="wf-here-pulse" />
            <circle r="7" className="wf-here-dot" />
            <g transform={`translate(${plan.doorX > MAIN_X ? 22 : -22} -16)`}>
              <rect x={plan.doorX > MAIN_X ? 0 : -86} y="-12" width="86" height="22" rx="11" className="wf-here-tag" />
              <text x={plan.doorX > MAIN_X ? 43 : -43} y="4" textAnchor="middle" className="wf-here-text">{t("wf.here")}</text>
            </g>
          </g>
          <g className="wf-walker" ref={walkerRef} style={{ opacity: 0 }}>
            <circle r="9" className="wf-walker-halo" />
            <circle r="5.5" className="wf-walker-dot" />
          </g>
          <g className="map-pin wf-pin" ref={pinRef} transform={`translate(${tx} ${ty})`} style={{ opacity: 0 }}>
            <circle r="13" className="pin-ring wf-pin-ring" />
            <circle r="5.5" className="pin-dot" />
          </g>
          {nf && spot.unitRect && (
            <>
              <line ref={linkRef} x1={spot.bayLabelX} y1={spot.unitRect.y + spot.unitRect.h} x2={faceX + 86} y2={NF_AISLE_Y + 24} className="wf-face-link" style={{ opacity: 0 }} />
              <ShelfFace gRef={faceRef} x={faceX} y={NF_AISLE_Y + 24} row={parsed.shelfRow ?? 1} slot={parsed.slot ?? 0.5} label={spot.label} seed={`face${parsed.dewey}`} />
            </>
          )}
          {!nf && spot.unitRect && (
            <g className="wf-face wf-chip" ref={faceRef} transform={`translate(${Math.min(W - 180, Math.max(20, tx - 80))} ${Math.max(20, ty - 52)})`}>
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
      {children}
      </div>

      <ol className="steps wf-steps" ref={stepsRef}>
        {steps.map((s, i) => (
          <li key={i} className={i === steps.length - 1 ? "wf-last" : ""} style={{ animationDelay: `${120 + i * 80}ms` }}>
            <button type="button" className="wf-step" onClick={() => jump(i)} title={t("wf.showStep")}>
              <span className="step-icon" aria-hidden="true">{s.icon}</span>
              <span>{s.text}</span>
            </button>
          </li>
        ))}
      </ol>
      <p className="hint map-note">
        {t("wf.noteLoop", { place: placeName(target.branch) })}
      </p>
    </div>
  );
}

const placeName = (branch: string) => (branch ? branch.replace(/\s+(public|regional)?\s*library$/i, "") : t("wf.thisLibrary"));

export default function WayfindMap({ target }: { target: Target }) {
  const lang = useLang();
  const parsed = useMemo(() => parseCallNumber(target.callNumber), [target.callNumber]);
  const seedKey = target.code || target.branch;
  const plan = useMemo(() => planFor(seedKey), [seedKey]);
  const spot = useMemo(() => locate(parsed, plan), [parsed, plan, lang]);
  const route = useMemo(() => routeFor(parsed, plan, spot), [parsed, plan, spot]);
  const steps = useMemo(() => stepsFor(parsed, target.callNumber, seedKey), [parsed, target.callNumber, seedKey, lang]);
  const view = { target, parsed, plan, spot, route, steps };

  const [full, setFull] = useState(false);
  const openRef = useRef<HTMLButtonElement>(null);
  const closeRef = useRef<HTMLButtonElement>(null);
  const dialogRef = useRef<HTMLDivElement>(null);
  const titleId = useId();

  // full screen: lock page scroll, focus the close button, Escape closes, Tab stays inside
  useEffect(() => {
    if (!full) return;
    const body = document.body;
    const prev = body.style.overflow;
    body.style.overflow = "hidden";
    closeRef.current?.focus({ preventScroll: true });
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        e.preventDefault();
        setFull(false);
      } else if (e.key === "Tab" && dialogRef.current) {
        const items = Array.from(dialogRef.current.querySelectorAll<HTMLElement>("button, [href], [tabindex]:not([tabindex='-1'])"));
        if (!items.length) return;
        const first = items[0];
        const last = items[items.length - 1];
        if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
        else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
        else if (!dialogRef.current.contains(document.activeElement)) { e.preventDefault(); first.focus(); }
      }
    };
    document.addEventListener("keydown", onKey);
    return () => {
      body.style.overflow = prev;
      document.removeEventListener("keydown", onKey);
      openRef.current?.focus({ preventScroll: true });
    };
  }, [full]);

  return (
    <>
      <MapView {...view} live={!full}>
        <button type="button" ref={openRef} className="wf-fs-btn" aria-pressed={full} onClick={() => setFull(true)}>
          <span aria-hidden="true">⛶</span> {t("wf.fullscreen")}
        </button>
      </MapView>
      {full && typeof document !== "undefined" &&
        createPortal(
          <div className="wf-fs" role="dialog" aria-modal="true" aria-labelledby={titleId} ref={dialogRef}>
            <div className="wf-fs-bar">
              <h2 className="wf-fs-title" id={titleId}>
                {t("book.findAt", { branch: placeName(target.branch) })} <span className="hint">· {target.callNumber}</span>
              </h2>
              <button type="button" ref={closeRef} className="wf-fs-close" onClick={() => setFull(false)} aria-label={t("wf.exitFullscreen")} title={t("wf.exitFullscreen")}>
                <span aria-hidden="true">✕</span>
              </button>
            </div>
            <MapView {...view} live />
          </div>,
          document.body,
        )}
    </>
  );
}
