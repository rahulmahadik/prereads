import { describe, expect, it } from "vitest";
import { clockLabel, formatKm, haversineKm, openState, sortByDistance } from "./geo";
import type { Branch } from "./types";

const hours = { open: "10:00", close: "21:00" };
// 2026-10-11 is a Sunday; times below are Singapore (UTC+8).
const sg = (hhmm: string) => new Date(`2026-10-11T${hhmm}:00+08:00`);

describe("haversineKm", () => {
  it("is zero for the same point", () => expect(haversineKm(1.35, 103.8, 1.35, 103.8)).toBeCloseTo(0, 5));
  it("matches a known Singapore distance", () => {
    // Bishan to Tampines is roughly 11-12 km
    const d = haversineKm(1.3503, 103.8556, 1.3535, 103.9449);
    expect(d).toBeGreaterThan(9.5);
    expect(d).toBeLessThan(10.5);
  });
});

describe("openState", () => {
  it("is open mid-day", () => expect(openState(hours, sg("14:00"))).toEqual({ open: true, label: "Open now · closes 9pm" }));
  it("is closed in the evening and names the next opening", () => expect(openState(hours, sg("21:30"))).toEqual({ open: false, label: "Closed · opens 10am" }));
  it("is closed before opening", () => expect(openState(hours, sg("08:15")).open).toBe(false));
  it("closes exactly at closing time", () => expect(openState(hours, sg("21:00")).open).toBe(false));
  it("uses Singapore time, not the device zone", () => {
    // 03:00 UTC is 11:00 in Singapore
    expect(openState(hours, new Date("2026-10-11T03:00:00Z")).open).toBe(true);
    // 14:00 UTC is 22:00 in Singapore
    expect(openState(hours, new Date("2026-10-11T14:00:00Z")).open).toBe(false);
  });
  it("handles missing hours", () => expect(openState(undefined, sg("12:00")).open).toBe(false));
});

describe("clockLabel", () => {
  it("formats", () => {
    expect(clockLabel("21:00")).toBe("9pm");
    expect(clockLabel("10:00")).toBe("10am");
    expect(clockLabel("12:00")).toBe("12pm");
    expect(clockLabel("09:30")).toBe("9:30am");
  });
});

describe("sortByDistance", () => {
  const b = (code: string, lat?: number, lng?: number): Branch => ({ code, name: code, lat, lng });
  it("sorts nearest first and drops branches without coordinates", () => {
    const out = sortByDistance([b("TRL", 1.3535, 103.9449), b("X"), b("BIPL", 1.3503, 103.8556), b("JWPL", 1.3406, 103.7226)], 1.351, 103.85);
    expect(out.map((x) => x.code)).toEqual(["BIPL", "TRL", "JWPL"]);
    expect(out[0].km).toBeLessThan(out[1].km);
  });
});

describe("formatKm", () => {
  it("formats", () => {
    expect(formatKm(1.234)).toBe("1.2 km");
    expect(formatKm(12.6)).toBe("13 km");
  });
});
