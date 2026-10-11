/* On-device reader state: hearts, paths opened, notes. Nothing leaves the device.
   Pure functions take a Storage so they are testable; React hooks wrap them. */
import { useEffect, useState } from "react";
import type { Route } from "./types";

export interface Heart {
  id: string;
  title: string;
  author: string;
  lineId: string;
  lineTitle: string;
  lineAuthor: string;
  cover_url?: string | null;
  at: number;
}

export interface PathEntry {
  id: string;
  title: string;
  author: string;
  before: { id: string; hours: number }[];
  at: number;
}

export interface PathProgress extends PathEntry {
  done: number;
  total: number;
  hoursLeft: number;
}

const HEARTS = "prereads.hearts";
const PATHS = "prereads.paths";
const NOTES = "prereads.notes";
const READ = "prereads.read";
const EVENT = "prereads:store";

function readJson<T>(s: Storage | undefined, key: string, fallback: T): T {
  try {
    const raw = s?.getItem(key);
    return raw ? (JSON.parse(raw) as T) : fallback;
  } catch {
    return fallback;
  }
}

function writeJson(s: Storage | undefined, key: string, value: unknown): void {
  try {
    s?.setItem(key, JSON.stringify(value));
  } catch {
    /* private mode / quota: on-device state is a convenience */
  }
  if (typeof window !== "undefined") window.dispatchEvent(new Event(EVENT));
}

const store = (): Storage | undefined => {
  try {
    return typeof localStorage === "undefined" ? undefined : localStorage;
  } catch {
    return undefined;
  }
};

/* ---------------- hearts ---------------- */
export function listHearts(s = store()): Heart[] {
  return Object.values(readJson<Record<string, Heart>>(s, HEARTS, {})).sort((a, b) => b.at - a.at);
}

export function isHearted(id: string, s = store()): boolean {
  return id in readJson<Record<string, Heart>>(s, HEARTS, {});
}

export function toggleHeart(h: Omit<Heart, "at">, s = store(), now = Date.now()): boolean {
  const all = readJson<Record<string, Heart>>(s, HEARTS, {});
  const on = !(h.id in all);
  if (on) all[h.id] = { ...h, at: now };
  else delete all[h.id];
  writeJson(s, HEARTS, all);
  return on;
}

/* ---------------- paths ---------------- */
export function recordPath(route: Route, title: string, author: string, s = store(), now = Date.now()): void {
  const all = readJson<Record<string, PathEntry>>(s, PATHS, {});
  all[route.target_id] = {
    id: route.target_id,
    title,
    author,
    before: route.stops.filter((x) => x.role === "before").map((x) => ({ id: x.book.id, hours: x.readiness.hours })),
    at: now,
  };
  writeJson(s, PATHS, all);
}

/** Paths opened on this device, newest first, with hours of PreReads still to read. */
export function pathsInProgress(read: Set<string>, s = store()): PathProgress[] {
  return Object.values(readJson<Record<string, PathEntry>>(s, PATHS, {}))
    .map((p) => {
      const left = p.before.filter((b) => !read.has(b.id));
      return { ...p, done: p.before.length - left.length, total: p.before.length, hoursLeft: Math.round(left.reduce((a, b) => a + b.hours, 0)) };
    })
    .sort((a, b) => b.at - a.at);
}

export function readSetFrom(s = store()): Set<string> {
  return new Set(readJson<string[]>(s, READ, []));
}

/* ---------------- notes ---------------- */
export function getNote(id: string, s = store()): string {
  return readJson<Record<string, string>>(s, NOTES, {})[id] ?? "";
}

export function setNote(id: string, text: string, s = store()): void {
  const all = readJson<Record<string, string>>(s, NOTES, {});
  if (text.trim()) all[id] = text;
  else delete all[id];
  writeJson(s, NOTES, all);
}

export function noteCount(ids: string[], s = store()): number {
  const all = readJson<Record<string, string>>(s, NOTES, {});
  return ids.filter((i) => i in all).length;
}

/* ---------------- hook ---------------- */
/** Re-render when any on-device store changes (this tab or another). */
export function useStoreVersion(): number {
  const [v, setV] = useState(0);
  useEffect(() => {
    const bump = () => setV((x) => x + 1);
    window.addEventListener(EVENT, bump);
    window.addEventListener("storage", bump);
    return () => {
      window.removeEventListener(EVENT, bump);
      window.removeEventListener("storage", bump);
    };
  }, []);
  return v;
}
