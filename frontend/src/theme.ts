import { useEffect, useState } from "react";

/** Reader appearance: colour theme, body font and a text-size step. Persisted per device, applied to <html>. */
export type Theme = "system" | "light" | "dark" | "sepia";
export type Resolved = Exclude<Theme, "system">;
export type Font = "sans" | "serif";
export type Size = "sm" | "md" | "lg";

export const THEMES: Theme[] = ["system", "light", "dark", "sepia"];
export const FONTS: Font[] = ["sans", "serif"];
export const SIZES: Size[] = ["sm", "md", "lg"];

/** --fs-scale per step: A− / A / A+. Senior mode multiplies on top (its own base sizes). */
export const SIZE_SCALE: Record<Size, number> = { sm: 0.9, md: 1, lg: 1.15 };

/** Browser chrome colour per theme (matches --paper). */
export const THEME_COLOR: Record<Resolved, string> = { light: "#F3F6F9", dark: "#0F1720", sepia: "#F4ECD8" };

/** Header button icon for the resolved theme. */
export const THEME_ICON: Record<Resolved, string> = { light: "☀️", dark: "🌙", sepia: "📖" };

export const THEME_EVENT = "prereads:appearance";
const KEY = { theme: "prereads.theme", font: "prereads.font", size: "prereads.size" } as const;

function read(key: string): string | null {
  try {
    return localStorage.getItem(key);
  } catch {
    return null;
  }
}

function write(key: string, value: string) {
  try {
    localStorage.setItem(key, value);
  } catch {
    /* private mode or storage blocked: the choice still applies for this visit */
  }
}

const isTheme = (v: unknown): v is Theme => THEMES.includes(v as Theme);
const isFont = (v: unknown): v is Font => FONTS.includes(v as Font);
const isSize = (v: unknown): v is Size => SIZES.includes(v as Size);

export const getTheme = (): Theme => {
  const v = read(KEY.theme);
  return isTheme(v) ? v : "system";
};
export const getFont = (): Font => {
  const v = read(KEY.font);
  return isFont(v) ? v : "sans";
};
export const getSize = (): Size => {
  const v = read(KEY.size);
  return isSize(v) ? v : "md";
};

export function systemPrefersDark(): boolean {
  try {
    return typeof matchMedia === "function" && matchMedia("(prefers-color-scheme: dark)").matches;
  } catch {
    return false;
  }
}

export function resolveTheme(theme: Theme = getTheme(), prefersDark: boolean = systemPrefersDark()): Resolved {
  if (theme === "system") return prefersDark ? "dark" : "light";
  return theme;
}

/** The header button cycles light → dark → reading → light, starting from what is on screen now. */
export function nextTheme(current: Resolved): Resolved {
  return current === "light" ? "dark" : current === "dark" ? "sepia" : "light";
}

/** Writes data-theme / data-font / data-size, the --fs-scale and <meta name="theme-color"> onto the document. */
export function applyAppearance(doc: Document = document) {
  const root = doc.documentElement;
  const pref = getTheme();
  const resolved = resolveTheme(pref);
  const size = getSize();
  root.dataset.theme = resolved;
  root.dataset.themePref = pref;
  root.dataset.font = getFont();
  root.dataset.size = size;
  root.style.setProperty("--fs-scale", String(SIZE_SCALE[size]));
  root.style.colorScheme = resolved === "dark" ? "dark" : "light";
  let meta = doc.querySelector<HTMLMetaElement>('meta[name="theme-color"]');
  if (!meta) {
    meta = doc.createElement("meta");
    meta.name = "theme-color";
    doc.head.appendChild(meta);
  }
  meta.content = THEME_COLOR[resolved];
  return resolved;
}

function changed() {
  applyAppearance();
  try {
    window.dispatchEvent(new Event(THEME_EVENT));
  } catch {
    /* no window (tests) */
  }
}

/** A ~200 ms cross-fade while the colours swap; skipped when the reader asks for reduced motion. */
function crossFade() {
  try {
    if (typeof matchMedia === "function" && matchMedia("(prefers-reduced-motion: reduce)").matches) return;
    const cl = document.documentElement.classList;
    if (!cl) return;
    cl.add("theme-fading");
    setTimeout(() => cl.remove("theme-fading"), 260);
  } catch {
    /* no document (tests) */
  }
}

export function setTheme(theme: Theme) {
  if (!isTheme(theme)) return;
  write(KEY.theme, theme);
  crossFade();
  changed();
}
export function setFont(font: Font) {
  if (!isFont(font)) return;
  write(KEY.font, font);
  changed();
}
export function setSize(size: Size) {
  if (!isSize(size)) return;
  write(KEY.size, size);
  changed();
}

let started = false;
/** Apply once before React renders, and follow the OS setting while the theme is "System". */
export function initAppearance() {
  applyAppearance();
  if (started) return;
  started = true;
  try {
    const mq = matchMedia("(prefers-color-scheme: dark)");
    const onChange = () => {
      if (getTheme() !== "system") return;
      crossFade();
      changed();
    };
    if (mq.addEventListener) mq.addEventListener("change", onChange);
    else mq.addListener?.(onChange);
  } catch {
    /* old browser: System stays on whatever it resolved at load */
  }
}

export interface Appearance {
  theme: Theme;
  resolved: Resolved;
  font: Font;
  size: Size;
}

const snapshot = (): Appearance => ({ theme: getTheme(), resolved: resolveTheme(), font: getFont(), size: getSize() });

/** Re-renders when any appearance setting changes (here or from another component). */
export function useAppearance(): Appearance {
  const [a, setA] = useState(snapshot);
  useEffect(() => {
    const on = () => setA(snapshot());
    window.addEventListener(THEME_EVENT, on);
    return () => window.removeEventListener(THEME_EVENT, on);
  }, []);
  return a;
}
