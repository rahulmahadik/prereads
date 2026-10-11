import { getLang } from "./i18n";
import type { Neighbour, AskResponse, Branch, DiscoverResponse, ResolveHit, Route } from "./types";

// Same-origin by default. For the mobile shell (WebView) or a split deploy, set
// VITE_API_BASE=https://your-api.example.com at build time.
const BASE: string = (import.meta.env.VITE_API_BASE as string | undefined)?.replace(/\/$/, "") ?? "";
const url = (path: string) => `${BASE}${path}`;

async function json<T>(res: Response): Promise<T> {
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = body.detail || detail;
    } catch {
      /* keep statusText */
    }
    throw new Error(detail);
  }
  return res.json() as Promise<T>;
}

const live = {
  mode: () => fetch(url("/api/mode")).then((r) => json<import("./components/SettingsSheet").ModeInfo>(r)),
  setMode: (patch: { demo?: boolean; use_llm?: boolean; use_nlb?: boolean }) =>
    fetch(url("/api/mode"), { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(patch) }).then((r) => json<import("./components/SettingsSheet").ModeInfo>(r)),
  health: () => fetch(url("/api/health")).then((r) => json<{ ok: boolean; mode: string; cached_routes: number }>(r)),
  resolve: (q: string, offset = 0, limit = 8) =>
    fetch(url(`/api/resolve?q=${encodeURIComponent(q)}&offset=${offset}&limit=${limit}`)).then((r) => json<{ results: ResolveHit[]; total: number; offset: number; limit: number; has_more: boolean }>(r)),
  route: (id: string, title?: string, author?: string) => {
    const p = new URLSearchParams({ id });
    if (title) p.set("title", title);
    if (author) p.set("author", author);
    return fetch(url(`/api/route?${p.toString()}`)).then((r) => json<Route>(r));
  },
  similar: (id: string, branch: string) =>
    fetch(url(`/api/similar?id=${encodeURIComponent(id)}${branch ? `&branch=${encodeURIComponent(branch)}` : ""}`)).then((r) => json<{ books: Neighbour[] }>(r)),
  branches: () => fetch(url("/api/branches")).then((r) => json<{ branches: Branch[] }>(r)),
  browse: (by: "author" | "category") => fetch(url(`/api/browse?by=${by}`)).then((r) => json<{ groups: { label: string; count: number; ids: string[] }[] }>(r)),
  browseBooks: (ids: string[]) => fetch(url(`/api/browse?ids=${encodeURIComponent(ids.join(","))}`)).then((r) => json<{ books: { id: string; title: string; author: string }[] }>(r)),
  chat: (text: string, state: unknown, lang?: string) =>
    fetch(url("/api/chat"), { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ text, state, lang: lang ?? getLang() }) }).then((r) =>
      json<{ messages: string[]; options: { label: string; value: string }[]; state: { step: string }; result?: { book_id: string; title: string; author: string; level: number; branch: string; start_id: string; start_title: string; start_status: string } | null }>(r),
    ),
  // mode "fast" (default): no model, no network, well under a second. "deep": the local AI's picks too (slow).
  discover: (text: string, branch: string, filters: string[], offset = 0, limit = 10, opts: { mode?: "fast" | "deep"; signal?: AbortSignal; lang?: string } = {}) =>
    fetch(url("/api/discover"), { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ text, branch: branch || null, filters, offset, limit, mode: opts.mode ?? "fast", lang: opts.lang ?? getLang() }), signal: opts.signal }).then((r) =>
      json<DiscoverResponse>(r),
    ),
  targets: () => fetch(url("/api/targets")).then((r) => json<{ targets: { id: string; title: string; author: string; unfinished?: boolean }[] }>(r)),
  popular: (limit = 12) => fetch(url(`/api/popular?limit=${limit}`)).then((r) => json<{ popular: { id: string; title: string; author: string; category: string; hot_at: string[]; queue: number; score: number; demo: boolean }[] }>(r)),
  ask: (target_id: string, intent: "why_before" | "time_budget" | "large_print", weeks?: number, lang?: string) =>
    fetch(url("/api/ask"), {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ target_id, intent, weeks, lang: lang ?? getLang() }),
    }).then((r) => json<AskResponse>(r)),
  scan: (file: File) => {
    const fd = new FormData();
    fd.append("image", file);
    return fetch(url("/api/scan"), { method: "POST", body: fd }).then((r) =>
      json<{ title: string; author: string; isbn?: string | null; confidence: number }>(r),
    );
  },
};

// ---------------------------------------------------------------------------
// Static prototype (GitHub Pages): scripts/build_prototype.py injects
// window.__PREREADS_DATA__; the GET endpoints are then served from it, no server.
// ---------------------------------------------------------------------------
/* eslint-disable @typescript-eslint/no-explicit-any */
const P: any = typeof window !== "undefined" ? (window as any).__PREREADS_DATA__ : undefined;
const wait = <T,>(v: T): Promise<T> => Promise.resolve(v);
const fail = (msg: string): Promise<never> => Promise.reject(new Error(msg));
const STOP = new Set("a an and are as at be but by for from have how i in into is it me my of on or so that the this to want what with you your about book books read reading like some something learn".split(" "));
const words = (t: string) => t.toLowerCase().split(/[^a-z0-9]+/).filter((w) => w.length > 2 && !STOP.has(w));

function protoDiscover(text: string, filters: string[], offset: number, limit: number): DiscoverResponse {
  const q = words(text);
  const fs = filters.map((f) => f.split(":"));
  let rows = (P.catalogue as any[])
    .map((e) => {
      const hay = `${e.title} ${e.author} ${e.category} ${(e.subjects || []).join(" ")} ${e.why}`.toLowerCase();
      const head = `${e.title} ${e.category} ${(e.subjects || []).join(" ")}`.toLowerCase();
      const score = q.reduce((n, w) => n + (hay.includes(w) ? 1 : 0) + (head.includes(w) ? 1 : 0), 0);
      return { e, score };
    })
    .filter((x) => x.score > 0)
    .filter(({ e }) => fs.every(([k, v]) => (k === "level" ? e.level <= +v : k === "hours" ? e.hours <= +v : k === "category" ? e.category === v : k === "branch" ? e.available_at.length > 0 : true)))
    .sort((a, b) => b.score - a.score || +b.e.is_target - +a.e.is_target);
  const top = rows[0]?.score || 1;
  const total = rows.length;
  rows = rows.slice(offset, offset + limit);
  return {
    need: { summary: "Prototype search: simple keyword match over the embedded demo catalogue (no AI).", topics: q.slice(0, 4) },
    chips: [],
    results: rows.map(({ e, score }) => ({ id: e.id, line_id: e.line_id, is_target: e.is_target, title: e.title, author: e.author, category: e.category, level: e.level, hours: e.hours, why: e.why, fit: Math.min(1, score / top), status: e.status, available_at: e.available_at, hot_at: e.hot_at, before_count: e.before_count })),
    engine: "prototype-keyword",
    total,
    offset,
    limit,
    has_more: offset + limit < total,
  };
}

const proto = {
  mode: () => wait({ ...P.mode, prototype: true }),
  setMode: () => wait({ ...P.mode, prototype: true }),
  health: () => wait({ ok: true, mode: "prototype", cached_routes: Object.keys(P.routes).length }),
  resolve: (q: string, offset = 0, limit = 8) => {
    const ql = q.toLowerCase().trim();
    const hits = (P.index as ResolveHit[])
      .filter((e) => e.title.toLowerCase().includes(ql) || e.author.toLowerCase().includes(ql))
      .sort((a, b) => Number(!a.title.toLowerCase().startsWith(ql)) - Number(!b.title.toLowerCase().startsWith(ql)) || a.title.localeCompare(b.title));
    return wait({ results: hits.slice(offset, offset + limit), total: hits.length, offset, limit, has_more: offset + limit < hits.length });
  },
  route: (id: string) => (P.routes[id] ? wait(P.routes[id] as Route) : fail("Not in the prototype's embedded data. Run the repo locally for the full catalogue.")),
  similar: (id: string) => wait({ books: (P.similar[id] || []) as Neighbour[] }),
  branches: () => wait({ branches: P.branches as Branch[] }),
  browse: (by: "author" | "category") => wait({ groups: P.browse[by] || [] }),
  browseBooks: (ids: string[]) => wait({ books: ids.map((i) => P.books[i]).filter(Boolean) }),
  targets: () => wait({ targets: P.targets }),
  popular: (limit = 12) => wait({ popular: (P.popular as any[]).slice(0, limit) }),
};
const offline = () => fail("Not available in the hosted prototype. Run the repo locally.");

export const api: typeof live = P
  ? {
      ...live,
      ...proto,
      discover: (text, _branch, filters, offset = 0, limit = 10) => wait(protoDiscover(text, filters, offset, limit)),
      chat: offline,
      ask: offline,
      scan: offline,
    }
  : live;
