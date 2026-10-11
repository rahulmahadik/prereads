/**
 * Wayfinding logic (pure, no React): call number -> bay / shelf unit / row / position,
 * and a per-branch schematic floor plan (seeded by the branch, so each library looks
 * different but always the same). WayfindMap.tsx only draws what this returns.
 */
import { t, type Key } from "./i18n";

export const W = 800;
export const H = 560;
export const MAIN_X = 390;          // centre aisle
export const NF_Y = 58;             // non-fiction ranges top
export const NF_H = 96;             // three shelf units of 32
export const NF_W = 34;
export const NF_STEP = 54;
export const NF_AISLE_Y = 172;      // cross aisle under the ranges
export const UNITS = 3;
export const UNIT_H = NF_H / UNITS;
export const DOOR_Y = H - 18;
export const FIC_ROWS = [222, 264, 306, 348, 390];
export const FIC_X = 44;
export const FIC_W = 260;
export const KIDS = { x: 450, y: 406, w: 300, h: 112 };

export const NF_LABELS = [
  "General & computing", "Philosophy & psychology", "Religion", "Social sciences", "Language",
  "Science & maths", "Technology & health", "Arts & recreation", "Literature", "History & geography",
];
export const FIC_SECTIONS = ["A–E", "F–J", "K–O", "P–T", "U–Z"];
export const ROW_NAMES = ["top", "middle", "bottom"] as const;

export type Kind = "nonfiction" | "fiction" | "children" | "unknown";

export interface Parsed {
  kind: Kind;
  dewey?: string;          // "332.63"
  author?: string;         // cutter, e.g. "MAL"
  bayIndex?: number;       // 0-9 (Dewey hundreds)
  unit?: number;           // 0-2 shelf unit inside the bay (tens + units)
  shelfRow?: number;       // 0 top, 1 middle, 2 bottom (decimal + cutter)
  slot?: number;           // 0-1 left-to-right position on that row
  row?: number;            // fiction section 0-4 (A–E ... U–Z)
  zoneLabel: string;
}

export function hash(s: string): number {
  let h = 2166136261;
  for (let i = 0; i < s.length; i++) h = Math.imul(h ^ s.charCodeAt(i), 16777619);
  return h >>> 0;
}

/** Small seeded PRNG (mulberry32). */
function rng(seed: number): () => number {
  let a = seed >>> 0;
  return () => {
    a = (a + 0x6d2b79f5) >>> 0;
    let t = a;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

const LANG = /^(english|chinese|malay|tamil|eng|chi|mal|tam)\b\s*/i;
const plain = (s: string) => s.normalize("NFD").replace(/[̀-ͯ]/g, "");

/** Author cutter -> 0..1 in A..Z order (first three letters). */
export function cutterFraction(author?: string): number {
  if (!author) return 0.5;
  const a = plain(author).toUpperCase().replace(/[^A-Z]/g, "");
  let f = 0;
  let scale = 1;
  for (let i = 0; i < Math.min(3, a.length); i++) {
    scale /= 26;
    f += (a.charCodeAt(i) - 65) * scale;
  }
  return Math.min(0.999, Math.max(0, f));
}

export function fictionSection(author?: string): number {
  const a = plain(author || "M").toUpperCase().replace(/[^A-Z]/g, "") || "M";
  return Math.min(4, Math.floor((a.charCodeAt(0) - 65) / 5));
}

export function parseCallNumber(callNumber: string): Parsed {
  const cn = plain(callNumber.trim()).replace(LANG, "");
  const upper = cn.toUpperCase();
  const tokens = upper.split(/\s+/).filter(Boolean);
  const dewey = cn.match(/(\d{3})(\.(\d+))?/);
  const last = tokens[tokens.length - 1] || "";
  const author = /^[A-Z]{1,4}$/.test(last) && !/^(FIC|J|JP|JS|JE|YA)$/.test(last) ? last : undefined;
  if (/^(J|JS|JP|JE|JR)$/.test(tokens[0] || "") || /CHILD/.test(upper)) {
    return { kind: "children", author, dewey: dewey?.[0], zoneLabel: "Children's corner" };
  }
  if (/\bFIC\b|FICTION/.test(upper) || !dewey) {
    if (!dewey && !author && !/\bFIC\b|FICTION/.test(upper)) return { kind: "unknown", zoneLabel: "Ask at the counter" };
    const row = fictionSection(author);
    return { kind: "fiction", author, row, zoneLabel: `Fiction ${FIC_SECTIONS[row]}` };
  }
  const whole = parseInt(dewey[1], 10);
  const bayIndex = Math.min(9, Math.floor(whole / 100));
  const n = whole % 100;                                     // tens + units
  const unit = Math.min(UNITS - 1, Math.floor((n * UNITS) / 100));
  const start = Math.ceil((unit * 100) / UNITS);
  const span = Math.ceil(((unit + 1) * 100) / UNITS) - start;
  const seg = Math.min(1, Math.max(0, (n - start + 0.5) / span));
  const dec = dewey[3] ? parseFloat(`0.${dewey[3]}`) : 0;
  // Order along the unit, row-major (top row left to right, then middle, then bottom).
  // The class number sets the rough place; the decimal and the author cutter spread books
  // that share it, as they would on a real shelf (332.6 DOM ... 332.6 MAL sit side by side).
  const s = Math.min(0.999, Math.max(0, 0.7 * seg + 0.3 * (0.6 * dec + 0.4 * cutterFraction(author))));
  const shelfRow = Math.min(2, Math.floor(s * 3));
  const slot = Math.min(0.97, Math.max(0.03, s * 3 - shelfRow));
  return { kind: "nonfiction", dewey: dewey[0], author, bayIndex, unit, shelfRow, slot, zoneLabel: `${bayIndex}00s · ${NF_LABELS[bayIndex]}` };
}

// --- per-branch plan ------------------------------------------------------------
export type Service = "toilets" | "lift" | "stairs";

export interface Plan {
  key: string;
  flip: boolean;            // Dewey runs right -> left, services on the left wall
  doorX: number;            // where the entrance doors are on the bottom wall
  services: Service[];      // left-to-right order of toilets / lift / stairs
  servicesX: number;
  bayX: number[];           // x of each Dewey bay 0..9
  windows: [number, number][];
  plants: [number, number][];
}

export function branchKey(branch: string): string {
  return plain(branch || "").toLowerCase().replace(/\b(public|regional|library|libraries)\b/g, "").replace(/[^a-z0-9]+/g, " ").trim();
}

const PERMS: Service[][] = [
  ["toilets", "lift", "stairs"], ["lift", "toilets", "stairs"], ["stairs", "lift", "toilets"],
  ["toilets", "stairs", "lift"], ["lift", "stairs", "toilets"], ["stairs", "toilets", "lift"],
];

export function planFor(branch: string): Plan {
  const key = branchKey(branch);
  const r = rng(hash(key || "default"));
  const flip = key ? r() < 0.5 : false;
  const doorX = key ? [MAIN_X - 96, MAIN_X, MAIN_X + 96][Math.floor(r() * 3)] : MAIN_X;
  const services = key ? PERMS[Math.floor(r() * PERMS.length)] : PERMS[0];
  const shift = key ? Math.round(r() * 28) : 0;   // the bank sits a little differently in each branch
  const bank = 9 * NF_STEP + NF_W;           // 520
  const x0 = flip ? W - 28 - 16 - bank - shift : 44 + shift;
  const servicesX = flip ? 32 : W - 32 - 166;
  const bayX = Array.from({ length: 10 }, (_, i) => x0 + (flip ? 9 - i : i) * NF_STEP);
  const w0 = 40 + Math.floor(r() * 60);
  const windows: [number, number][] = [[w0, w0 + 180 + Math.floor(r() * 60)], [380 + Math.floor(r() * 40), 540 + Math.floor(r() * 30)], [600 + Math.floor(r() * 20), 740]];
  const plants: [number, number][] = [[30, 30], [770, 530], [flip ? 380 : 420, 190]];
  return { key, flip, doorX, services, servicesX, bayX, windows, plants };
}

/** Compact signature of a plan, for tests and React keys. */
export const planSignature = (p: Plan) => `${p.flip ? "R" : "L"}${p.doorX}${p.services.map((s) => s[0]).join("")}@${p.bayX[0]}`;

// --- where you stand ------------------------------------------------------------
export interface Spot {
  stand: [number, number];                         // where the walker stops
  unitRect?: { x: number; y: number; w: number; h: number };
  bayLabelX?: number;
  label: string;                                   // "Shelf 2 · middle row"
  rowName?: string;
}

export function locate(p: Parsed, plan: Plan): Spot {
  if (p.kind === "nonfiction" && p.bayIndex !== undefined) {
    const bx = plan.bayX[p.bayIndex];
    const u = p.unit ?? 0;
    const y = NF_Y + NF_H - (u + 1) * UNIT_H;      // shelf 1 is at the aisle end
    // stand in the gap on the side facing the entrance aisle
    const side = bx + NF_W / 2 < MAIN_X ? 1 : -1;
    const gx = side > 0 ? bx + NF_W + 10 : bx - 10;
    const sy = y + 4 + (p.slot ?? 0.5) * (UNIT_H - 8);
    const rowName = ROW_NAMES[p.shelfRow ?? 1];
    return { stand: [gx, sy], unitRect: { x: bx, y, w: NF_W, h: UNIT_H }, bayLabelX: bx + NF_W / 2, rowName, label: t("wf.label.shelf", { n: u + 1, row: t(`wf.rowL.${rowName}` as Key) }) };
  }
  if (p.kind === "fiction") {
    const row = p.row ?? 2;
    const within = (cutterFraction(p.author) * 26 - row * 5) / (row === 4 ? 6 : 5);
    const x = FIC_X + 12 + within * (FIC_W - 24);
    return { stand: [Math.min(FIC_X + FIC_W - 8, Math.max(FIC_X + 8, x)), FIC_ROWS[row] + 28], unitRect: { x: FIC_X, y: FIC_ROWS[row], w: FIC_W, h: 18 }, label: t("wf.label.fiction", { section: FIC_SECTIONS[row] }) };
  }
  if (p.kind === "children") {
    const row = Math.min(2, Math.floor(cutterFraction(p.author) * 3));
    return { stand: [KIDS.x + 170, KIDS.y + 23 + row * 28], unitRect: { x: KIDS.x + 180, y: KIDS.y + 16 + row * 28, w: 100, h: 14 }, label: t("wf.label.kids", { n: row + 1 }) };
  }
  return { stand: [MAIN_X, 470], label: t("wf.label.info") };
}

export interface Route {
  d: string;
  points: [number, number][];
  length: number;
  /** fraction (0-1) of the walk at which each written step begins */
  marks: number[];
}

function lengthOf(pts: [number, number][]): number[] {
  const acc = [0];
  for (let i = 1; i < pts.length; i++) acc.push(acc[i - 1] + Math.hypot(pts[i][0] - pts[i - 1][0], pts[i][1] - pts[i - 1][1]));
  return acc;
}

export function routeFor(p: Parsed, plan: Plan, spot: Spot): Route {
  const [tx, ty] = spot.stand;
  const pts: [number, number][] = [[plan.doorX, DOOR_Y]];
  if (plan.doorX !== MAIN_X) pts.push([plan.doorX, 520], [MAIN_X, 520]);
  let turnAt = pts.length - 1;    // index where "turn" starts
  if (p.kind === "nonfiction") {
    pts.push([MAIN_X, NF_AISLE_Y]);
    turnAt = pts.length - 1;
    pts.push([tx, NF_AISLE_Y], [tx, ty]);
  } else if (p.kind === "fiction" || p.kind === "children") {
    pts.push([MAIN_X, ty]);
    turnAt = pts.length - 1;
    pts.push([tx, ty]);
  } else {
    pts.push([MAIN_X, ty]);
  }
  const clean = pts.filter((q, i) => i === 0 || q[0] !== pts[i - 1][0] || q[1] !== pts[i - 1][1]);
  const acc = lengthOf(pts);
  const total = acc[acc.length - 1] || 1;
  const marks =
    p.kind === "nonfiction" ? [0, acc[turnAt] / total, acc[turnAt + 1] / total, 1] :
    p.kind === "unknown" ? [0] : [0, acc[turnAt] / total, 1];
  const d = clean.map((q, i) => `${i ? "L" : "M"} ${Math.round(q[0])} ${Math.round(q[1])}`).join(" ");
  return { d, points: clean, length: Math.round(total), marks };
}

// --- written steps -----------------------------------------------------------------
export interface Step { icon: string; text: string }

/** Plain steps. Without a branch the directions stay neutral (no left/right), so the
 *  narration never contradicts a branch's mirrored plan. */
export function stepsFor(p: Parsed, callNumber: string, branch?: string): Step[] {
  const plan = branch ? planFor(branch) : null;
  const short = callNumber.replace(LANG, "").trim();
  const dirWord = (d: "left" | "right") => t(d === "left" ? "wf.dir.left" : "wf.dir.right");
  const enter =
    !plan || plan.doorX === MAIN_X ? t("wf.enter.straight") :
    t("wf.enter.turn", { dir: dirWord(plan.doorX < MAIN_X ? "right" : "left") });
  if (p.kind === "nonfiction" && p.bayIndex !== undefined) {
    const spot = plan ? locate(p, plan) : null;
    const dir = spot ? (spot.stand[0] < MAIN_X ? "left" : "right") : "";
    const rowName = ROW_NAMES[p.shelfRow ?? 1];
    const where = t((p.slot ?? 0.5) < 0.34 ? "wf.where.left" : (p.slot ?? 0.5) > 0.66 ? "wf.where.right" : "wf.where.mid");
    return [
      { icon: "🚪", text: enter },
      { icon: dir === "right" ? "↱" : "↰", text: dir ? t("wf.nf.turn", { dir: dirWord(dir) }) : t("wf.nf.follow") },
      { icon: "📚", text: t("wf.nf.bay", { n: p.bayIndex, range: NF_LABELS[p.bayIndex], shelf: (p.unit ?? 0) + 1 }) },
      { icon: "🔎", text: t("wf.nf.row", { row: t(`wf.rowU.${rowName}` as Key), where, call: short }) },
    ];
  }
  if (p.kind === "children") {
    return [
      { icon: "🚪", text: enter },
      { icon: "↱", text: t("wf.kids.turn") },
      { icon: "🔎", text: p.author ? t("wf.kids.author", { author: p.author }) : t("wf.look", { call: short }) },
    ];
  }
  if (p.kind === "fiction") {
    return [
      { icon: "🚪", text: enter },
      { icon: "↰", text: t("wf.fic.turn", { section: FIC_SECTIONS[p.row ?? 2] }) },
      { icon: "🔎", text: p.author ? t("wf.fic.author", { author: p.author }) : t("wf.look", { call: short }) },
    ];
  }
  return [{ icon: "🛎️", text: t("wf.ask") }];
}

// --- the route animation (one loop) ------------------------------------------------
/** Timeline of one loop, in ms: "You are here" pulses, the route draws, the walker follows it,
 *  the shelf unit, row and label light up, it holds ~1.5 s, the trail fades, and it starts again. */
export const LOOP = (() => {
  const pathAt = 150, pathMs = 900, walkMs = 1200, hlMs = 300, popMs = 300, holdMs = 1500, outMs = 500;
  const walkAt = pathAt + pathMs;                 // 1050
  const arriveAt = walkAt + walkMs;               // 2250
  const outAt = arriveAt + 120 + popMs + holdMs;  // the shelf card is in at +420, then hold
  return { pathAt, pathMs, walkAt, walkMs, arriveAt, hlMs, popMs, holdMs, outAt, outMs, cycle: outAt + outMs + 150 };
})();

/** A moment in the loop where everything is drawn and lit (reduced motion shows this, still). */
export const STILL_MS = LOOP.outAt - 1;

/** CSS-style cubic-bezier(x1, y1, x2, y2) timing function. */
function bezier(x1: number, y1: number, x2: number, y2: number): (x: number) => number {
  const at = (p1: number, p2: number, s: number) => 3 * p1 * s * (1 - s) ** 2 + 3 * p2 * s * s * (1 - s) + s ** 3;
  return (x) => {
    if (x <= 0) return 0;
    if (x >= 1) return 1;
    let lo = 0, hi = 1, s = x;
    for (let i = 0; i < 28; i++) {
      s = (lo + hi) / 2;
      if (at(x1, x2, s) < x) lo = s; else hi = s;
    }
    return at(y1, y2, s);
  };
}
const easeWalk = bezier(0.45, 0.05, 0.4, 1);
const easePage = bezier(0.22, 0.61, 0.36, 1);   // --ease-page
const easePop = bezier(0.34, 1.56, 0.64, 1);    // slight overshoot
const clamp01 = (v: number) => Math.min(1, Math.max(0, v));

export interface Frame {
  pulse: number;      // 0-1 phase of the "You are here" ripple, -1 when still
  draw: number;       // 0-1 of the route drawn
  shadow: number;     // 0-1 opacity of the route's soft shadow
  walker: number;     // 0 hidden, 1 shown
  walk: number;       // 0-1 distance along the route
  unit: number;       // 0-1 shelf-unit highlight
  pin: number;        // 0-1
  link: number;       // 0-1 dotted line to the shelf card
  face: number;       // 0-1 shelf card opacity
  faceScale: number;  // shelf card pop
  trail: number;      // 1 shown, fading to 0 at the end of the loop
  step: number;       // index of the lit written step, -1 for none
  arrived: boolean;
}

/** Where everything is at `ms` into the loop (wraps). `marks` are the route's step marks. */
export function frameAt(ms: number, marks: number[]): Frame {
  const L = LOOP;
  const t = ((ms % L.cycle) + L.cycle) % L.cycle;
  const walk = easeWalk(clamp01((t - L.walkAt) / L.walkMs));
  const face = clamp01((t - L.arriveAt - 120) / L.popMs);
  let step = -1;
  if (t >= L.walkAt - 200 && t < L.outAt) {
    step = 0;
    if (t >= L.walkAt) for (let i = 1; i < marks.length; i++) if (walk >= marks[i] - 1e-6) step = i;
  }
  return {
    pulse: t < 3 * 1200 ? (t % 1200) / 1200 : -1,
    draw: easePage(clamp01((t - L.pathAt) / L.pathMs)),
    shadow: clamp01((t - L.pathAt) / 300),
    walker: t >= L.walkAt ? 1 : 0,
    walk,
    unit: easePage(clamp01((t - L.arriveAt) / L.hlMs)),
    pin: clamp01((t - L.arriveAt) / 200),
    link: clamp01((t - L.arriveAt - 80) / 200),
    face,
    faceScale: 0.85 + 0.15 * easePop(face),
    trail: 1 - clamp01((t - L.outAt) / L.outMs),
    step,
    arrived: t >= L.arriveAt && t < L.outAt + L.outMs,
  };
}

/** The moment in the loop when the walker reaches written step `i` (for tapping a step). */
export function timeForStep(marks: number[], i: number): number {
  const m = marks[i] ?? 1;
  if (i <= 0) return LOOP.walkAt;
  if (m >= 1) return LOOP.arriveAt;
  let lo = 0, hi = 1;
  for (let k = 0; k < 28; k++) {
    const mid = (lo + hi) / 2;
    if (easeWalk(mid) < m) lo = mid; else hi = mid;
  }
  return LOOP.walkAt + hi * LOOP.walkMs + 0.5;
}

/** The point `f` (0-1) of the way along a polyline. */
export function pointAlong(points: [number, number][], f: number): [number, number] {
  if (points.length < 2) return points[0] ?? [0, 0];
  const seg = points.slice(1).map((p, i) => Math.hypot(p[0] - points[i][0], p[1] - points[i][1]));
  let left = clamp01(f) * seg.reduce((a, b) => a + b, 0);
  for (let i = 0; i < seg.length; i++) {
    if (left <= seg[i] || i === seg.length - 1) {
      const k = seg[i] ? Math.min(1, left / seg[i]) : 0;
      return [points[i][0] + (points[i + 1][0] - points[i][0]) * k, points[i][1] + (points[i + 1][1] - points[i][1]) * k];
    }
    left -= seg[i];
  }
  return points[points.length - 1];
}
