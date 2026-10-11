import { describe, expect, it } from "vitest";
import { meetPlan, meetSummary } from "./meet";
import type { Route, Stop } from "./types";

const stop = (id: string, role: Stop["role"], level: number, hours: number) =>
  ({ role, order: 0, book: { id, title: id, author: "x" }, readiness: { level, hours }, why: "", confidence: 1, availability: [], demand: {} }) as unknown as Stop;
const route = {
  target_id: "t",
  stops: [stop("p1", "before", 1, 9), stop("p2", "before", 3, 8), stop("p3", "before", 4, 10), stop("t", "target", 5, 12), stop("n", "after", 5, 5)],
} as unknown as Route;

describe("meetPlan", () => {
  it("filters by level and finds shared books", () => {
    const p = meetPlan(route, 1, 4);
    expect(p.a.map((s) => s.book.id)).toEqual(["p1", "p2", "p3"]);
    expect(p.b.map((s) => s.book.id)).toEqual(["p3"]);
    expect(p.shared).toEqual(["p3"]);
    expect(p.hoursA).toBe(27);
    expect(p.hoursB).toBe(10);
    expect(p.target?.book.id).toBe("t");
  });
  it("same level shares everything", () => {
    expect(meetPlan(route, 3, 3).shared).toEqual(["p2", "p3"]);
  });
  it("summary", () => {
    expect(meetSummary(meetPlan(route, 1, 4))).toBe("Reader 1: 3 books · 27 h — Reader 2: 1 book · 10 h");
  });
});
