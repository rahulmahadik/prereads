import { afterEach, describe, expect, it, vi } from "vitest";
import { api } from "./api";
import { mergeRanked, rankedOf } from "./components/Discover";

afterEach(() => {
  vi.unstubAllGlobals();
});

const b = (id: string, title = id, ai_rank: number | null = null) => ({ id, title, ai_rank });

describe("deep rerank in the list", () => {
  it("orders the AI's ranked books by rank", () => {
    expect(rankedOf([b("a"), b("x", "X", 2), b("y", "Y", 1), b("c")]).map((r) => r.id)).toEqual(["y", "x"]);
  });
  it("puts them first and drops their repeats (by id or title) from the rest", () => {
    const list = [b("1", "One"), b("2", "Two"), b("3", "Three"), b("4", "Four")];
    const top = [b("3", "Three", 1), b("ol:9", "two ", 2), b("7", "Seven", 3)];
    expect(mergeRanked(top, list).map((r) => r.id)).toEqual(["3", "ol:9", "7", "1", "4"]);
    expect(mergeRanked([], list)).toEqual(list);
  });
});

describe("api.suggestions", () => {
  it("asks for the reader's language, the count and a fresh seed", async () => {
    const fetch = vi.fn(async () => new Response(JSON.stringify({ suggestions: [{ text: "Stoicism for a beginner", kind: "topic", source: "catalogue" }], lang: "zh", from: "catalogue" })));
    vi.stubGlobal("fetch", fetch);
    const r = await api.suggestions("zh", 4, 1700000000123.4);
    expect(String((fetch.mock.calls[0] as unknown[])[0])).toBe("/api/suggestions?lang=zh&n=4&seed=1700000000123");
    expect(r.suggestions[0].text).toBe("Stoicism for a beginner");
    await api.suggestions("en");
    expect(String((fetch.mock.calls[1] as unknown[])[0])).toBe("/api/suggestions?lang=en&n=4");
  });
  it("rejects on a server error, so the UI keeps its built-in examples", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response("{}", { status: 500 })));
    await expect(api.suggestions("en")).rejects.toThrow();
  });
});
