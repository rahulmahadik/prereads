/**
 * Wayfinding logic (pure, no React): call number -> bay / shelf unit / row / position,
 * and a per-branch schematic floor plan (seeded by the branch, so each library looks
 * different but always the same). WayfindMap.tsx only draws what this returns.
 */

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
    return { stand: [gx, sy], unitRect: { x: bx, y, w: NF_W, h: UNIT_H }, bayLabelX: bx + NF_W / 2, rowName, label: `Shelf ${u + 1} · ${rowName} row` };
  }
  if (p.kind === "fiction") {
    const row = p.row ?? 2;
    const within = (cutterFraction(p.author) * 26 - row * 5) / (row === 4 ? 6 : 5);
    const x = FIC_X + 12 + within * (FIC_W - 24);
    return { stand: [Math.min(FIC_X + FIC_W - 8, Math.max(FIC_X + 8, x)), FIC_ROWS[row] + 28], unitRect: { x: FIC_X, y: FIC_ROWS[row], w: FIC_W, h: 18 }, label: `Fiction ${FIC_SECTIONS[row]}` };
  }
  if (p.kind === "children") {
    const row = Math.min(2, Math.floor(cutterFraction(p.author) * 3));
    return { stand: [KIDS.x + 170, KIDS.y + 23 + row * 28], unitRect: { x: KIDS.x + 180, y: KIDS.y + 16 + row * 28, w: 100, h: 14 }, label: `Children's shelf ${row + 1}` };
  }
  return { stand: [MAIN_X, 470], label: "Information counter" };
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
  const enter =
    !plan || plan.doorX === MAIN_X ? "Go through the gates and walk straight up the main aisle, past the counter." :
    `Go in, turn ${plan.doorX < MAIN_X ? "right" : "left"}, then walk up the main aisle past the counter.`;
  if (p.kind === "nonfiction" && p.bayIndex !== undefined) {
    const spot = plan ? locate(p, plan) : null;
    const dir = spot ? (spot.stand[0] < MAIN_X ? "left" : "right") : "";
    const rowName = ROW_NAMES[p.shelfRow ?? 1];
    const where = (p.slot ?? 0.5) < 0.34 ? "near the left end" : (p.slot ?? 0.5) > 0.66 ? "near the right end" : "about halfway along";
    return [
      { icon: "🚪", text: enter },
      { icon: dir === "right" ? "↱" : "↰", text: dir ? `At the top of the aisle, turn ${dir} along the non-fiction bays.` : "At the top of the aisle, follow the non-fiction bays in Dewey order." },
      { icon: "📚", text: `Walk to the ${p.bayIndex}00s bay (${NF_LABELS[p.bayIndex]}) and stop at shelf ${(p.unit ?? 0) + 1} from the aisle.` },
      { icon: "🔎", text: `${rowName[0].toUpperCase()}${rowName.slice(1)} row, ${where}: look for ${short}.` },
    ];
  }
  if (p.kind === "children") {
    return [
      { icon: "🚪", text: enter },
      { icon: "↱", text: "Turn right into the children's corner, the one with the round rug." },
      { icon: "🔎", text: p.author ? `The low shelves run by author: look for ${p.author}.` : `Look for ${short} on the spines.` },
    ];
  }
  if (p.kind === "fiction") {
    return [
      { icon: "🚪", text: enter },
      { icon: "↰", text: `Turn left into the fiction stacks and go to the ${FIC_SECTIONS[p.row ?? 2]} row.` },
      { icon: "🔎", text: p.author ? `Fiction is shelved A–Z by author surname: find ${p.author}.` : `Look for ${short} on the spines.` },
    ];
  }
  return [{ icon: "🛎️", text: "Ask at the counter: this call number doesn't match a zone on the map." }];
}
