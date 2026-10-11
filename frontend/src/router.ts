import { useEffect, useState } from "react";

export type Screen = "home" | "ready" | "line" | "book";

export interface Location {
  screen: Screen;
  params: Record<string, string>;
}

function parse(hash: string): Location {
  const raw = hash.replace(/^#\/?/, "");
  const [path, query = ""] = raw.split("?");
  const params: Record<string, string> = {};
  new URLSearchParams(query).forEach((v, k) => (params[k] = v));
  const screen = (["home", "ready", "line", "book"].includes(path) ? path : "home") as Screen;
  return { screen, params };
}

export function href(screen: Screen, params: Record<string, string | number | undefined> = {}): string {
  const q = new URLSearchParams();
  Object.entries(params).forEach(([k, v]) => v !== undefined && v !== "" && q.set(k, String(v)));
  const qs = q.toString();
  return `#/${screen}${qs ? `?${qs}` : ""}`;
}

export function navigate(screen: Screen, params: Record<string, string | number | undefined> = {}, replace = false) {
  const h = href(screen, params);
  if (replace) history.replaceState(null, "", h);
  else location.hash = h;
  if (replace) window.dispatchEvent(new HashChangeEvent("hashchange"));
}

export function back(fallback: Screen = "home") {
  if (history.length > 1) history.back();
  else navigate(fallback);
}

export function useLocation(): Location {
  const [loc, setLoc] = useState<Location>(() => parse(location.hash));
  useEffect(() => {
    const on = () => setLoc(parse(location.hash));
    window.addEventListener("hashchange", on);
    return () => window.removeEventListener("hashchange", on);
  }, []);
  return loc;
}
