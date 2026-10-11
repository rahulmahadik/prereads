import { describe, expect, it } from "vitest";
import { getNote, isHearted, listHearts, noteCount, pathsInProgress, recordPath, setNote, toggleHeart } from "./myshelf";
import type { Route } from "./types";

class MemStorage implements Storage {
  private m = new Map<string, string>();
  get length() { return this.m.size; }
  clear() { this.m.clear(); }
  getItem(k: string) { return this.m.has(k) ? this.m.get(k)! : null; }
  key(i: number) { return [...this.m.keys()][i] ?? null; }
  removeItem(k: string) { this.m.delete(k); }
  setItem(k: string, v: string) { this.m.set(k, v); }
}

const h = { id: "b1", title: "Nudge", author: "Thaler", lineId: "t1", lineTitle: "Thinking", lineAuthor: "Kahneman" };

describe("hearts", () => {
  it("toggles on and off, newest first", () => {
    const s = new MemStorage();
    expect(toggleHeart(h, s, 1)).toBe(true);
    expect(toggleHeart({ ...h, id: "b2", title: "Noise" }, s, 2)).toBe(true);
    expect(isHearted("b1", s)).toBe(true);
    expect(listHearts(s).map((x) => x.id)).toEqual(["b2", "b1"]);
    expect(toggleHeart(h, s, 3)).toBe(false);
    expect(isHearted("b1", s)).toBe(false);
  });
  it("survives corrupt storage", () => {
    const s = new MemStorage();
    s.setItem("prereads.hearts", "{not json");
    expect(listHearts(s)).toEqual([]);
    expect(toggleHeart(h, s)).toBe(true);
  });
});

describe("paths in progress", () => {
  const route = {
    target_id: "t1",
    stops: [
      { role: "before", book: { id: "a" }, readiness: { hours: 8 } },
      { role: "before", book: { id: "b" }, readiness: { hours: 5.6 } },
      { role: "target", book: { id: "t1" }, readiness: { hours: 16 } },
    ],
  } as unknown as Route;
  it("counts hours left from what is read", () => {
    const s = new MemStorage();
    recordPath(route, "Thinking, Fast and Slow", "Kahneman", s, 10);
    const [p] = pathsInProgress(new Set(["a"]), s);
    expect(p).toMatchObject({ id: "t1", done: 1, total: 2, hoursLeft: 6 });
    expect(pathsInProgress(new Set(), s)[0].hoursLeft).toBe(14);
  });
});

describe("notes", () => {
  it("saves, counts and clears", () => {
    const s = new MemStorage();
    setNote("a", "Read chapter 3 first", s);
    setNote("b", "   ", s);
    expect(getNote("a", s)).toBe("Read chapter 3 first");
    expect(noteCount(["a", "b", "c"], s)).toBe(1);
    setNote("a", "", s);
    expect(noteCount(["a"], s)).toBe(0);
  });
});
