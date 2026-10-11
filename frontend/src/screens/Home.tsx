import { useEffect, useRef, useState } from "react";
import { api } from "../api";
import Cover from "../components/Cover";
import Discover from "../components/Discover";
import SettingsSheet from "../components/SettingsSheet";
import LanguagePicker from "../components/LanguagePicker";
import { t, tn, useLang, type Key } from "../i18n";
import { navigate } from "../router";
import { listHearts, noteCount, pathsInProgress, readSetFrom, useStoreVersion } from "../myshelf";
import type { ResolveHit } from "../types";

interface Target {
  id: string;
  title: string;
  author: string;
  unfinished?: boolean;
}

interface Popular extends Target {
  category: string;
  hot_at: string[];
  queue: number;
  demo: boolean;
  /** "api" (NLB checkout trends), "nlb-dataset" (open data) or "demo". */
  source?: string;
}

/** All-of-NLB annual aggregates from the open dataset (never per title). */
interface NlbFacts {
  year: number;
  physical_loans: number;
  digital_usage?: number | null;
  dataset?: string;
}

interface PopularMeta {
  source?: string;
  dataset?: string;
  year?: number;
  facts?: NlbFacts | null;
}

const millions = (n?: number | null) => (n ? (n / 1e6).toFixed(1) : "0");

type Mode = "ask" | "title" | "scan";

const MODES: { id: Mode; label: Key; icon: string }[] = [
  { id: "ask", label: "home.tab.ask", icon: "✨" },
  { id: "title", label: "home.tab.title", icon: "✎" },
  { id: "scan", label: "home.tab.scan", icon: "📷" },
];

export default function Home({ senior, onSenior }: { senior: boolean; onSenior: () => void }) {
  useLang();
  const [mode, setMode] = useState<Mode>("ask");
  const [resetKey, setResetKey] = useState(0);
  const [settings, setSettings] = useState(false);
  const [modeLabel, setModeLabel] = useState<Key | "">("");
  useEffect(() => {
    api.mode().then((m) => setModeLabel(m.prototype ? "home.mode.prototype" : m.demo ? "home.mode.demo" : "home.mode.real")).catch(() => setModeLabel(""));
  }, [settings]);
  const startOver = () => {
    setMode("ask");
    setQ("");
    setHits([]);
    setError("");
    setResetKey((k) => k + 1);
    window.scrollTo({ top: 0 });
  };
  const [q, setQ] = useState("");
  const [hits, setHits] = useState<ResolveHit[]>([]);
  const [hitsMeta, setHitsMeta] = useState<{ total: number; has_more: boolean; offset: number; limit: number }>({ total: 0, has_more: false, offset: 0, limit: 8 });
  const [targets, setTargets] = useState<Target[]>([]);
  const [popular, setPopular] = useState<Popular[]>([]);
  const [popularMeta, setPopularMeta] = useState<PopularMeta>({});
  const [showAllPopular, setShowAllPopular] = useState(false);
  const [showAllUnfinished, setShowAllUnfinished] = useState(false);
  const [error, setError] = useState("");
  const [scanning, setScanning] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);
  const uploadRef = useRef<HTMLInputElement>(null);
  const timer = useRef<number | undefined>(undefined);

  useEffect(() => {
    api.targets().then((r) => setTargets(r.targets)).catch(() => setTargets([]));
    api
      .popular(12)
      .then((r) => {
        setPopular(r.popular);
        setPopularMeta(r as unknown as PopularMeta);
      })
      .catch(() => setPopular([]));
  }, []);

  useEffect(() => {
    window.clearTimeout(timer.current);
    if (mode !== "title" || q.trim().length < 2) {
      setHits([]);
      return;
    }
    timer.current = window.setTimeout(() => {
      api
        .resolve(q.trim(), 0, 8)
        .then((r) => {
          setHits(r.results);
          setHitsMeta({ total: r.total, has_more: r.has_more, offset: r.offset, limit: r.limit });
        })
        .catch(() => setHits([]));
    }, 160);
    return () => window.clearTimeout(timer.current);
  }, [q, mode]);

  const go = (id: string, title: string, author: string) => navigate("line", { id, title, author });

  const onScan = async (file: File | undefined) => {
    if (!file) return;
    setScanning(true);
    setError("");
    try {
      const res = await api.scan(file);
      const r = await api.resolve(res.title);
      if (r.results.length) go(r.results[0].id, r.results[0].title, r.results[0].author);
      else setError(t("home.scanMiss", { title: res.title }));
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setScanning(false);
      if (fileRef.current) fileRef.current.value = "";
      if (uploadRef.current) uploadRef.current.value = "";
    }
  };

  useStoreVersion();
  const hearts = listHearts();
  const paths = pathsInProgress(readSetFrom()).filter((p) => p.total > 0).slice(0, 6);

  const asBook = (t: Target) => ({ id: t.id, title: t.title, author: t.author, subjects: [], summary: "", source: "seed" });

  const BookList = ({ books }: { books: Target[] }) => (
    <ul className="results" role="listbox" aria-label={t("home.books")}>
      {books.map((b) => (
        <li key={b.id} role="option" aria-selected={false}>
          <button type="button" onClick={() => go(b.id, b.title, b.author)}>
            <Cover book={asBook(b)} size="s" />
            <span className="result-text">
              <strong>{b.title}</strong>
              <span className="by">{b.author}</span>
            </span>
            <span className="chev" aria-hidden="true">›</span>
          </button>
        </li>
      ))}
    </ul>
  );

  return (
    <main className="screen home">
      <header className="home-head">
        <h1 className="wordmark">
          <button type="button" className="wordmark-btn" onClick={startOver} title={t("common.startOver")}>
            PreReads
          </button>
          <small>{t("app.tagline")}</small>
        </h1>
        <span className="head-actions">
          <button type="button" className="mode-chip" onClick={() => setSettings(true)} aria-haspopup="dialog" title={t("home.dataMode")}>
            ⚙️ {t(modeLabel || "home.settings")}
          </button>
          <LanguagePicker />
          <button type="button" className="senior-toggle" aria-pressed={senior} onClick={onSenior} title={t("home.senior")} aria-label={t("home.senior")}>
            Aa
          </button>
        </span>
      </header>
      <SettingsSheet open={settings} onClose={() => setSettings(false)} />

      <section className="hero">
        <h2 className="home-question">{t("home.question")}</h2>
        <p className="home-sub">{t("home.sub")}</p>

        <div className="modes" role="tablist" aria-label={t("home.modes")}>
          {MODES.map((m) => (
            <button key={m.id} type="button" role="tab" aria-selected={mode === m.id} className={`mode ${mode === m.id ? "on" : ""}`} onClick={() => setMode(m.id)}>
              <span aria-hidden="true">{m.icon}</span> {t(m.label)}
            </button>
          ))}
        </div>

        {mode === "ask" && (
          <div className="mode-panel">
            <Discover key={resetKey} />
          </div>
        )}

        {mode === "title" && (
          <div className="mode-panel">
            <label className="big-action input-action">
              <span className="big-icon" aria-hidden="true">✎</span>
              <input value={q} onChange={(e) => setQ(e.target.value)} placeholder={t("home.typeTitle")} autoComplete="off" inputMode="search" aria-label={t("home.typeTitleLabel")} />
            </label>
            {hits.length > 0 && <BookList books={hits} />}
          </div>
        )}

        {mode === "scan" && (
          <div className="mode-panel scan-panel">
            <button type="button" className="big-action primary" onClick={() => fileRef.current?.click()} disabled={scanning}>
              <span className="big-icon" aria-hidden="true">📷</span>
              {scanning ? t("home.scanning") : t("home.scanCamera")}
            </button>
            <button type="button" className="big-action" onClick={() => uploadRef.current?.click()} disabled={scanning}>
              <span className="big-icon" aria-hidden="true">🖼️</span>
              {t("home.upload")}
            </button>
            <input ref={fileRef} type="file" accept="image/*" capture="environment" hidden onChange={(e) => onScan(e.target.files?.[0])} />
            <input ref={uploadRef} type="file" accept="image/*" hidden onChange={(e) => onScan(e.target.files?.[0])} />
            <p className="hint">{t("home.scanHint")}</p>
          </div>
        )}

        {error && (
          <p className="error" role="alert">
            {error}
          </p>
        )}
      </section>

      {(hearts.length > 0 || paths.length > 0) && (
        <section className="row-section my-shelf" aria-label={t("home.myShelf")}>
          <div className="row-head">
            <h3>♥ {t("home.myShelf")}</h3>
            <span className="hint">{t("home.savedHere")}</span>
          </div>
          {paths.length > 0 && (
            <ul className="my-paths">
              {paths.map((p) => {
                const notes = noteCount(p.before.map((b) => b.id).concat(p.id));
                return (
                  <li key={p.id}>
                    <button type="button" className="my-path" onClick={() => go(p.id, p.title, p.author)}>
                      <strong>{p.title}</strong>
                      <span className="hint">
                        {p.done === p.total ? t("home.pathDone") : t("home.pathProgress", { done: p.done, total: p.total, hours: p.hoursLeft })}
                        {notes > 0 ? tn("home.notes", notes) : ""}
                      </span>
                      <span className="my-bar" aria-hidden="true"><i style={{ width: `${(p.done / p.total) * 100}%` }} /></span>
                    </button>
                  </li>
                );
              })}
            </ul>
          )}
          {hearts.length > 0 && (
            <div className="book-row" role="list">
              {hearts.map((h) => (
                <button key={h.id} type="button" className="row-item" role="listitem" onClick={() => navigate("book", { id: h.lineId, title: h.lineTitle, author: h.lineAuthor, stop: h.id })}>
                  <Cover book={asBook(h)} size="m" />
                  <span className="row-title">{h.title}</span>
                  <span className="row-badge heart-badge">{t("home.saved")}</span>
                </button>
              ))}
            </div>
          )}
        </section>
      )}

      {popular.length > 0 && (
        <section className="row-section">
          <div className="row-head">
            <h3>🔥 {t("home.popular")}</h3>
            <span className="hint">
              {popularMeta.source === "nlb-dataset" && popularMeta.dataset
                ? t("home.popularFrom", { dataset: popularMeta.dataset, year: String(popularMeta.year ?? "") })
                : <>{t("home.popularHint")}{popular[0]?.demo ? t("home.demoData") : ""}</>}
            </span>
            {popular.length > 6 && (
              <button type="button" className="link-btn inline" onClick={() => setShowAllPopular((v) => !v)}>
                {showAllPopular ? t("home.showFewer") : t("home.seeAll", { n: popular.length })}
              </button>
            )}
          </div>
          {popularMeta.facts && (
            <p className="hint">
              {t("home.nlbFacts", { year: String(popularMeta.facts.year), loans: millions(popularMeta.facts.physical_loans), digital: millions(popularMeta.facts.digital_usage) })}
            </p>
          )}
          <div className={`book-row ${showAllPopular ? "grid" : ""}`} role="list">
            {(showAllPopular ? popular : popular.slice(0, 6)).map((b) => (
              <button key={b.id} type="button" className="row-item" role="listitem" onClick={() => go(b.id, b.title, b.author)}>
                <Cover book={asBook(b)} size="m" />
                <span className="row-title">{b.title}</span>
                {b.hot_at[0] && <span className="row-badge">{t("home.hotAt", { branch: b.hot_at[0] })}</span>}
              </button>
            ))}
          </div>
        </section>
      )}

      {targets.some((t) => t.unfinished) && (
        <section className="row-section">
          <div className="row-head">
            <h3>📚 {t("home.unfinished")}</h3>
            <span className="hint">{t("home.unfinishedHint")}</span>
            {targets.filter((t) => t.unfinished).length > 6 && (
              <button type="button" className="link-btn inline" onClick={() => setShowAllUnfinished((v) => !v)}>
                {showAllUnfinished ? t("home.showFewer") : t("home.seeAll", { n: targets.filter((x) => x.unfinished).length })}
              </button>
            )}
          </div>
          <div className={`book-row ${showAllUnfinished ? "grid" : ""}`} role="list">
            {(showAllUnfinished ? targets.filter((t) => t.unfinished) : targets.filter((t) => t.unfinished).slice(0, 6)).map((t) => (
              <button key={t.id} type="button" className="row-item" role="listitem" onClick={() => go(t.id, t.title, t.author)}>
                <Cover book={asBook(t)} size="m" />
                <span className="row-title">{t.title}</span>
              </button>
            ))}
          </div>
        </section>
      )}

      <footer className="footer">{t("home.footer")}</footer>
    </main>
  );
}
