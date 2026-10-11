import { useEffect, useState } from "react";
import { api } from "../api";
import Cover from "../components/Cover";
import ReadinessMeter from "../components/ReadinessMeter";
import ListenButton from "../components/ListenButton";
import { bookScript } from "../speech";
import { parseCallNumber, stepsFor } from "../components/WayfindMap";
import WayfindMap from "../components/WayfindMap";
import { Sheet, TopBar, getBranch, nlbSearchUrl, shelfStatus, shortBranch, useBack, useReadSet } from "../components/ui";
import { navigate } from "../router";
import type { Route, Stop } from "../types";

export default function Book({ id, title, author, stopId }: { id: string; title: string; author: string; stopId: string }) {
  const goBack = useBack("line");
  const [route, setRoute] = useState<Route | null>(null);
  const [error, setError] = useState("");
  const [ask, setAsk] = useState(false);
  const [answer, setAnswer] = useState("");
  const [busy, setBusy] = useState(false);
  const [weeks, setWeeks] = useState(2);
  const [readSet, toggleRead] = useReadSet();
  const [shownLibs, setShownLibs] = useState(0);   // 0 = collapsed (status block only)
  const branchPref = getBranch();

  useEffect(() => {
    api
      .route(id, title, author)
      .then(setRoute)
      .catch((e) => setError((e as Error).message));
  }, [id, title, author]);

  const stops = route?.stops ?? [];
  const idx = stops.findIndex((s) => s.book.id === stopId);
  const stop: Stop | undefined = stops[idx];

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
  const wayfind = st.kind === "available" || st.kind === "elsewhere" ? { callNumber: st.callNumber || "", branch: st.branch } : null;
  const statusText =
    st.kind === "available" ? `It's available at ${shortBranch(st.branch)}` :
    st.kind === "elsewhere" ? `It's not at ${shortBranch(st.here)} right now; the nearest copy is at ${shortBranch(st.branch)}` :
    st.kind === "waiting" ? "All copies are out, so join the waiting list and read the PreReads while you wait" :
    "No physical copies are listed; check the NLB app for an eBook";
  const narration = () =>
    bookScript({
      title: book.title, author: book.author, why: stop.role === "target" ? readiness.one_line || stop.why : stop.why,
      level: readiness.level, hours: readiness.hours, status: statusText, callNumber: wayfind?.callNumber, branch: wayfind?.branch,
      assumes: readiness.assumed_concepts, steps: wayfind && wayfind.callNumber ? stepsFor(parseCallNumber(wayfind.callNumber), wayfind.callNumber).map((x) => x.text) : [],
    });
  const read = readSet.has(book.id);
  const role = stop.role === "target" ? "Your book" : stop.role === "before" ? "PreRead" : "NextRead";
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
        title={`${role} · ${idx + 1} of ${stops.length}`}
        right={
          <span className="pager">
            <button type="button" className="icon-btn" onClick={() => go(idx - 1)} disabled={idx <= 0} aria-label="Previous book">
              ‹
            </button>
            <button type="button" className="icon-btn" onClick={() => go(idx + 1)} disabled={idx >= stops.length - 1} aria-label="Next book">
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
              <ListenButton id={`book:${book.id}`} text={narration} label="Listen" />
            </div>
            <p className="book-author">
              {book.author}
              {book.year ? ` · ${book.year}` : ""}
              {book.pages ? ` · ${book.pages} pp` : ""}
            </p>
            <ReadinessMeter level={readiness.level} hours={readiness.hours} />
          </div>
        </div>

        <div className="page page-right">
          <p className="why">{stop.role === "target" ? readiness.one_line || stop.why : stop.why}</p>
          {readiness.assumed_concepts.length > 0 && (
            <>
              <h3 className="small-h">Assumes you know</h3>
              <ul className="chips">
                {readiness.assumed_concepts.map((c, i) => (
                  <li key={c} style={{ animationDelay: `${120 + i * 50}ms` }}>
                    {c}
                  </li>
                ))}
              </ul>
            </>
          )}
          <h3 className="small-h">Where to get it</h3>
          {st.kind === "available" && (
            <div className="status ok">
              <strong>Available at {shortBranch(st.branch)}</strong>
              <span className="call">{st.callNumber}</span>
              {st.others > 0 && <span className="hint">Also in at {st.others} other {st.others === 1 ? "library" : "libraries"}</span>}
            </div>
          )}
          {st.kind === "elsewhere" && (
            <div className="status alt">
              <strong>Not at {shortBranch(st.here)} right now</strong>
              <span className="hint">Nearest copy: {shortBranch(st.branch)} · {st.callNumber}</span>
            </div>
          )}
          {st.kind === "waiting" && (
            <div className="status no">
              <strong>All copies are out{demand.reservations ? ` · ${demand.reservations} in the queue` : ""}</strong>
              <span className="hint">Join the waiting list on NLB, and read the PreReads while you wait.</span>
            </div>
          )}
          {st.kind === "none" && (
            <div className="status no">
              <strong>No physical copies listed</strong>
              <span className="hint">Check the NLB app for an eBook.</span>
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
                  {a.available > 0 ? <span className="in">{a.available} in</span> : <span className="out">all out</span>}
                </li>
              ))}
            </ul>
          )}
          {availability.length > 1 && (
            <div className="more-row">
              {shownLibs < sorted.length && (
                <button type="button" className="link-btn inline" onClick={() => setShownLibs((n) => Math.min(sorted.length, n + 3))}>
                  {shownLibs === 0 ? `Other libraries (${sorted.length})` : `Load more (${sorted.length - shownLibs} left)`}
                </button>
              )}
              {shownLibs > 0 && (
                <button type="button" className="link-btn inline" onClick={() => setShownLibs(0)}>
                  Show less
                </button>
              )}
            </div>
          )}
          <div className="badges">
            {demand.hot_branches.map((b) => (
              <span className="badge hot" key={b}>
                Hot at {shortBranch(b)}
              </span>
            ))}
            {demand.hidden_gem && <span className="badge gem">Hidden gem — in everywhere, nobody's queuing</span>}
          </div>
          {(availability.some((a) => a.demo) || demand.demo) && <p className="demo-note">Demo shelf data until the NLB key is connected.</p>}
        </div>
      </article>

      {wayfind && wayfind.callNumber && (
        <section className="section wayfind-section" id="find">
          <h3 className="small-h">
            Find it at {shortBranch(wayfind.branch)} <span className="hint">· {wayfind.callNumber}</span>
          </h3>
          <WayfindMap target={wayfind} />
        </section>
      )}

      <div className="action-bar">
        {stop.role !== "target" ? (
          <button type="button" className={`bar-btn ${read ? "on" : ""}`} onClick={() => toggleRead(book.id)} aria-pressed={read}>
            {read ? "✓ Read it" : "Mark read"}
          </button>
        ) : (
          <a className="bar-btn link-as-btn" href={nlbSearchUrl(book.title, book.isbn)} target="_blank" rel="noopener">
            {inSomewhere ? "Reserve" : "Waitlist"}
          </a>
        )}
        {wayfind && wayfind.callNumber ? (
          <a className="bar-btn primary" href="#find" onClick={(e) => { e.preventDefault(); document.getElementById("find")?.scrollIntoView({ behavior: "smooth", block: "start" }); }}>
            Find on shelf
          </a>
        ) : (
          <a className="bar-btn primary link-as-btn" href={nlbSearchUrl(book.title, book.isbn)} target="_blank" rel="noopener">
            Find on NLB
          </a>
        )}
        <button type="button" className="bar-btn" onClick={() => setAsk(true)}>
          Ask
        </button>
      </div>
      <p className="swipe-hint hint">Swipe to turn to the next book</p>

      <Sheet open={ask} title="Ask about this path" onClose={() => setAsk(false)}>
        <div className="chip-row">
          <button type="button" disabled={busy} onClick={() => runAsk("why_before")}>
            Why these first?
          </button>
          <button type="button" disabled={busy} onClick={() => runAsk("time_budget")}>
            I have{" "}
            <select aria-label="weeks" value={weeks} onClick={(e) => e.stopPropagation()} onChange={(e) => setWeeks(Number(e.target.value))}>
              {[1, 2, 3, 4, 6, 8].map((w) => (
                <option key={w} value={w}>
                  {w}
                </option>
              ))}
            </select>{" "}
            weeks
          </button>
          <button type="button" disabled={busy} onClick={() => runAsk("large_print")}>
            Large print or audio?
          </button>
        </div>
        {busy && <p className="hint">Thinking…</p>}
        {answer && (
          <p className="answer" aria-live="polite">
            {answer}
          </p>
        )}
      </Sheet>
    </main>
  );
}
