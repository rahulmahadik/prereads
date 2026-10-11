import { useEffect, useState } from "react";
import { speak, stop, subscribe, type SpeechState } from "../speech";

interface Props {
  id: string;
  text: () => string;          // lazily built narration
  label?: string;
  className?: string;
  lang?: string;
}

export default function ListenButton({ id, text, label = "Listen", className = "", lang = "en-SG" }: Props) {
  const [st, setSt] = useState<SpeechState>({ speaking: false, id: null, source: null });
  useEffect(() => subscribe(setSt), []);
  const active = st.speaking && st.id === id;
  return (
    <button
      type="button"
      className={`listen-btn ${active ? "on" : ""} ${className}`}
      onClick={() => (active ? stop() : speak(text(), id, lang))}
      aria-pressed={active}
      aria-label={active ? "Stop listening" : label}
      title={active ? "Stop" : label}
    >
      <span className="listen-icon" aria-hidden="true">
        {active ? "■" : "🔊"}
      </span>
      {active ? "Stop" : label}
      {active && <span className="listen-wave" aria-hidden="true"><i /><i /><i /></span>}
    </button>
  );
}
