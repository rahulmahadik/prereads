import { useState } from "react";
import { clockLabel, formatKm, openState, sortByDistance } from "../geo";
import { t, useLang } from "../i18n";
import type { Branch } from "../types";

type Status = "idle" | "locating" | "denied" | "unavailable" | "ready";

const shortName = (n: string) => n.replace(/\s+(Regional|Public)?\s*Library$/i, "").trim() || n;

export default function NearestLibraries({ branches, onPick }: { branches: Branch[]; onPick: (code: string) => void }) {
  const lang = useLang();
  const [status, setStatus] = useState<Status>("idle");
  const [nearest, setNearest] = useState<ReturnType<typeof sortByDistance>>([]);

  const locate = () => {
    if (!navigator.geolocation) {
      setStatus("unavailable");
      return;
    }
    setStatus("locating");
    navigator.geolocation.getCurrentPosition(
      (pos) => {
        setNearest(sortByDistance(branches, pos.coords.latitude, pos.coords.longitude).slice(0, 5));
        setStatus("ready");
      },
      (err) => setStatus(err.code === err.PERMISSION_DENIED ? "denied" : "unavailable"),
      { enableHighAccuracy: false, timeout: 10000, maximumAge: 60000 },
    );
  };

  const now = new Date();
  return (
    <div className="nearest">
      <button type="button" className="btn nearest-btn" onClick={locate} disabled={status === "locating"}>
        {status === "locating" ? t("near.locating") : t("near.use")}
      </button>
      {status === "denied" && <p className="hint">{t("near.denied")}</p>}
      {status === "unavailable" && <p className="hint">{t("near.unavailable")}</p>}
      {status === "ready" && nearest.length === 0 && <p className="hint">{t("near.none")}</p>}
      {status === "ready" && nearest.length > 0 && (
        <>
          <ul className="nearest-list">
            {nearest.map((b) => {
              const s = openState(b.hours, now);
              // 24-hour times outside English ("21:00"); "9pm" in English, as geo.ts writes it.
              const clock = (hhmm: string) => (lang === "en" ? clockLabel(hhmm) : hhmm);
              const label = !b.hours ? t("near.noHours") : s.open ? t("near.open", { time: clock(b.hours.close) }) : t("near.closed", { time: clock(b.hours.open) });
              return (
                <li key={b.code}>
                  <button type="button" className="nearest-item" onClick={() => onPick(b.code)}>
                    <span className="nearest-name">{shortName(b.name)}</span>
                    <span className="nearest-meta">
                      {formatKm(b.km)} · <span className={s.open ? "nearest-open" : "nearest-closed"}>{label}</span>
                    </span>
                  </button>
                </li>
              );
            })}
          </ul>
          <p className="hint">{t("near.typical")}</p>
        </>
      )}
    </div>
  );
}
