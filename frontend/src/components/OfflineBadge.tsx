import { useEffect, useState } from "react";
import { t, useLang } from "../i18n";

export default function OfflineBadge() {
  useLang();
  const [online, setOnline] = useState(() => (typeof navigator === "undefined" ? true : navigator.onLine));
  useEffect(() => {
    const on = () => setOnline(true);
    const off = () => setOnline(false);
    window.addEventListener("online", on);
    window.addEventListener("offline", off);
    return () => {
      window.removeEventListener("online", on);
      window.removeEventListener("offline", off);
    };
  }, []);
  return (
    <div className="offline-badge-wrap" aria-live="polite">
      {!online && <span className="offline-badge">{t("offline.badge")}</span>}
    </div>
  );
}
