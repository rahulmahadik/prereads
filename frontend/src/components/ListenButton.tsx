import { useEffect, useState } from "react";
import { speak, stop, subscribe, type SpeechState } from "../speech";
import { t, useLang, voiceLang } from "../i18n";

interface Props {
  id: string;
  text: () => string;          // lazily built narration
  label?: string;
  className?: string;
  lang?: string;
}

export default function ListenButton({ id, text, label, className = "", lang }: Props) {
  const ui = useLang();
  const name = label ?? t("listen.label");
  const [st, setSt] = useState<SpeechState>({ speaking: false, id: null, source: null });
  useEffect(() => subscribe(setSt), []);
  const active = st.speaking && st.id === id;
  return (
    <button
      type="button"
      className={`listen-btn ${active ? "on" : ""} ${className}`}
      onClick={() => (active ? stop() : speak(text(), id, lang ?? voiceLang(ui)))}
      aria-pressed={active}
      aria-label={active ? t("listen.stopAria") : name}
      title={active ? t("listen.stop") : name}
    >
      <span className="listen-icon" aria-hidden="true">
        {active ? "■" : "🔊"}
      </span>
      {active ? t("listen.stop") : name}
      {active && <span className="listen-wave" aria-hidden="true"><i /><i /><i /></span>}
    </button>
  );
}
