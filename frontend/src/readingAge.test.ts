import { describe, expect, it } from "vitest";
import { readingAge, readingAgeText } from "./readingAge";

describe("readingAge", () => {
  it("juvenile subject gives children", () => expect(readingAge([], ["Juvenile fiction"], 4).label).toBe("Children 8–12"));
  it("adult audience is catalogue", () => expect(readingAge(["Adult"], [], 1)).toEqual({ label: "Adult", min_age: 18, source: "catalogue" }));
  it("young adult audience is teen", () => expect(readingAge(["Young adult"], [], 5).label).toBe("Teen"));
  it("level based", () => {
    expect(readingAge([], [], 1).label).toBe("Reading age 12+");
    expect(readingAge([], [], 2, 700).label).toBe("Reading age 15+");
    expect(readingAge([], [], 3).label).toBe("Reading age 15+");
    expect(readingAge([], [], 5).label).toBe("Adult");
  });
  it("marks estimates", () => expect(readingAgeText(readingAge([], [], 1))).toBe("Reading age 12+ · estimated"));
});
