import { t } from "./i18n";
import type { Stop } from "./types";

/** Dewey class (first three digits) of a call number such as "English 153.4 KAH" or "332.024 TAN". */
export function deweyClass(callNumber: string | undefined | null): string | null {
  const m = /(?:^|[^\d])(\d{3})(?:\.\d+)?(?:[^\d]|$)/.exec(callNumber ?? "");
  return m ? m[1] : null;
}

export interface ShelfGroup {
  dewey: string;
  stops: Stop[];
}

/** Unread PreReads with a copy on the shelf at the chosen branch, grouped by Dewey class.
 *  Only groups of two or more come back, largest first. */
export function sameShelfGroups(stops: Stop[], branchCode: string, branchName: string | undefined, read: Set<string>): ShelfGroup[] {
  if (!branchCode) return [];
  const by = new Map<string, Stop[]>();
  for (const s of stops) {
    if (s.role !== "before" || read.has(s.book.id)) continue;
    const a = s.availability.find((x) => x.branch_code === branchCode || x.branch === branchName);
    if (!a || a.available <= 0) continue;
    const d = deweyClass(a.call_number);
    if (!d) continue;
    by.set(d, [...(by.get(d) ?? []), s]);
  }
  return [...by.entries()]
    .filter(([, v]) => v.length >= 2)
    .map(([dewey, v]) => ({ dewey, stops: v }))
    .sort((a, b) => b.stops.length - a.stops.length || a.dewey.localeCompare(b.dewey));
}

export function sameShelfText(g: ShelfGroup): string {
  return t("trip.sameShelf", { n: g.stops.length, dewey: g.dewey });
}
