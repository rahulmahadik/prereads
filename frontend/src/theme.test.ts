import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  THEME_COLOR,
  THEME_EVENT,
  applyAppearance,
  getFont,
  getSize,
  getTheme,
  nextTheme,
  resolveTheme,
  setFont,
  setSize,
  setTheme,
} from "./theme";

class MemStorage {
  m = new Map<string, string>();
  getItem(k: string) { return this.m.has(k) ? this.m.get(k)! : null; }
  setItem(k: string, v: string) { this.m.set(k, v); }
  removeItem(k: string) { this.m.delete(k); }
}

/** Just enough of a Document for applyAppearance: <html> dataset/style and one theme-color meta. */
function fakeDoc() {
  const props: Record<string, string> = {};
  const meta = { name: "theme-color", content: "" };
  const root = { dataset: {} as Record<string, string>, style: { colorScheme: "", setProperty: (k: string, v: string) => (props[k] = v) } };
  return {
    props,
    meta,
    doc: { documentElement: root, querySelector: () => meta, head: { appendChild: () => {} }, createElement: () => ({}) },
  };
}

let dark = false;
let events = 0;
let f: ReturnType<typeof fakeDoc>;

beforeEach(() => {
  dark = false;
  events = 0;
  f = fakeDoc();
  vi.stubGlobal("localStorage", new MemStorage());
  vi.stubGlobal("matchMedia", (q: string) => ({ matches: q.includes("dark") && dark }));
  vi.stubGlobal("document", f.doc);
  vi.stubGlobal("window", { dispatchEvent: (e: Event) => e.type === THEME_EVENT && events++ });
});
afterEach(() => vi.unstubAllGlobals());

describe("appearance defaults", () => {
  it("is System · Sans · A when nothing is stored", () => {
    expect(getTheme()).toBe("system");
    expect(getFont()).toBe("sans");
    expect(getSize()).toBe("md");
  });
  it("ignores junk in storage", () => {
    localStorage.setItem("prereads.theme", "neon");
    localStorage.setItem("prereads.font", "comic");
    localStorage.setItem("prereads.size", "xxl");
    expect([getTheme(), getFont(), getSize()]).toEqual(["system", "sans", "md"]);
  });
  it("survives storage that throws (private mode)", () => {
    vi.stubGlobal("localStorage", { getItem: () => { throw new Error("blocked"); }, setItem: () => { throw new Error("blocked"); } });
    expect(getTheme()).toBe("system");
    expect(() => setTheme("dark")).not.toThrow();
  });
});

describe("theme", () => {
  it("System follows prefers-color-scheme", () => {
    expect(resolveTheme("system", false)).toBe("light");
    expect(resolveTheme("system", true)).toBe("dark");
    expect(resolveTheme("sepia", true)).toBe("sepia");
    dark = true;
    expect(resolveTheme()).toBe("dark");
  });
  it("persists, applies data-theme, colour-scheme and theme-color, and tells listeners", () => {
    setTheme("dark");
    expect(getTheme()).toBe("dark");
    expect(f.doc.documentElement.dataset.theme).toBe("dark");
    expect(f.doc.documentElement.dataset.themePref).toBe("dark");
    expect(f.doc.documentElement.style.colorScheme).toBe("dark");
    expect(f.meta.content).toBe(THEME_COLOR.dark);
    expect(events).toBe(1);
    setTheme("sepia");
    expect(f.doc.documentElement.dataset.theme).toBe("sepia");
    expect(f.meta.content).toBe(THEME_COLOR.sepia);
  });
  it("rejects an unknown theme without touching storage", () => {
    setTheme("neon" as never);
    expect(localStorage.getItem("prereads.theme")).toBeNull();
    expect(events).toBe(0);
  });
  it("the header button cycles light → dark → reading → light", () => {
    expect(nextTheme("light")).toBe("dark");
    expect(nextTheme("dark")).toBe("sepia");
    expect(nextTheme("sepia")).toBe("light");
  });
});

describe("font and size", () => {
  it("sets data-font", () => {
    setFont("serif");
    expect(getFont()).toBe("serif");
    expect(f.doc.documentElement.dataset.font).toBe("serif");
  });
  it("scales --fs with A− / A / A+", () => {
    applyAppearance(f.doc as unknown as Document);
    expect(f.props["--fs-scale"]).toBe("1");
    setSize("lg");
    expect(f.props["--fs-scale"]).toBe("1.15");
    expect(f.doc.documentElement.dataset.size).toBe("lg");
    setSize("sm");
    expect(f.props["--fs-scale"]).toBe("0.9");
  });
});
