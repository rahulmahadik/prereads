import { useState } from "react";
import { formatKm, openState, sortByDistance } from "../geo";
import type { Branch } from "../types";

type Status = "idle" | "locating" | "denied" | "unavailable" | "ready";

const shortName = (n: string) => n.replace(/\s+(Regional|Public)?\s*Library$/i, "").trim() || n;

export default function NearestLibraries({ branches, onPick }: { branches: Branch[]; onPick: (code: string) => void }) {
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
        {status === "locating" ? "Finding your location…" : "Use my location"}
      </button>
      {status === "denied" && <p className="hint">Location is turned off for this site. You can still pick a library from the list.</p>}
      {status === "unavailable" && <p className="hint">Couldn't get your location. You can still pick a library from the list.</p>}
      {status === "ready" && nearest.length === 0 && <p className="hint">No library locations are available to compare yet.</p>}
      {status === "ready" && nearest.length > 0 && (
        <>
          <ul className="nearest-list">
            {nearest.map((b) => {
              const s = openState(b.hours, now);
              return (
                <li key={b.code}>
                  <button type="button" className="nearest-item" onClick={() => onPick(b.code)}>
                    <span className="nearest-name">{shortName(b.name)}</span>
                    <span className="nearest-meta">
                      {formatKm(b.km)} · <span className={s.open ? "nearest-open" : "nearest-closed"}>{s.label}</span>
                    </span>
                  </button>
                </li>
              );
            })}
          </ul>
          <p className="hint">Typical hours, check NLB.</p>
        </>
      )}
    </div>
  );
}
