import { afterEach, describe, expect, it, vi } from "vitest";
import { DICTS, LANGS, getLang, langFrom, setLang, t, tn, voiceLang, type Key } from "./i18n";

class MemStorage {
  private m = new Map<string, string>();
  getItem(k: string) { return this.m.has(k) ? this.m.get(k)! : null; }
  setItem(k: string, v: string) { this.m.set(k, v); }
  removeItem(k: string) { this.m.delete(k); }
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("dictionaries", () => {
  const keys = Object.keys(DICTS.en) as Key[];
  it.each(["zh", "ms", "ta"] as const)("%s has every English key, none empty", (lang) => {
    const missing = keys.filter((k) => !DICTS[lang][k]?.trim());
    expect(missing).toEqual([]);
    const extra = Object.keys(DICTS[lang]).filter((k) => !(k in DICTS.en));
    expect(extra).toEqual([]);
  });
  it.each(["zh", "ms", "ta"] as const)("%s keeps every {placeholder} of the English string", (lang) => {
    const names = (s: string) => [...s.matchAll(/\{(\w+)\}/g)].map((m) => m[1]).sort();
    const bad = keys.filter((k) => names(DICTS.en[k]!).join() !== names(DICTS[lang][k] ?? "").join());
    expect(bad).toEqual([]);
  });
  it("keeps the product name and the reading-path term", () => {
    for (const l of LANGS) expect(t("home.sub", undefined, l.id)).toContain("PreReads");
    expect(t("line.title", undefined, "zh")).toContain("阅读路线");
    expect(t("line.title", undefined, "ms").toLowerCase()).toContain("laluan bacaan");
    expect(t("line.title", undefined, "ta")).toContain("வாசிப்புப் பாதை");
  });
});

describe("t", () => {
  it("interpolates {name} and leaves unknown placeholders alone", () => {
    expect(t("home.hotAt", { branch: "Bishan" }, "en")).toBe("Hot at Bishan");
    expect(t("home.hotAt", { branch: "Bishan" }, "zh")).toBe("Bishan 热门");
    expect(t("home.hotAt", {}, "en")).toBe("Hot at {branch}");
    expect(t("trip.sameShelf", { n: 2, dewey: "332" }, "en")).toBe("2 of your PreReads are on the same shelf (332) — grab them in one trip");
  });
  it("picks plurals", () => {
    expect(tn("line.summary", 1, { title: "X", hours: 4 }, "en")).toBe("1 book before X · about 4 h of reading");
    expect(tn("line.summary", 3, { title: "X", hours: 4 }, "en")).toBe("3 books before X · about 4 h of reading");
    expect(tn("line.summary", 3, { title: "X", hours: 4 }, "ta")).toContain("நூல்கள்");
  });
  it("falls back to English when a translation is missing", () => {
    const saved = DICTS.zh["home.popular"];
    delete DICTS.zh["home.popular"];
    try {
      expect(t("home.popular", undefined, "zh")).toBe("Popular right now");
    } finally {
      DICTS.zh["home.popular"] = saved;
    }
    expect(t("home.popular", undefined, "zh")).toBe("近期热门");
  });
});

describe("getLang / setLang", () => {
  it("maps browser language tags", () => {
    expect(langFrom("zh-CN")).toBe("zh");
    expect(langFrom("zh-Hant-TW")).toBe("zh");
    expect(langFrom("ms-MY")).toBe("ms");
    expect(langFrom("ta-SG")).toBe("ta");
    expect(langFrom("en-SG")).toBe("en");
    expect(langFrom("fr-FR")).toBe("en");
    expect(langFrom("")).toBe("en");
  });
  it("defaults from navigator.language when nothing is saved", () => {
    vi.stubGlobal("localStorage", new MemStorage());
    vi.stubGlobal("navigator", { language: "ta-IN" });
    expect(getLang()).toBe("ta");
    vi.stubGlobal("navigator", { language: "zh-SG" });
    expect(getLang()).toBe("zh");
    vi.stubGlobal("navigator", { language: "de-DE" });
    expect(getLang()).toBe("en");
  });
  it("prefers the saved choice, and survives blocked storage", () => {
    const s = new MemStorage();
    vi.stubGlobal("localStorage", s);
    vi.stubGlobal("navigator", { language: "en-GB" });
    setLang("ms");
    expect(s.getItem("prereads.lang")).toBe("ms");
    expect(getLang()).toBe("ms");
    expect(t("home.popular")).toBe("Popular sekarang");
    expect(voiceLang()).toBe("ms-MY");
    vi.stubGlobal("localStorage", { getItem: () => { throw new Error("blocked"); }, setItem: () => { throw new Error("blocked"); } });
    expect(getLang()).toBe("en");
    expect(() => setLang("zh")).not.toThrow();
    expect(t("home.popular")).toBe("近期热门");
    expect(voiceLang()).toBe("zh-CN");
    setLang("en");
  });
});
