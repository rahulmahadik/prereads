import { useEffect, useState } from "react";
import { createPortal } from "react-dom";
import { t, useLang, type Key } from "../i18n";
import { THEME_ICON, nextTheme, setTheme, useAppearance, type Resolved } from "../theme";

const THEME_NAME: Record<Resolved, Key> = { light: "look.light", dark: "look.dark", sepia: "look.sepia" };
const FONT_KEY = "prereads.readerFont";
const readFont = (): "serif" | "sans" => {
  try {
    return localStorage.getItem(FONT_KEY) === "sans" ? "sans" : "serif";
  } catch {
    return "serif";
  }
};

type Chapter = {
  title: string;
  chapter_title: string;
  paragraphs: string[];
  minutes?: number;
  source_url: string;
};

/** Full-screen reading sheet for the first chapter of a public-domain Project Gutenberg book. */
export default function SampleReader({ gutenbergId, onClose }: { gutenbergId: number; onClose: () => void }) {
  useLang();
  const look = useAppearance();
  // The reader is an e-reader page: Serif by default, its own Aa toggle, the same theme as the app.
  const [font, setFont] = useState(readFont);
  const toggleFont = () => {
    const next = font === "serif" ? "sans" : "serif";
    setFont(next);
    try {
      localStorage.setItem(FONT_KEY, next);
    } catch {
      /* storage blocked: applies for this visit */
    }
  };
  const [c, setC] = useState<Chapter | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let off = false;
    fetch(`/api/online/chapter?gutenberg_id=${gutenbergId}`)
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error("no chapter"))))
      .then((j) => !off && setC(j))
      .catch(() => !off && setFailed(true));
    return () => {
      off = true;
    };
  }, [gutenbergId]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    document.body.style.overflow = "hidden";
    return () => {
      window.removeEventListener("keydown", onKey);
      document.body.style.overflow = "";
    };
  }, [onClose]);

  // Portal to <body>: the book card is transformed (page-turn animation), which would trap a fixed overlay inside it.
  return createPortal(
    <div className="reader" data-reader-font={font} role="dialog" aria-modal="true" aria-label={c?.title || t("dig.readHere")}>
      <div className="reader-bar">
        <span className="reader-progress">
          {c ? t("reader.progress", { c: c.chapter_title, m: c.minutes ?? 1 }) : failed ? "" : t("reader.loading")}
        </span>
        <span className="reader-tools">
          <button type="button" className="icon-btn reader-aa" onClick={toggleFont} aria-label={t("reader.font")} title={t("reader.font")}
                  aria-pressed={font === "sans"}>
            Aa
          </button>
          <button
            type="button"
            className="theme-btn"
            onClick={() => setTheme(nextTheme(look.resolved))}
            aria-label={t("look.switch", { name: t(THEME_NAME[look.resolved]), next: t(THEME_NAME[nextTheme(look.resolved)]) })}
            title={t("look.switch", { name: t(THEME_NAME[look.resolved]), next: t(THEME_NAME[nextTheme(look.resolved)]) })}
          >
            <span aria-hidden="true">{THEME_ICON[look.resolved]}</span>
          </button>
          <button type="button" className="icon-btn" onClick={onClose} aria-label={t("common.close")}>
            ✕
          </button>
        </span>
      </div>
      <article className="reader-page">
        {failed && <p className="hint">{t("reader.error")}</p>}
        {c && (
          <>
            <p className="reader-book">{c.title}</p>
            <h2>{c.chapter_title}</h2>
            {c.paragraphs.map((p, i) => (
              <p key={i}>{p}</p>
            ))}
          </>
        )}
        <footer className="reader-foot">
          <p>{t("reader.footer")}</p>
          <a className="link-btn" href={c?.source_url || `https://www.gutenberg.org/ebooks/${gutenbergId}`}
             target="_blank" rel="noreferrer">
            {t("reader.full")} ↗
          </a>
        </footer>
      </article>
    </div>,
    document.body,
  );
}
