import { useEffect, useState } from "react";
import type { ReactNode } from "react";
import { back, navigate } from "../router";
import { t, useLang } from "../i18n";

/* ------------------------------------------------------------ top bar */
export function TopBar({ title, onBack, right, home = true }: { title?: string; onBack?: () => void; right?: ReactNode; home?: boolean }) {
  useLang();
  return (
    <header className="topbar">
      <span className="topbar-left">
        {onBack ? (
          <button type="button" className="icon-btn" onClick={onBack} aria-label={t("common.back")}>
            ←
          </button>
        ) : (
          <span className="icon-btn placeholder" aria-hidden="true" />
        )}
        {home && (
          <button type="button" className="icon-btn" onClick={() => navigate("home")} aria-label={t("common.startOver")} title={t("common.startOver")}>
            🏠
          </button>
        )}
      </span>
      <div className="topbar-title">{title}</div>
      <div className="topbar-right">{right}</div>
    </header>
  );
}

export function useBack(fallback: "home" | "line" = "home") {
  return () => back(fallback);
}

/* --------------------------------------------------------- bottom sheet */
export function Sheet({ open, title, onClose, children }: { open: boolean; title: string; onClose: () => void; children: ReactNode }) {
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    document.body.style.overflow = "hidden";
    return () => {
      window.removeEventListener("keydown", onKey);
      document.body.style.overflow = "";
    };
  }, [open, onClose]);
  if (!open) return null;
  return (
    <div className="sheet-backdrop" onClick={onClose}>
      <div className="sheet" role="dialog" aria-modal="true" aria-label={title} onClick={(e) => e.stopPropagation()}>
        <div className="sheet-grab" aria-hidden="true" />
        <div className="sheet-head">
          <h2>{title}</h2>
          <button type="button" className="icon-btn" onClick={onClose} aria-label={t("common.close")}>
            ✕
          </button>
        </div>
        <div className="sheet-body">{children}</div>
      </div>
    </div>
  );
}

/* ------------------------------------------------------ progress store */
const KEY = "prereads.read";

function load(): Set<string> {
  try {
    return new Set(JSON.parse(localStorage.getItem(KEY) || "[]"));
  } catch {
    return new Set();
  }
}

export function useReadSet(): [Set<string>, (id: string) => void] {
  const [set, setSet] = useState<Set<string>>(load);
  const toggle = (id: string) => {
    const next = new Set(set);
    if (next.has(id)) next.delete(id);
    else next.add(id);
    localStorage.setItem(KEY, JSON.stringify([...next]));
    setSet(next);
  };
  return [set, toggle];
}

/* -------------------------------------------------------- readiness */
const RKEY = "prereads.readerLevel";
export function getReaderLevel(): number {
  const v = Number(localStorage.getItem(RKEY) || "1");
  return v >= 1 && v <= 5 ? v : 1;
}
export function setReaderLevel(level: number) {
  localStorage.setItem(RKEY, String(level));
}

/* ------------------------------------------------------------- NLB */
// Public catalogue search; opens in a new tab or the system browser from a WebView.
export function nlbSearchUrl(title: string, isbn?: string | null): string {
  const q = isbn || title;
  return `https://catalogue.nlb.gov.sg/search/card?keyword=${encodeURIComponent(q)}`;
}

export function shortBranch(b: string): string {
  return b.replace(" Public Library", "").replace(" Regional Library", "").replace(" Library", "");
}

/* ------------------------------------------------------- shelf status */
import type { Availability, Stop } from "../types";

type ShelfStatus =
  | { kind: "available"; branch: string; code: string; callNumber: string; others: number }
  | { kind: "elsewhere"; branch: string; code: string; callNumber: string; here: string }
  | { kind: "waiting"; callNumber: string }
  | { kind: "none" };

/** Reader-facing decision, not inventory. Prefer the branch the reader is in. */
export function shelfStatus(stop: Stop, preferredCode?: string): ShelfStatus {
  const avail = stop.availability;
  if (!avail.length) return { kind: "none" };
  const inStock = avail.filter((a) => a.available > 0);
  const preferred = preferredCode ? avail.find((a) => a.branch_code === preferredCode) : undefined;
  if (preferred && preferred.available > 0) {
    return { kind: "available", branch: preferred.branch, code: preferred.branch_code, callNumber: preferred.call_number, others: inStock.length - 1 };
  }
  if (!inStock.length) return { kind: "waiting", callNumber: avail[0].call_number };
  const best: Availability = [...inStock].sort((a, b) => b.available - a.available)[0];
  if (preferredCode) {
    return { kind: "elsewhere", branch: best.branch, code: best.branch_code, callNumber: best.call_number, here: preferred?.branch ?? t("lib.thisLibrary") };
  }
  return { kind: "available", branch: best.branch, code: best.branch_code, callNumber: best.call_number, others: inStock.length - 1 };
}

const BKEY = "prereads.branch";
export function getBranch(): string {
  return localStorage.getItem(BKEY) || "";
}
export function setBranch(code: string) {
  if (code) localStorage.setItem(BKEY, code);
  else localStorage.removeItem(BKEY);
}

export const FAMILIARITY = [
  { level: 1, title: "New to this", sub: "Never read about it. Start me gently." },
  { level: 3, title: "Read a bit", sub: "I've read a popular book or two on it." },
  { level: 4, title: "Know it well", sub: "Studied or worked in it. Skip the basics." },
];
/** FAMILIARITY title / sub in the current UI language (the array itself stays English for older callers). */
export const famTitle = (level: number) => t(`fam.${level}.title` as "fam.1.title");
export const famSub = (level: number) => t(`fam.${level}.sub` as "fam.1.sub");

/* ------------------------------------------------- only-available preference */
const AKEY = "prereads.onlyAvailable";
export function getOnlyAvailable(): boolean {
  return localStorage.getItem(AKEY) === "1";
}
export function setOnlyAvailable(v: boolean) {
  localStorage.setItem(AKEY, v ? "1" : "0");
}

export function AvailToggle({ on, onChange, label = t("avail.only") }: { on: boolean; onChange: (v: boolean) => void; label?: string }) {
  return (
    <button type="button" className={`avail-toggle ${on ? "on" : ""}`} role="switch" aria-checked={on} onClick={() => onChange(!on)}>
      <span className="sw" aria-hidden="true" />
      {label}
    </button>
  );
}

/** Scroll to the shelf map (#find), or to the shelf status when no copy is on a shelf to map. */
export function scrollToShelf() {
  const el = document.getElementById("find") ?? document.getElementById("where");
  const smooth = !window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
  el?.scrollIntoView({ behavior: smooth ? "smooth" : "auto", block: "start" });
}
