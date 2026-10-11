import { useState } from "react";
import { LANGS, setLang, t, useLang } from "../i18n";
import { Sheet } from "./ui";

/** EN · 中文 · BM · தமிழ் as a 44px segmented control. Picking applies at once. */
export function LanguageSegments({ onPicked }: { onPicked?: () => void }) {
  const lang = useLang();
  return (
    <div className="lang-seg" role="radiogroup" aria-label={t("lang.title")}>
      {LANGS.map((l) => (
        <button
          key={l.id}
          type="button"
          role="radio"
          aria-checked={lang === l.id}
          lang={l.html}
          className={`lang-opt ${lang === l.id ? "on" : ""}`}
          title={l.name}
          onClick={() => {
            setLang(l.id);
            onPicked?.();
          }}
        >
          {l.short}
        </button>
      ))}
    </div>
  );
}

/** Compact pill for the Home header: shows the current language, opens a small sheet. */
export default function LanguagePicker() {
  const lang = useLang();
  const [open, setOpen] = useState(false);
  const cur = LANGS.find((l) => l.id === lang)!;
  return (
    <>
      <button type="button" className="lang-pill" onClick={() => setOpen(true)} aria-haspopup="dialog" aria-label={`${t("lang.pick")}: ${cur.name}`} title={t("lang.pick")}>
        <span aria-hidden="true">🌐</span> <span lang={cur.html}>{cur.short}</span>
      </button>
      <Sheet open={open} title={t("lang.title")} onClose={() => setOpen(false)}>
        <div className="lang-list" role="radiogroup" aria-label={t("lang.title")}>
          {LANGS.map((l) => (
            <button
              key={l.id}
              type="button"
              role="radio"
              aria-checked={lang === l.id}
              lang={l.html}
              className={`choice lang-choice ${lang === l.id ? "on" : ""}`}
              onClick={() => {
                setLang(l.id);
                setOpen(false);
              }}
            >
              <strong>{l.name}</strong>
              <span>{l.short}</span>
            </button>
          ))}
        </div>
        <p className="hint">{t("lang.hint")}</p>
      </Sheet>
    </>
  );
}
