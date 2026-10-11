import { useEffect, useState } from "react";
import { t, useLang } from "../i18n";

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

  return (
    <div className="reader" role="dialog" aria-modal="true" aria-label={c?.title || t("dig.readHere")}>
      <div className="reader-bar">
        <span className="reader-progress">
          {c ? t("reader.progress", { c: c.chapter_title, m: c.minutes ?? 1 }) : failed ? "" : t("reader.loading")}
        </span>
        <button type="button" className="icon-btn" onClick={onClose} aria-label={t("common.close")}>
          ✕
        </button>
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
    </div>
  );
}
