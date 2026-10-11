import type { Branch } from "./types";

export interface Hours {
  open: string; // "10:00", Singapore time
  close: string; // "21:00"
}

export interface OpenState {
  open: boolean;
  label: string;
}

export type WithDistance<T> = T & { km: number };

const R_KM = 6371;
const rad = (d: number) => (d * Math.PI) / 180;

/** Great-circle distance in km. */
export function haversineKm(lat1: number, lng1: number, lat2: number, lng2: number): number {
  const dLat = rad(lat2 - lat1);
  const dLng = rad(lng2 - lng1);
  const a = Math.sin(dLat / 2) ** 2 + Math.cos(rad(lat1)) * Math.cos(rad(lat2)) * Math.sin(dLng / 2) ** 2;
  return 2 * R_KM * Math.asin(Math.min(1, Math.sqrt(a)));
}

const toMinutes = (hhmm: string): number => {
  const [h, m] = hhmm.split(":").map(Number);
  return h * 60 + (m || 0);
};

/** "21:00" -> "9pm", "10:30" -> "10:30am". */
export function clockLabel(hhmm: string): string {
  const [h, m] = hhmm.split(":").map(Number);
  const suffix = h >= 12 && h < 24 ? "pm" : "am";
  const h12 = h % 12 === 0 ? 12 : h % 12;
  return m ? `${h12}:${String(m).padStart(2, "0")}${suffix}` : `${h12}${suffix}`;
}

/** Minutes since midnight in Singapore time. */
function sgMinutes(now: Date): number {
  const parts = new Intl.DateTimeFormat("en-GB", { timeZone: "Asia/Singapore", hour: "2-digit", minute: "2-digit", hourCycle: "h23" }).formatToParts(now);
  const get = (t: string) => Number(parts.find((p) => p.type === t)?.value ?? 0);
  return get("hour") * 60 + get("minute");
}

export function openState(hours: Hours | undefined | null, now: Date): OpenState {
  if (!hours) return { open: false, label: "Hours not listed" };
  const t = sgMinutes(now);
  const o = toMinutes(hours.open);
  const c = toMinutes(hours.close);
  if (t >= o && t < c) return { open: true, label: `Open now · closes ${clockLabel(hours.close)}` };
  return { open: false, label: `Closed · opens ${clockLabel(hours.open)}` };
}

/** Branches that have coordinates, nearest first, with km attached. */
export function sortByDistance(branches: Branch[], lat: number, lng: number): WithDistance<Branch>[] {
  return branches
    .filter((b): b is Branch & { lat: number; lng: number } => typeof b.lat === "number" && typeof b.lng === "number")
    .map((b) => ({ ...b, km: haversineKm(lat, lng, b.lat, b.lng) }))
    .sort((a, b) => a.km - b.km);
}

export function formatKm(km: number): string {
  return km < 10 ? `${km.toFixed(1)} km` : `${Math.round(km)} km`;
}
