import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { api } from "../api";
import Cover from "./Cover";
import ReadinessMeter from "./ReadinessMeter";
import ListenButton from "./ListenButton";
import { canListen, listen, picksScript } from "../speech";
import { AvailToggle, getBranch, getOnlyAvailable, setOnlyAvailable } from "./ui";
import { navigate } from "../router";
import { getLang, t, tn, useLang, voiceLang } from "../i18n";
import type { DiscoverResponse, FilterChip, Recommendation } from "../types";

const EXAMPLE_KEYS = ["disc.ex1", "disc.ex2", "disc.ex3", "disc.ex4"] as const;

// Fields the backend adds for two-phase discovery (optional, so older servers and the prototype still fit).
type Rec = Recommendation & { ai_pick?: boolean };
type Phased = Omit<DiscoverResponse, "results"> & { results: Rec[]; deep?: "ai" | "catalogue" | null };
type DeepKind = "ai" | "catalogue";
type DeepState = { phase: "idle" | "busy" | "done" | "gone"; kind: DeepKind };

const PAGE = 10;
const DEEP_LIMIT = 30; // ask the slow pass for a wide page; only the books the fast list lacks are shown
const DEEP_TIMEOUT_MS = 60_000;
const OTHER_CAP = 6; // deep-only catalogue books (not model picks) shown under the AI picks

function needSummary(d: Phased): string {
  const n = d.need;
  const bits: string[] = [];
  if (n.topics.length) bits.push(t("disc.need.about", { topics: n.topics.slice(0, 3).join(t("disc.need.sep")) }));
  if (n.level) bits.push(t(n.level <= 1 ? "disc.need.new" : n.level <= 3 ? "disc.need.some" : "disc.need.expert"));
  if (n.max_hours) bits.push(t("disc.need.hours", { n: Math.round(n.max_hours) }));
  if (n.age_group && n.age_group !== "adult") bits.push(t("disc.need.age", { age: n.age_group }));
  if (n.mood) bits.push(n.mood);
  if (n.language) bits.push(t("disc.need.lang", { lang: n.language }));
  return bits.length ? t("disc.need.books", { bits: bits.join(t("disc.need.sep")) }) : t("disc.need.fits");
}

/** Keep the chip row stable on a re-run of the same request: old order and labels, new on/off, new chips last. */
function mergeChips(prev: FilterChip[], next: FilterChip[]): FilterChip[] {
  const byId = new Map(next.map((c) => [c.id, c]));
  const kept = prev.map((c) => ({ ...c, on: byId.get(c.id)?.on ?? false }));
  const have = new Set(prev.map((c) => c.id));
  return [...kept, ...next.filter((c) => !have.has(c.id))];
}

/** Honest copy for how a list was made. The main list is always the fast one; the AI's own picks
 * carry the "llm" copy in their section. A fast list with no AI pass to follow says the AI is off. */
function engineNote(engine: string, deep?: DeepKind | null): string {
  if (engine === "fast") return t(deep === "ai" ? "disc.engine.instant" : "disc.engine.rules");
  if (engine === "llm") return t("disc.engine.llm");
  if (engine.startsWith("prototype")) return t("disc.engine.proto");
  return t("disc.engine.rules");
}

const sameIds =(a: FilterChip[], b: FilterChip[]) => a.length === b.length && a.every((c, i) => c.id === b[i].id && c.on === b[i].on);

const key = (r: Rec) => r.title.trim().toLowerCase();

export default function Discover({ initialText = "" }: { initialText?: string }) {
  const lang = useLang();
  const [text, setText] = useState(initialText);
  const [res, setRes] = useState<Phased | null>(null);
  const [chips, setChips] = useState<FilterChip[]>([]);
  const [ai, setAi] = useState<{ picks: Rec[]; others: Rec[]; at: number }>({ picks: [], others: [], at: 0 });
  const [deep, setDeep] = useState<DeepState>({ phase: "idle", kind: "ai" });
  const [filters, setFilters] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [hearing, setHearing] = useState(false);
  const [onlyAvail, setOnlyAvail] = useState(getOnlyAvailable());
  const [more, setMore] = useState(false);
  const lastQuery = useRef("");
  const availRef = useRef(getOnlyAvailable());
  const resRef = useRef<Phased | null>(null);
  const seq = useRef(0); // bumps on every new request; stale replies are dropped
  const deepCtl = useRef<AbortController | null>(null);
  const listRef = useRef<HTMLDivElement | null>(null);
  const anchor = useRef<number | null>(null); // list top before a background update, to undo any shift

  const commit = (r: Phased | null) => {
    resRef.current = r;
    setRes(r);
  };

  const withAvail = (f: string[], on: boolean) => {
    const base = f.filter((id) => !id.startsWith("branch:"));
    return on ? [...base, getBranch() ? `branch:${getBranch()}` : "branch:any"] : base;
  };

  const cancelDeep = () => {
    deepCtl.current?.abort();
    deepCtl.current = null;
  };

  useEffect(() => () => {
    seq.current++;
    cancelDeep();
  }, []);

  // A background update (chips from the AI, the status row) must not move the list under the reader's finger.
  useLayoutEffect(() => {
    if (anchor.current == null || !listRef.current) return;
    const delta = listRef.current.getBoundingClientRect().top - anchor.current;
    anchor.current = null;
    if (delta !== 0 && window.scrollY > 0) window.scrollBy(0, delta);
  }, [chips, deep, ai]);

  const holdList = () => {
    anchor.current = listRef.current ? listRef.current.getBoundingClientRect().top : null;
  };

  const voiceIn = async () => {
    setHearing(true);
    setError("");
    try {
      const heard = await listen();
      setText(heard);
      setFilters([]);
      run(heard, []);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setHearing(false);
    }
  };

  const runDeep = async (q: string, sent: string[], my: number, kind: DeepKind) => {
    const ctl = new AbortController();
    deepCtl.current = ctl;
    const timer = window.setTimeout(() => ctl.abort(), DEEP_TIMEOUT_MS);
    setDeep({ phase: "busy", kind });
    try {
      const d = (await api.discover(q, getBranch(), sent, 0, DEEP_LIMIT, { mode: "deep", signal: ctl.signal, lang: getLang() })) as Phased;
      const cur = resRef.current;
      if (my !== seq.current || !cur) return;
      const shownIds = new Set(cur.results.map((r) => r.id));
      const shownTitles = new Set(cur.results.map(key));
      const extra = d.results.filter((r) => !shownIds.has(r.id) && !shownTitles.has(key(r)));
      const picks = kind === "ai" ? extra.filter((r) => r.ai_pick) : [];
      const others = extra.filter((r) => !picks.includes(r)).slice(0, kind === "ai" ? OTHER_CAP : PAGE);
      holdList();
      setAi({ picks, others, at: cur.results.length });
      // The model read the request better (level, time, age): its chips win; on/off already reflects what was sent.
      if (d.engine === "llm") setChips((prev) => (sameIds(prev, d.chips) ? prev : d.chips));
      setDeep({ phase: picks.length + others.length ? "done" : "gone", kind });
    } catch {
      if (my === seq.current) {
        holdList();
        setDeep({ phase: "gone", kind }); // failed, timed out or replaced: just hide the row
      }
    } finally {
      window.clearTimeout(timer);
      if (deepCtl.current === ctl) deepCtl.current = null;
    }
  };

  const run = async (q: string, f: string[], sameQuery = false) => {
    if (q.trim().length < 2) return;
    const my = ++seq.current;
    cancelDeep();
    setBusy(true);
    setError("");
    const sent = withAvail(f, availRef.current);
    try {
      const r = (await api.discover(q, getBranch(), sent, 0, PAGE, { mode: "fast", lang: getLang() })) as Phased;
      if (my !== seq.current) return;
      commit(r);
      setChips((prev) => (sameQuery && prev.length ? mergeChips(prev, r.chips) : r.chips));
      setAi({ picks: [], others: [], at: 0 });
      lastQuery.current = q;
      if (r.deep) runDeep(q, sent, my, r.deep);
      else setDeep({ phase: "idle", kind: "ai" });
    } catch (e) {
      if (my === seq.current) {
        setError((e as Error).message);
        setDeep((cur) => (cur.phase === "busy" ? { ...cur, phase: "gone" } : cur));
      }
    } finally {
      if (my === seq.current) setBusy(false);
    }
  };

  const loadMore = async () => {
    if (!res || !res.has_more) return;
    const my = seq.current;
    setMore(true);
    try {
      // Paging stays on the fast path.
      const r = (await api.discover(lastQuery.current, getBranch(), withAvail(filters, availRef.current), res.offset + res.limit, PAGE, { mode: "fast", lang: getLang() })) as Phased;
      if (my !== seq.current) return;
      const cur = resRef.current ?? res;
      const seen = new Set([...cur.results, ...ai.picks, ...ai.others].map((x) => x.id));
      commit({ ...r, results: [...cur.results, ...r.results.filter((x) => !seen.has(x.id))] });
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setMore(false);
    }
  };

  useEffect(() => {
    if (initialText) run(initialText, []);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [initialText]);

  const reset = () => {
    seq.current++;
    cancelDeep();
    setText("");
    commit(null);
    setChips([]);
    setAi({ picks: [], others: [], at: 0 });
    setDeep({ phase: "idle", kind: "ai" });
    setFilters([]);
    setError("");
    setBusy(false);
    lastQuery.current = "";
  };

  const toggle = (id: string) => {
    if (id.startsWith("branch:")) {
      flipAvail(!onlyAvail);
      return;
    }
    const next = filters.includes(id) ? filters.filter((x) => x !== id) : [...filters, id];
    setFilters(next);
    run(lastQuery.current || text, next, true);
  };

  const flipAvail = (on: boolean) => {
    availRef.current = on;
    setOnlyAvail(on);
    setOnlyAvailable(on);
    if (lastQuery.current) run(lastQuery.current, filters, true);
  };

  const open = (r: Recommendation) => {
    if (r.is_target) navigate("line", { id: r.line_id, title: r.title, author: r.author });
    else navigate("book", { id: r.line_id, title: r.title, author: r.author, stop: r.id });
  };

  const card = (r: Rec, i: number, aiPick = false) => (
    <li key={r.id} className={`rec ${aiPick ? "rec-ai" : ""}`} style={{ animationDelay: `${i * 50}ms` }}>
      <button type="button" className="rec-card" onClick={() => open(r)}>
        <Cover book={{ id: r.id, title: r.title, author: r.author, subjects: [], summary: "", source: "seed" }} size="m" level={r.level} />
        <span className="rec-main">
          <span className="rec-kicker">
            {aiPick && <span className="badge ai-pick small" title={t("disc.aiPickTip")}>{t("disc.aiPick")}</span>}
            <span className="fit" title={t("disc.fitTip")}>{t("disc.fit", { n: Math.round(r.fit * 100) })}</span>
            {" · "}{r.category}
          </span>
          <strong className="rec-title">{r.title}</strong>
          <span className="by">{r.author}</span>
          <span className="rec-why">{r.why}</span>
          {r.blurb && r.blurb !== r.why && <span className="rec-blurb">{r.blurb}</span>}
          <ReadinessMeter level={r.level} hours={r.hours} compact />
          <span className="rec-foot">
            <span className={`where ${r.status.startsWith("Available") ? "ok" : r.status.startsWith("Not there") ? "alt" : "no"}`}>{r.status}</span>
            {r.hot_at.length > 0 && <span className="badge hot small">{t("home.hotAt", { branch: r.hot_at[0] })}</span>}
            {r.is_target && r.before_count > 0 && <span className="hint">{t("disc.preFirst", { n: r.before_count })}</span>}
          </span>
        </span>
        <span className="chev" aria-hidden="true">›</span>
      </button>
    </li>
  );

  const extraCount = ai.picks.length + ai.others.length;
  const at = res ? Math.min(ai.at, res.results.length) : 0;
  const deepLabel = t(deep.kind === "ai" ? "disc.deep.ai" : "disc.deep.cat");
  const doneLabel = deep.kind === "ai" && ai.picks.length ? tn("disc.done.ai", ai.picks.length) : t("disc.done.cat", { n: extraCount });

  return (
    <section className="discover">
      <form
        className="discover-form"
        onSubmit={(e) => {
          e.preventDefault();
          setFilters([]);
          run(text, []);
        }}
      >
        <label htmlFor="want" className="sr-only">
          {t("disc.label")}
        </label>
        <div className="discover-input">
          <span className="big-icon" aria-hidden="true">✨</span>
          <input id="want" value={text} onChange={(e) => setText(e.target.value)} placeholder={t("disc.placeholder")} autoComplete="off" />
          {text && (
            <button type="button" className="clear-btn" onClick={reset} aria-label={t("disc.clearAria")} title={t("disc.clear")}>
              ✕
            </button>
          )}
          {canListen() && (
            <button type="button" className={`mic-btn ${hearing ? "on" : ""}`} onClick={voiceIn} aria-label={t("disc.say")} title={t("disc.sayTitle")} disabled={busy}>
              {hearing ? "●" : "🎤"}
            </button>
          )}
          <button type="submit" className="primary" disabled={busy || text.trim().length < 2}>
            {busy ? t("disc.thinking") : t("disc.find")}
          </button>
        </div>
      </form>

      {!res && !busy && (
        <div className="examples">
          <span className="hint">{t("disc.try")}</span>
          {EXAMPLE_KEYS.map((k) => {
            const ex = t(k);
            return (
              <button key={k} type="button" className="example" onClick={() => { setText(ex); setFilters([]); run(ex, []); }}>
                {ex}
              </button>
            );
          })}
        </div>
      )}

      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}

      {busy && !res && (
        <div className="skeleton">
          <div className="sk-line" />
          <div className="sk-book">
            <div className="sk-cover" />
            <div className="sk-lines"><span /><span /><span /></div>
          </div>
        </div>
      )}

      {res && (
        <div className={`discover-results ${busy ? "busy" : ""}`} aria-live="polite">
          <div className="need-row">
            <p className="need-line">
              <span aria-hidden="true">🧠 </span>
              {needSummary(res)}
              <span className="hint engine-note"> · {engineNote(res.engine, res.deep)}</span>
            </p>
            <span className="need-actions">
              <ListenButton
                id="picks"
                label={t("disc.listenPicks")}
                lang={voiceLang(lang)}
                text={() => picksScript({ summary: needSummary(res), picks: [...res.results, ...ai.picks].map((r) => ({ title: r.title, author: r.author, why: r.why, status: r.status })) })}
              />
              <button type="button" className="secondary start-over" onClick={reset}>
                ↺ {t("disc.startOver")}
              </button>
            </span>
          </div>

          <div className="chips-row" role="group" aria-label={t("disc.filters")}>
            <AvailToggle on={onlyAvail} onChange={flipAvail} label={getBranch() ? t("disc.onlyShelf") : t("avail.only")} />
            {chips.filter((c) => c.kind !== "branch").map((c) => (
              <button key={c.id} type="button" className={`fchip ${c.on ? "on" : ""}`} aria-pressed={c.on} onClick={() => toggle(c.id)}>
                {c.on ? "✓ " : ""}{c.label}
              </button>
            ))}
          </div>

          {deep.phase !== "idle" && (
            <p className={`deep-row ${deep.phase}`} role="status" aria-hidden={deep.phase === "gone"}>
              {deep.phase === "busy" && (
                <>
                  <span className="deep-spin" aria-hidden="true" />
                  {deepLabel}
                </>
              )}
              {deep.phase === "done" && (
                <button type="button" className="deep-jump" onClick={() => document.getElementById("ai-picks")?.scrollIntoView({ behavior: "smooth", block: "start" })}>
                  ✓ {doneLabel} ↓
                </button>
              )}
            </p>
          )}

          <div ref={listRef}>
            {res.results.length === 0 && extraCount === 0 && <p className="hint">{t("disc.empty")}</p>}
            {res.total > 0 && (
              <p className="hint count-line">
                {tn("disc.count", res.total, { shown: res.results.length, total: res.total })}
              </p>
            )}

            <ol className="rec-list">{res.results.slice(0, extraCount ? at : undefined).map((r, i) => card(r, i))}</ol>

            {extraCount > 0 && (
              <section className="ai-picks" id="ai-picks" aria-label={t(ai.picks.length ? "disc.moreAi" : "disc.moreCat")}>
                <h3 className="ai-head">{t(ai.picks.length ? "disc.moreAi" : "disc.moreCat")}</h3>
                {ai.picks.length > 0 && (
                  <>
                    <p className="hint ai-note">{t("disc.aiNote")}</p>
                    <ol className="rec-list">{ai.picks.map((r, i) => card(r, i, true))}</ol>
                  </>
                )}
                {ai.others.length > 0 && (
                  <>
                    {ai.picks.length > 0 && <h4 className="ai-sub">{t("disc.alsoCat")}</h4>}
                    <ol className="rec-list">{ai.others.map((r, i) => card(r, i))}</ol>
                  </>
                )}
              </section>
            )}

            {extraCount > 0 && res.results.length > at && <ol className="rec-list rec-list-after">{res.results.slice(at).map((r, i) => card(r, i))}</ol>}
          </div>

          <div className="more-row">
            {res.has_more && (
              <button type="button" className="secondary load-more" onClick={loadMore} disabled={more}>
                {more ? t("common.loading") : t("disc.loadMore", { n: Math.max(0, res.total - (res.offset + res.limit)) })}
              </button>
            )}
            {res.results.length > PAGE && (
              <button
                type="button"
                className="secondary load-more"
                onClick={() => {
                  commit({ ...res, results: res.results.slice(0, PAGE), offset: 0, limit: PAGE, has_more: res.total > PAGE });
                  setAi((cur) => ({ ...cur, at: Math.min(cur.at, PAGE) }));
                  document.querySelector(".discover-results")?.scrollIntoView({ behavior: "smooth", block: "start" });
                }}
              >
                {t("common.showLess")}
              </button>
            )}
          </div>
        </div>
      )}
    </section>
  );
}
