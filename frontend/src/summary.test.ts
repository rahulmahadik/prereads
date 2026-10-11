import { describe, expect, it } from "vitest";
import { cleanSummary } from "./summary";

describe("cleanSummary", () => {
  it("strips markdown links, footnotes and separators", () => {
    const raw = "A **great** book about [biases][1] and choices, written for everyone who decides things.\n\n----------\nAlso contained in: x\n\n[1]: https://example.org";
    expect(cleanSummary(raw)).toBe("A great book about biases and choices, written for everyone who decides things.");
  });
  it("drops source notes and very short or empty text", () => {
    expect(cleanSummary("Short. ([source][2])")).toBe("");
    expect(cleanSummary(undefined)).toBe("");
  });
});
