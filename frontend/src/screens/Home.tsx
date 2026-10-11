import { useEffect, useRef, useState } from "react";
import { api } from "../api";
import Cover from "../components/Cover";
import Discover from "../components/Discover";
import SettingsSheet from "../components/SettingsSheet";
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
}

type Mode = "ask" | "title" | "scan";

const MODES: { id: Mode; label: string; icon: string }[] = [
  { id: "ask", label: "Tell me what you want", icon: "✨" },
  { id: "title", label: "I know the title", icon: "✎" },
  { id: "scan", label: "Scan or upload a cover", icon: "📷" },
];

export default function Home({ senior, onSenior }: { senior: boolean; onSenior: () => void }) {
  const [mode, setMode] = useState<Mode>("ask");
  const [resetKey, setResetKey] = useState(0);
  const [settings, setSettings] = useState(false);
  const [modeLabel, setModeLabel] = useState("");
  useEffect(() => {
    api.mode().then((m) => setModeLabel(m.prototype ? "Prototype" : m.demo ? "Demo data" : "Real calls")).catch(() => setModeLabel(""));
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
  const [showAllPopular, setShowAllPopular] = useState(false);
  const [showAllUnfinished, setShowAllUnfinished] = useState(false);
  const [error, setError] = useState("");
  const [scanning, setScanning] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);
  const uploadRef = useRef<HTMLInputElement>(null);
  const timer = useRef<number | undefined>(undefined);

  useEffect(() => {
    api.targets().then((r) => setTargets(r.targets)).catch(() => setTargets([]));
    api.popular(12).then((r) => setPopular(r.popular)).catch(() => setPopular([]));
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
      else setError(`Read "${res.title}" from the cover, but it isn't in the catalogue yet. Try typing it.`);
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
    <ul className="results" role="listbox" aria-label="Books">
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
          <button type="button" className="wordmark-btn" onClick={startOver} title="Start from the beginning">
            PreReads
          </button>
          <small>Book recommendations, and what to read before the book you want.</small>
        </h1>
        <span className="head-actions">
          <button type="button" className="mode-chip" onClick={() => setSettings(true)} aria-haspopup="dialog" title="Data mode">
            ⚙️ {modeLabel || "Settings"}
          </button>
          <button type="button" className="senior-toggle" aria-pressed={senior} onClick={onSenior} title="Larger text and controls">
            Aa
          </button>
        </span>
      </header>
      <SettingsSheet open={settings} onClose={() => setSettings(false)} />

      <section className="hero">
        <h2 className="home-question">Which book do you want to read?</h2>
        <p className="home-sub">Say what you want in your own words. PreReads reads it, picks the books, builds the filters, and shows what to read first and where it is on a shelf today.</p>

        <div className="modes" role="tablist" aria-label="Ways to find a book">
          {MODES.map((m) => (
            <button key={m.id} type="button" role="tab" aria-selected={mode === m.id} className={`mode ${mode === m.id ? "on" : ""}`} onClick={() => setMode(m.id)}>
              <span aria-hidden="true">{m.icon}</span> {m.label}
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
              <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Type a title…" autoComplete="off" inputMode="search" aria-label="Type the title" />
            </label>
            {hits.length > 0 && <BookList books={hits} />}
          </div>
        )}

        {mode === "scan" && (
          <div className="mode-panel scan-panel">
            <button type="button" className="big-action primary" onClick={() => fileRef.current?.click()} disabled={scanning}>
              <span className="big-icon" aria-hidden="true">📷</span>
              {scanning ? "Reading the cover…" : "Scan the cover with your camera"}
            </button>
            <button type="button" className="big-action" onClick={() => uploadRef.current?.click()} disabled={scanning}>
              <span className="big-icon" aria-hidden="true">🖼️</span>
              Upload a photo of the cover
            </button>
            <input ref={fileRef} type="file" accept="image/*" capture="environment" hidden onChange={(e) => onScan(e.target.files?.[0])} />
            <input ref={uploadRef} type="file" accept="image/*" hidden onChange={(e) => onScan(e.target.files?.[0])} />
            <p className="hint">Works best on the front cover in good light. Spines work too.</p>
          </div>
        )}

        {error && (
          <p className="error" role="alert">
            {error}
          </p>
        )}
      </section>

      {(hearts.length > 0 || paths.length > 0) && (
        <section className="row-section my-shelf" aria-label="My shelf">
          <div className="row-head">
            <h3>♥ My shelf</h3>
            <span className="hint">Saved on this device</span>
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
                        {p.done === p.total ? "PreReads done — ready for the book" : `${p.done} of ${p.total} PreReads read · about ${p.hoursLeft} h left`}
                        {notes > 0 ? ` · ${notes} ${notes === 1 ? "note" : "notes"}` : ""}
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
                  <span className="row-badge heart-badge">♥ Saved</span>
                </button>
              ))}
            </div>
          )}
        </section>
      )}

      {popular.length > 0 && (
        <section className="row-section">
          <div className="row-head">
            <h3>🔥 Popular right now</h3>
            <span className="hint">From checkout trends and waiting lists{popular[0]?.demo ? " (demo data)" : ""}</span>
            {popular.length > 6 && (
              <button type="button" className="link-btn inline" onClick={() => setShowAllPopular((v) => !v)}>
                {showAllPopular ? "Show fewer" : `See all ${popular.length}`}
              </button>
            )}
          </div>
          <div className={`book-row ${showAllPopular ? "grid" : ""}`} role="list">
            {(showAllPopular ? popular : popular.slice(0, 6)).map((t) => (
              <button key={t.id} type="button" className="row-item" role="listitem" onClick={() => go(t.id, t.title, t.author)}>
                <Cover book={asBook(t)} size="m" />
                <span className="row-title">{t.title}</span>
                {t.hot_at[0] && <span className="row-badge">Hot at {t.hot_at[0]}</span>}
              </button>
            ))}
          </div>
        </section>
      )}

      {targets.some((t) => t.unfinished) && (
        <section className="row-section">
          <div className="row-head">
            <h3>📚 Books people start and never finish</h3>
            <span className="hint">The ones a reading path helps most</span>
            {targets.filter((t) => t.unfinished).length > 6 && (
              <button type="button" className="link-btn inline" onClick={() => setShowAllUnfinished((v) => !v)}>
                {showAllUnfinished ? "Show fewer" : `See all ${targets.filter((t) => t.unfinished).length}`}
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

      <footer className="footer">Built on NLB Labs open APIs and Open Library. Not an NLB product.</footer>
    </main>
  );
}
