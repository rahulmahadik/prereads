import jsQR from "jsqr";
import { describe, expect, it } from "vitest";
import { qrMatrix, qrSvgPath } from "./qr";

function decode(matrix: boolean[][], scale = 4, quiet = 4): string | null {
  const size = (matrix.length + quiet * 2) * scale;
  const px = new Uint8ClampedArray(size * size * 4).fill(255);
  matrix.forEach((row, y) =>
    row.forEach((dark, x) => {
      if (!dark) return;
      for (let dy = 0; dy < scale; dy++)
        for (let dx = 0; dx < scale; dx++) {
          const i = (((y + quiet) * scale + dy) * size + (x + quiet) * scale + dx) * 4;
          px[i] = px[i + 1] = px[i + 2] = 0;
        }
    }),
  );
  return jsQR(px, size, size)?.data ?? null;
}

const url =
  "https://prereads.example.org/app/#/line?id=bk-1234567&title=" +
  encodeURIComponent("Thinking, Fast and Slow: a long title") +
  "&author=" +
  encodeURIComponent("Daniel Kahneman");

describe("qr encoder", () => {
  it("round-trips short and long strings across versions", () => {
    const cases = [
      "A",
      "PreReads",
      "Hello, world! 0123456789",
      "x".repeat(60),
      url,
      url + "&pad=" + "z".repeat(60),
      "y".repeat(180),
      "Café – 読書 ✓",
      "w".repeat(213),
    ];
    for (const text of cases) {
      expect(decode(qrMatrix(text)), text.slice(0, 20)).toBe(text);
    }
  });

  it("uses the expected sizes and rejects oversize input", () => {
    expect(qrMatrix("A").length).toBe(21);
    expect(qrMatrix("w".repeat(213)).length).toBe(57);
    expect(url.length).toBeGreaterThan(110);
    expect(() => qrMatrix("w".repeat(214))).toThrow();
  });

  it("builds an svg path of the dark modules", () => {
    const d = qrSvgPath(qrMatrix("PreReads"), 2);
    expect(d.startsWith("M")).toBe(true);
    expect((d.match(/z/g) ?? []).length).toBeGreaterThan(20);
  });
});
