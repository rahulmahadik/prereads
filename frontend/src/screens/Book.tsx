import { useEffect, useState } from "react";
import Footer from "../components/Footer";
import { api } from "../api";
import Cover from "../components/Cover";
import ReadinessMeter from "../components/ReadinessMeter";
import { readingAge, type ReadingAge } from "../readingAge";
import ListenButton from "../components/ListenButton";
import { bookScript } from "../speech";
import WayfindMap from "../components/WayfindMap";
import { Sheet, TopBar, getBranch, nlbSearchUrl, scrollToShelf, shelfStatus, shortBranch, useBack, useReadSet } from "../components/ui";
import { navigate } from "../router";
import HeartButton from "../components/HeartButton";
import { getNote, setNote } from "../myshelf";
import DigitalCopies from "../components/DigitalCopies";
import SampleReader from "../components/SampleReader";
import { isHearted, toggleHeart, useStoreVersion } from "../myshelf";
import { cleanSummary } from "../summary";
import type { Neighbour, Route, Stop } from "../types";
import { rich, t, tn, useLang, voiceLang, type Key } from "../i18n";

/** readingAgeText() in the UI language: the label is keyed by its minimum age (8, 12, 13, 15, 18). */
const ageText = (a: ReadingAge) => {
  const key = `age.${a.min_age}` as Key;
  const label = ["age.8", "age.12", "age.13", "age.15", "age.18"].includes(key) ? t(key) : a.label;
  return label + (a.source === "estimated" ? t("age.estimated") : "");
};

export default function Book({ id, title, author, stopId, at }: { id: string; title: string; author: string; stopId: string; at?: string }) {
  const lang = useLang();
  const goBack = useBack("line");
  const [route, setRoute] = useState<Route | null>(null);
  const [error, setError] = useState("");
  const [ask, setAsk] = useState(false);
  const [access, setAccess] = useState<{ gid: number; sample?: string; readFree?: string; libby?: { url: string; available: number } } | null>(null);
  const [reading, setReading] = useState(false);
  useStoreVersion();
  const [answer, setAnswer] = useState("");
  const [busy, setBusy] = useState(false);
  const [weeks, setWeeks] = useState(2);
  const [readSet, toggleRead] = useReadSet();
  const [shownLibs, setShownLibs] = useState(0);   // 0 = collapsed (status block only)
  const branchPref = getBranch();
  const [similar, setSimilar] = useState<Neighbour[]>([]);
  const [note, setNoteText] = useState("");
  const [moreAbout, setMoreAbout] = useState(false);

  useEffect(() => {
    api
      .route(id, title, author)
      .then(setRoute)
      .catch((e) => setError((e as Error).message));
  }, [id, title, author]);

  const stops = route?.stops ?? [];
  // A shared or older link can name the path's target id while the target stop shows a different
  // (better) edition; fall back to the target stop so the page never stays on the skeleton.
  let idx = stops.findIndex((s) => s.book.id === stopId);
  if (idx < 0 && route) idx = stops.findIndex((s) => s.role === "target");
  const stop: Stop | undefined = stops[idx];
  const stopBookId = stop?.book.id;

  useEffect(() => {
    setNoteText(stopBookId ? getNote(stopBookId) : "");
  }, [stopBookId]);

  useEffect(() => {
    setAccess(null);
    if (!stop) return;
    let live = true;
    const q = new URLSearchParams({ title: stop.book.title, author: stop.book.author || "" });
    Promise.all([
      fetch(`/api/digital?${q}`).then((r) => (r.ok ? r.json() : {})).catch(() => ({})),
      fetch(`/api/online?${q}`).then((r) => (r.ok ? r.json() : {})).catch(() => ({})),
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
    ]).then(([d, o]: any[]) => {
      if (!live) return;
      const gid = Number(o?.gutenberg?.url?.match(/\/ebooks\/(\d+)/)?.[1]) || 0;
      setAccess({
        gid,
        sample: d?.ebook?.sample_url || undefined,
        readFree: o?.openlibrary?.access === "public" ? o.openlibrary.read_url : undefined,
        libby: d?.ebook ? { url: d.ebook.url, available: d.ebook.available } : undefined,
      });
    });
    return () => {
      live = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [stop?.book.id]);

  useEffect(() => {
    setSimilar([]);
    if (!stopBookId) return;
    let live = true;
    api
      .similar(stopBookId, branchPref)
      .then((r) => live && setSimilar(r.books))
      .catch(() => live && setSimilar([]));
    return () => {
      live = false;
    };
  }, [stopBookId, branchPref]);

  // "Directions" links (at=find) open the page at the shelf map once the page has rendered.
  useEffect(() => {
    if (at !== "find" || !stopBookId) return;
    const timer = window.setTimeout(scrollToShelf, 150);
    return () => window.clearTimeout(timer);
  }, [at, stopBookId]);

  const go = (i: number) => {
    const s = stops[i];
    if (s) navigate("book", { id, title, author, stop: s.book.id }, true);
  };

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "ArrowRight") go(idx + 1);
      if (e.key === "ArrowLeft") go(idx - 1);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [idx, stops.length]);

  const runAsk = async (intent: "why_before" | "time_budget" | "large_print") => {
    if (!route) return;
    setBusy(true);
    try {
      const r = await api.ask(route.target_id, intent, weeks);
      setAnswer(r.answer);
    } catch (e) {
      setAnswer((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  if (error)
    return (
      <main className="screen">
        <TopBar onBack={goBack} />
        <p className="error">{error}</p>
      </main>
    );
  if (!route || !stop)
    return (
      <main className="screen">
        <TopBar onBack={goBack} />
        <div className="skeleton">
          <div className="sk-book">
            <div className="sk-cover" />
            <div className="sk-lines">
              <span />
              <span />
              <span />
            </div>
          </div>
        </div>
      </main>
    );

  const { book, readiness, availability, demand } = stop;
  const sorted = [...availability].sort((a, b) => b.available - a.available || a.branch.localeCompare(b.branch));
  const inSomewhere = availability.some((a) => a.available > 0);
  const st = shelfStatus(stop, branchPref || undefined);
  const wayfind = st.kind === "available" || st.kind === "elsewhere" ? { callNumber: st.callNumber || "", branch: st.branch, code: st.code } : null;
  const narration = () =>
    bookScript({
      title: book.title, author: book.author, about: cleanSummary(book.summary),
      why: stop.role === "target" ? readiness.one_line || stop.why : stop.why,
    });
  const queue = demand.reservations ?? 0;
  const reserveLabel = st.kind === "waiting" || st.kind === "none" ? (queue ? t("book.waitlistQueue", { n: queue }) : t("book.waitlist")) : t("book.reserve");
  const read = readSet.has(book.id);
  const role = stop.role === "target" ? t("line.kicker.target") : stop.role === "before" ? t("line.kicker.before") : t("line.kicker.after");
  let startX: number | null = null;

  return (
    <main
      className="screen book-screen"
      onTouchStart={(e) => (startX = e.touches[0].clientX)}
      onTouchEnd={(e) => {
        if (startX === null) return;
        const dx = e.changedTouches[0].clientX - startX;
        startX = null;
        if (dx < -56) go(idx + 1);
        else if (dx > 56) go(idx - 1);
      }}
    >
      <TopBar
        onBack={goBack}
        title={t("book.pos", { role, i: idx + 1, n: stops.length })}
        right={
          <span className="pager">
            <button type="button" className="icon-btn" onClick={() => go(idx - 1)} disabled={idx <= 0} aria-label={t("book.prev")}>
              ‹
            </button>
            <button type="button" className="icon-btn" onClick={() => go(idx + 1)} disabled={idx >= stops.length - 1} aria-label={t("book.next")}>
              ›
            </button>
          </span>
        }
      />

      <article key={book.id} className="book turn-fwd">
        <div className="page page-left">
          <Cover book={book} size="l" level={readiness.level} />
          <div className="page-meta">
            <div className="title-row">
              <h1 className="book-title">{book.title}</h1>
              <ListenButton id={`book:${book.id}`} text={narration} label={t("book.listen")} lang={voiceLang(lang)} />
              <HeartButton book={{ id: book.id, title: book.title, author: book.author, lineId: id, lineTitle: title, lineAuthor: author, cover_url: book.cover_url }} />
            </div>
            <p className="book-author">
              {book.author}
              {book.year ? ` · ${book.year}` : ""}
              {book.pages ? t("book.pages", { n: book.pages }) : ""}
            </p>
            <ReadinessMeter level={readiness.level} hours={readiness.hours} />
            {stop.role !== "target" && (
              <button type="button" className={`mark-read ${read ? "on" : ""}`} onClick={() => toggleRead(book.id)} aria-pressed={read}>
                {read ? t("book.readIt") : t("book.markRead")}
              </button>
            )}
            <span className="age-chip">{ageText(readingAge(book.audience, book.subjects, readiness.level, book.pages))}</span>
          </div>
        </div>

        <div className="page page-right">
          {(() => {
            const about = cleanSummary(book.summary);
            const subjects = book.subjects.filter((x) => x.split(" ").length <= 4).slice(0, 5);
            if (!about && subjects.length === 0) return null;
            const long = about.length > 700;
            return (
              <section className="about" aria-label={t("book.about")}>
                <h3 className="small-h">{t("book.about")}</h3>
                {about && <p className={`about-text ${long && !moreAbout ? "clamped" : ""}`}>{about}</p>}
                {long && (
                  <button type="button" className="link-btn inline" onClick={() => setMoreAbout((v) => !v)} aria-expanded={moreAbout}>
                    {moreAbout ? t("common.showLess") : t("book.readMore")}
                  </button>
                )}
                {subjects.length > 0 && <p className="about-subjects">{subjects.join(" · ")}</p>}
                {about && <p className="hint about-src">{t("book.source", { src: t(book.source === "nlb" ? "book.src.nlb" : book.source === "openlibrary" ? "book.src.ol" : "book.src.seed") })}</p>}
              </section>
            );
          })()}
          <p className="why">{stop.role === "target" ? readiness.one_line || stop.why : stop.why}</p>
          {readiness.assumed_concepts.length > 0 && (
            <>
              <h3 className="small-h">{t("book.assumes")}</h3>
              <ul className="chips">
                {readiness.assumed_concepts.map((c, i) => (
                  <li key={c} style={{ animationDelay: `${120 + i * 50}ms` }}>
                    {c}
                  </li>
                ))}
              </ul>
            </>
          )}
          <h3 className="small-h where-h" id="where">{t("book.where")}</h3>
          {st.kind === "available" && (
            <div className="status ok">
              <strong>{t("book.availableAt", { branch: shortBranch(st.branch) })}</strong>
              <span className="call">{st.callNumber}</span>
              {st.others > 0 && <span className="hint">{tn("book.alsoIn", st.others)}</span>}
            </div>
          )}
          {st.kind === "elsewhere" && (
            <div className="status alt">
              <strong>{t("book.notHere", { here: shortBranch(st.here) })}</strong>
              <span className="hint">{t("book.nearest", { branch: shortBranch(st.branch), call: st.callNumber })}</span>
            </div>
          )}
          {st.kind === "waiting" && (
            <div className="status no">
              <strong>{t("book.allOut")}{demand.reservations ? t("book.inQueue", { n: demand.reservations }) : ""}</strong>
              <span className="hint">{t("book.waitHint")}</span>
            </div>
          )}
          {st.kind === "none" && (
            <div className="status no">
              <strong>{t("book.noCopies")}</strong>
              <span className="hint">{t("book.ebookHint")}</span>
            </div>
          )}
          {shownLibs > 0 && (
            <ul className="branch-list">
              {sorted.slice(0, shownLibs).map((a) => (
                <li key={a.branch}>
                  <span className="branch-name">
                    {shortBranch(a.branch)}
                    {a.call_number && <span className="call">{a.call_number}</span>}
                  </span>
                  {a.available > 0 ? <span className="in">{t("book.nIn", { n: a.available })}</span> : <span className="out">{t("book.allOutShort")}</span>}
                </li>
              ))}
            </ul>
          )}
          {availability.length > 1 && (
            <div className="more-row">
              {shownLibs < sorted.length && (
                <button type="button" className="link-btn inline" onClick={() => setShownLibs((n) => Math.min(sorted.length, n + 3))}>
                  {shownLibs === 0 ? t("book.otherLibs", { n: sorted.length }) : t("book.loadMore", { n: sorted.length - shownLibs })}
                </button>
              )}
              {shownLibs > 0 && (
                <button type="button" className="link-btn inline" onClick={() => setShownLibs(0)}>
                  {t("common.showLess")}
                </button>
              )}
            </div>
          )}
          <a className="reserve-link" href={nlbSearchUrl(book.title, book.isbn)} target="_blank" rel="noopener">
            {reserveLabel} ↗
          </a>

          <DigitalCopies title={book.title} author={book.author} />

          <label className="note-box">
            <span className="small-h">{t("book.myNote")}</span>
            <textarea
              value={note}
              rows={3}
              placeholder={t("book.notePlaceholder")}
              onChange={(e) => {
                setNoteText(e.target.value);
                setNote(book.id, e.target.value);
              }}
            />
          </label>
        </div>
      </article>

      {wayfind && wayfind.callNumber && (
        <section className="section wayfind-section" id="find">
          <h3 className="small-h">
            {t("book.findAt", { branch: shortBranch(wayfind.branch) })} <span className="hint">· {wayfind.callNumber}</span>
          </h3>
          <WayfindMap target={wayfind} />
        </section>
      )}

      {similar.length > 0 && (
        <section className="section similar-section" aria-label={t("book.because", { title: book.title })}>
          <h3 className="small-h">{t("book.because", { title: book.title })}</h3>
          <ul className="similar-list">
            {similar.map((n) => (
              <li key={n.id}>
                <button type="button" className="similar-item" onClick={() => navigate("book", { id: n.line_id, title: n.line_title, author: n.line_author, stop: n.id })}>
                  <strong>{n.title}</strong>
                  <span className="hint">{n.author}</span>
                  <span className="similar-why">{n.reason}</span>
                  <span className={`where ${n.status.startsWith("Available") ? "ok" : n.status.startsWith("Not") ? "alt" : "no"}`}>{n.status}</span>
                </button>
              </li>
            ))}
          </ul>
        </section>
      )}

      <div className="action-bar">
        {access?.gid ? (
          <button type="button" className="bar-btn primary" onClick={() => setReading(true)}>
            📖 {t("book.firstChapter")}
          </button>
        ) : access?.sample ? (
          <a className="bar-btn primary link-as-btn" href={access.sample} target="_blank" rel="noopener">
            📖 {t("book.sample")}
          </a>
        ) : access?.readFree ? (
          <a className="bar-btn primary link-as-btn" href={access.readFree} target="_blank" rel="noopener">
            📖 {t("book.readFree")}
          </a>
        ) : null}
        {access?.libby && access.libby.available > 0 ? (
          <a className="bar-btn link-as-btn" href={access.libby.url} target="_blank" rel="noopener">
            {t("book.borrowLibby")}
          </a>
        ) : (
          <a className="bar-btn link-as-btn" href={nlbSearchUrl(book.title, book.isbn)} target="_blank" rel="noopener">
            {inSomewhere ? t("book.reserve") : queue ? t("book.waitlistN", { n: queue }) : t("book.waitlist")}
          </a>
        )}
        <button type="button" className={`bar-btn ${isHearted(book.id) ? "on" : ""}`} aria-pressed={isHearted(book.id)} onClick={() => toggleHeart({ id: book.id, title: book.title, author: book.author, lineId: id, lineTitle: title, lineAuthor: author, cover_url: book.cover_url })}>
          {isHearted(book.id) ? `♥ ${t("book.saved")}` : `♡ ${t("book.save")}`}
        </button>
      </div>
      {reading && access?.gid ? <SampleReader gutenbergId={access.gid} onClose={() => setReading(false)} /> : null}
      <Footer />

      <Sheet open={ask} title={t("book.askTitle")} onClose={() => setAsk(false)}>
        <div className="chip-row">
          <button type="button" disabled={busy} onClick={() => runAsk("why_before")}>
            {t("book.whyFirst")}
          </button>
          <button type="button" disabled={busy} onClick={() => runAsk("time_budget")}>
            {rich("book.iHave", {
              weeks: (
                <select aria-label={t("book.weeks")} value={weeks} onClick={(e) => e.stopPropagation()} onChange={(e) => setWeeks(Number(e.target.value))}>
                  {[1, 2, 3, 4, 6, 8].map((w) => (
                    <option key={w} value={w}>
                      {w}
                    </option>
                  ))}
                </select>
              ),
            })}
          </button>
          <button type="button" disabled={busy} onClick={() => runAsk("large_print")}>
            {t("book.largePrint")}
          </button>
        </div>
        {busy && <p className="hint">{t("book.thinking")}</p>}
        {answer && (
          <p className="answer" aria-live="polite">
            {answer}
          </p>
        )}
      </Sheet>
    </main>
  );
}
