import type { Route, Stop } from "./types";

export interface MeetPlan {
  a: Stop[];
  b: Stop[];
  shared: string[];
  hoursA: number;
  hoursB: number;
  target: Stop | undefined;
}

const sum = (xs: Stop[]) => Math.round(xs.reduce((n, s) => n + s.readiness.hours, 0) * 10) / 10;

/** Two reading paths to the same target; a book is "shared" when both readers need it. */
export function meetPlan(route: Route, levelA: number, levelB: number): MeetPlan {
  const before = route.stops.filter((s) => s.role === "before");
  const a = before.filter((s) => s.readiness.level >= levelA);
  const b = before.filter((s) => s.readiness.level >= levelB);
  const inB = new Set(b.map((s) => s.book.id));
  const shared = a.filter((s) => inB.has(s.book.id)).map((s) => s.book.id);
  return { a, b, shared, hoursA: sum(a), hoursB: sum(b), target: route.stops.find((s) => s.role === "target") };
}

export function meetSummary(p: MeetPlan): string {
  const one = (n: number, h: number) => `${n} ${n === 1 ? "book" : "books"} · ${h} h`;
  return `Reader 1: ${one(p.a.length, p.hoursA)} — Reader 2: ${one(p.b.length, p.hoursB)}`;
}
