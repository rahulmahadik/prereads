import { useEffect, useState } from "react";

export default function OfflineBadge() {
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
      {!online && <span className="offline-badge">Offline — showing paths saved on this device</span>}
    </div>
  );
}
