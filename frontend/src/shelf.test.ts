import { describe, expect, it } from "vitest";
import { deweyClass, sameShelfGroups, sameShelfText } from "./shelf";
import type { Stop } from "./types";

const stop = (id: string, call: string, available = 1, role: Stop["role"] = "before", code = "BIPL"): Stop =>
  ({ role, book: { id, title: id }, availability: [{ branch: "Bishan Public Library", branch_code: code, call_number: call, available, total: 2, demo: true }] }) as unknown as Stop;

describe("deweyClass", () => {
  it("reads the first three digits", () => {
    expect(deweyClass("English 153.4 KAH")).toBe("153");
    expect(deweyClass("332.024 TAN")).toBe("332");
    expect(deweyClass("English FIC ATW")).toBeNull();
    expect(deweyClass("")).toBeNull();
    expect(deweyClass(undefined)).toBeNull();
  });
});

describe("sameShelfGroups", () => {
  const stops = [stop("a", "English 332.024 TAN"), stop("b", "English 332.6 BOG"), stop("c", "English 153.4 KAH"), stop("t", "English 332.1 X", 1, "target")];
  it("groups unread PreReads on one Dewey class at the branch", () => {
    const g = sameShelfGroups(stops, "BIPL", "Bishan Public Library", new Set());
    expect(g).toHaveLength(1);
    expect(g[0].dewey).toBe("332");
    expect(g[0].stops.map((s) => s.book.id)).toEqual(["a", "b"]);
    expect(sameShelfText(g[0])).toBe("2 of your PreReads are on the same shelf (332) — grab them in one trip");
  });
  it("ignores read books, empty shelves, the target and other branches", () => {
    expect(sameShelfGroups(stops, "BIPL", undefined, new Set(["a"]))).toEqual([]);
    expect(sameShelfGroups([stop("a", "332.1 A", 0), stop("b", "332.2 B")], "BIPL", undefined, new Set())).toEqual([]);
    expect(sameShelfGroups(stops, "TRL", "Tampines Regional Library", new Set())).toEqual([]);
    expect(sameShelfGroups(stops, "", undefined, new Set())).toEqual([]);
  });
});
