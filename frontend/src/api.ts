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

export const api = {
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
  chat: (text: string, state: unknown) =>
    fetch(url("/api/chat"), { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ text, state }) }).then((r) =>
      json<{ messages: string[]; options: { label: string; value: string }[]; state: { step: string }; result?: { book_id: string; title: string; author: string; level: number; branch: string; start_id: string; start_title: string; start_status: string } | null }>(r),
    ),
  discover: (text: string, branch: string, filters: string[], offset = 0, limit = 10) =>
    fetch(url("/api/discover"), { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ text, branch: branch || null, filters, offset, limit }) }).then((r) =>
      json<DiscoverResponse>(r),
    ),
  targets: () => fetch(url("/api/targets")).then((r) => json<{ targets: { id: string; title: string; author: string; unfinished?: boolean }[] }>(r)),
  popular: (limit = 12) => fetch(url(`/api/popular?limit=${limit}`)).then((r) => json<{ popular: { id: string; title: string; author: string; category: string; hot_at: string[]; queue: number; score: number; demo: boolean }[] }>(r)),
  ask: (target_id: string, intent: "why_before" | "time_budget" | "large_print", weeks?: number) =>
    fetch(url("/api/ask"), {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ target_id, intent, weeks }),
    }).then((r) => json<AskResponse>(r)),
  scan: (file: File) => {
    const fd = new FormData();
    fd.append("image", file);
    return fetch(url("/api/scan"), { method: "POST", body: fd }).then((r) =>
      json<{ title: string; author: string; isbn?: string | null; confidence: number }>(r),
    );
  },
};
