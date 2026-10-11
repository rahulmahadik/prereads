import { describe, expect, it } from "vitest";
import { LOOP, STILL_MS, frameAt, locate, parseCallNumber, planFor, planSignature, pointAlong, routeFor, stepsFor, timeForStep } from "./wayfind";

const BRANCHES = [
  "Ang Mo Kio Public Library", "Bishan Public Library", "Bukit Panjang Public Library", "Cheng San Public Library",
  "Jurong West Public Library", "Pasir Ris Public Library", "Tampines Regional Library", "Woodlands Regional Library",
];

describe("parseCallNumber", () => {
  it("different Dewey classes go to different bays", () => {
    expect(parseCallNumber("English 332.6 GRA").bayIndex).toBe(3);
    expect(parseCallNumber("English 576.8 DAW").bayIndex).toBe(5);
    expect(parseCallNumber("English 004.015 GRA").bayIndex).toBe(0);
    expect(parseCallNumber("English 153.4 KAH").bayIndex).toBe(1);
  });

  it("tens and units pick the shelf unit", () => {
    expect(parseCallNumber("English 303.49 TET").unit).toBe(0);
    expect(parseCallNumber("English 332.63 MAL").unit).toBe(0);
    expect(parseCallNumber("English 153.4 KAH").unit).toBe(1);
    expect(parseCallNumber("English 576.8 DAW").unit).toBe(2);
  });

  it("same class, different decimals: same bay and unit, close but distinct spots", () => {
    const plan = planFor("Bishan Public Library");
    const a = parseCallNumber("English 153.4 KAH");
    const b = parseCallNumber("English 153.83 ARI");
    expect(a.bayIndex).toBe(b.bayIndex);
    expect(a.unit).toBe(b.unit);
    const sa = locate(a, plan).stand;
    const sb = locate(b, plan).stand;
    expect(sa).not.toEqual(sb);
    expect(Math.hypot(sa[0] - sb[0], sa[1] - sb[1])).toBeLessThan(30);
    expect([a.shelfRow, a.slot]).not.toEqual([b.shelfRow, b.slot]);
  });

  it("the author cutter separates books with the same class number", () => {
    const g = parseCallNumber("English 332.6 GRA");
    const m = parseCallNumber("English 332.6 MAL");
    expect(g.slot! + g.shelfRow! * 1).not.toBe(m.slot! + m.shelfRow! * 1);
  });

  it("rows and slots stay in range for every real call number shape", () => {
    for (const cn of ["English 100 VIT", "English 959.5705092 YEW", "English 006.31 GÉR", "English 999.99 ZZZ", "English 000 AAA"]) {
      const p = parseCallNumber(cn);
      expect(p.kind).toBe("nonfiction");
      expect(p.shelfRow).toBeGreaterThanOrEqual(0);
      expect(p.shelfRow).toBeLessThanOrEqual(2);
      expect(p.slot).toBeGreaterThan(0);
      expect(p.slot).toBeLessThan(1);
    }
    expect(parseCallNumber("English 006.31 GÉR").author).toBe("GER");
  });

  it("fiction letters map to the right A–E / F–J / K–O / P–T / U–Z sections", () => {
    const row = (cn: string) => parseCallNumber(cn).row;
    expect(parseCallNumber("English FIC KIN").kind).toBe("fiction");
    expect(row("English FIC AUS")).toBe(0);
    expect(row("English FIC EVA")).toBe(0);
    expect(row("English FIC FIT")).toBe(1);
    expect(row("English FIC JOY")).toBe(1);
    expect(row("English FIC KIN")).toBe(2);
    expect(row("English FIC ORW")).toBe(2);
    expect(row("English FIC PRA")).toBe(3);
    expect(row("English FIC TOL")).toBe(3);
    expect(row("English FIC UPD")).toBe(4);
    expect(row("English FIC ZAF")).toBe(4);
  });

  it("children's books use the J prefix, even after the language", () => {
    expect(parseCallNumber("English J 523.1 HAW").kind).toBe("children");
    expect(parseCallNumber("JP DAH").kind).toBe("children");
    expect(parseCallNumber("English J FIC DAH").kind).toBe("children");
    expect(parseCallNumber("English 523.1 JON").kind).toBe("nonfiction");
  });
});

describe("planFor", () => {
  it("the same branch always gives the same layout", () => {
    expect(planFor("Jurong West Public Library")).toEqual(planFor("Jurong West Public Library"));
    expect(planSignature(planFor("Jurong West Public Library"))).toBe(planSignature(planFor("jurong west")));
  });

  it("different branches differ", () => {
    const sigs = new Set(BRANCHES.map((b) => planSignature(planFor(b))));
    expect(sigs.size).toBeGreaterThanOrEqual(5);
    expect(planFor("Ang Mo Kio Public Library")).not.toEqual(planFor("Woodlands Regional Library"));
  });

  it("keeps Dewey order along the bank, whichever way it runs", () => {
    for (const b of BRANCHES) {
      const p = planFor(b);
      const dx = p.bayX.slice(1).map((x, i) => x - p.bayX[i]);
      expect(dx.every((d) => (p.flip ? d < 0 : d > 0))).toBe(true);
      expect(Math.min(...p.bayX)).toBeGreaterThan(12);
      expect(Math.max(...p.bayX)).toBeLessThan(800 - 12 - 34);
    }
  });
});

describe("routeFor and stepsFor", () => {
  it("routes start at the door and end where you stand, with a mark per step", () => {
    const p = parseCallNumber("English 332.63 MAL");
    const plan = planFor("Tampines Regional Library");
    const spot = locate(p, plan);
    const r = routeFor(p, plan, spot);
    expect(r.points[0][0]).toBe(plan.doorX);
    expect(r.points[r.points.length - 1]).toEqual(spot.stand);
    expect(r.marks).toHaveLength(stepsFor(p, "English 332.63 MAL", "Tampines Regional Library").length);
    expect(r.marks.every((m, i) => i === 0 || m >= r.marks[i - 1])).toBe(true);
    expect(spot.label).toMatch(/^Shelf [123] · (top|middle|bottom) row$/);
  });

  it("steps name the bay, shelf and row; without a branch they avoid left/right", () => {
    const p = parseCallNumber("English 332.63 MAL");
    const neutral = stepsFor(p, "English 332.63 MAL").map((s) => s.text).join(" ");
    expect(neutral).toContain("300s bay");
    expect(neutral).toContain("332.63 MAL");
    expect(neutral).toMatch(/(Top|Middle|Bottom) row/);
    expect(neutral).not.toMatch(/turn (left|right)/);
    const at = stepsFor(p, "English 332.63 MAL", "Bishan Public Library").map((s) => s.text).join(" ");
    expect(at).toMatch(/turn (left|right) along the non-fiction bays/);
  });
});

describe("route animation loop", () => {
  const p = parseCallNumber("English 332.6 GRA");
  const plan = planFor("Bishan Public Library");
  const route = routeFor(p, plan, locate(p, plan));

  it("starts empty, arrives, holds, fades, then starts again", () => {
    const start = frameAt(0, route.marks);
    expect([start.draw, start.walker, start.walk, start.unit, start.step]).toEqual([0, 0, 0, 0, -1]);
    expect(start.pulse).toBe(0);
    const arrived = frameAt(LOOP.arriveAt + 500, route.marks);
    expect(arrived.walk).toBe(1);
    expect(arrived.arrived).toBe(true);
    expect(arrived.step).toBe(route.marks.length - 1);
    expect(LOOP.outAt - (LOOP.arriveAt + 420)).toBe(1500);          // ~1.5 s hold once everything is lit
    expect(frameAt(LOOP.outAt + LOOP.outMs, route.marks).trail).toBe(0);
    expect(frameAt(LOOP.cycle + 10, route.marks)).toEqual(frameAt(10, route.marks));
  });

  it("the walker only moves forward within a loop", () => {
    let prev = -1;
    for (let ms = 0; ms < LOOP.cycle; ms += 50) {
      const w = frameAt(ms, route.marks).walk;
      expect(w).toBeGreaterThanOrEqual(prev);
      prev = w;
    }
  });

  it("the still frame shows the whole route and the last step", () => {
    const f = frameAt(STILL_MS, route.marks);
    expect([f.draw, f.walk, f.trail, f.unit, f.face, f.pulse]).toEqual([1, 1, 1, 1, 1, -1]);
    expect(f.step).toBe(route.marks.length - 1);
  });

  it("tapping a step puts the walker at that step", () => {
    route.marks.forEach((m, i) => {
      const f = frameAt(timeForStep(route.marks, i), route.marks);
      expect(f.step).toBe(i);
      expect(Math.abs(f.walk - m)).toBeLessThan(0.01);
    });
  });

  it("pointAlong follows the route from the door to the shelf", () => {
    expect(pointAlong(route.points, 0)).toEqual(route.points[0]);
    expect(pointAlong(route.points, 1)).toEqual(route.points[route.points.length - 1]);
    const [x, y] = pointAlong([[0, 0], [10, 0], [10, 10]], 0.75);
    expect([x, y]).toEqual([10, 5]);
  });
});
