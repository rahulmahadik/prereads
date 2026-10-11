import { useEffect, useRef, useState } from "react";
import { api } from "../api";
import Cover from "./Cover";
import ReadinessMeter from "./ReadinessMeter";
import ListenButton from "./ListenButton";
import { canListen, listen, picksScript } from "../speech";
import { AvailToggle, getBranch, getOnlyAvailable, setOnlyAvailable } from "./ui";
import { navigate } from "../router";
import type { DiscoverResponse, Recommendation } from "../types";

const EXAMPLES = [
  "I want to understand investing but I only have 2 weeks",
  "Something simple about the universe for this weekend",
  "How the brain makes decisions — I've read a bit",
  "AI for a beginner who knows some Python",
];

function needSummary(d: DiscoverResponse): string {
  const n = d.need;
  const bits: string[] = [];
  if (n.topics.length) bits.push(`about ${n.topics.slice(0, 3).join(", ")}`);
  if (n.level) bits.push(n.level <= 1 ? "for a newcomer" : n.level <= 3 ? "for someone who's read a bit" : "for someone who knows the field");
  if (n.max_hours) bits.push(`within about ${Math.round(n.max_hours)} hours`);
  if (n.age_group && n.age_group !== "adult") bits.push(`for a ${n.age_group}`);
  if (n.mood) bits.push(n.mood);
  if (n.language) bits.push(`in ${n.language}`);
  return bits.length ? `Books ${bits.join(", ")}` : "Here's what fits";
}

export default function Discover({ initialText = "" }: { initialText?: string }) {
  const [text, setText] = useState(initialText);
  const [res, setRes] = useState<DiscoverResponse | null>(null);
  const [filters, setFilters] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [hearing, setHearing] = useState(false);
  const [onlyAvail, setOnlyAvail] = useState(getOnlyAvailable());
  const lastQuery = useRef("");
  const availRef = useRef(getOnlyAvailable());

  const withAvail = (f: string[], on: boolean) => {
    const base = f.filter((id) => !id.startsWith("branch:"));
    return on ? [...base, getBranch() ? `branch:${getBranch()}` : "branch:any"] : base;
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

  const PAGE = 10;
  const [more, setMore] = useState(false);

  const run = async (q: string, f: string[]) => {
    if (q.trim().length < 2) return;
    setBusy(true);
    setError("");
    try {
      const r = await api.discover(q, getBranch(), withAvail(f, availRef.current), 0, PAGE);
      setRes(r);
      lastQuery.current = q;
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const loadMore = async () => {
    if (!res || !res.has_more) return;
    setMore(true);
    try {
      const r = await api.discover(lastQuery.current, getBranch(), withAvail(filters, availRef.current), res.offset + res.limit, PAGE);
      setRes({ ...r, results: [...res.results, ...r.results] });
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
    setText("");
    setRes(null);
    setFilters([]);
    setError("");
    lastQuery.current = "";
  };

  const toggle = (id: string) => {
    if (id.startsWith("branch:")) {
      flipAvail(!onlyAvail);
      return;
    }
    const next = filters.includes(id) ? filters.filter((x) => x !== id) : [...filters, id];
    setFilters(next);
    run(lastQuery.current || text, next);
  };

  const flipAvail = (on: boolean) => {
    availRef.current = on;
    setOnlyAvail(on);
    setOnlyAvailable(on);
    if (lastQuery.current) run(lastQuery.current, filters);
  };

  const open = (r: Recommendation) => {
    if (r.is_target) navigate("line", { id: r.line_id, title: r.title, author: r.author });
    else navigate("book", { id: r.line_id, title: r.title, author: r.author, stop: r.id });
  };

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
          Tell PreReads what you want
        </label>
        <div className="discover-input">
          <span className="big-icon" aria-hidden="true">✨</span>
          <input id="want" value={text} onChange={(e) => setText(e.target.value)} placeholder="Tell me what you want to read or learn, in your own words…" autoComplete="off" />
          {text && (
            <button type="button" className="clear-btn" onClick={reset} aria-label="Clear and start over" title="Clear">
              ✕
            </button>
          )}
          {canListen() && (
            <button type="button" className={`mic-btn ${hearing ? "on" : ""}`} onClick={voiceIn} aria-label="Say what you want" title="Say it instead" disabled={busy}>
              {hearing ? "●" : "🎤"}
            </button>
          )}
          <button type="submit" className="primary" disabled={busy || text.trim().length < 2}>
            {busy ? "Thinking…" : "Find"}
          </button>
        </div>
      </form>

      {!res && !busy && (
        <div className="examples">
          <span className="hint">Try:</span>
          {EXAMPLES.map((ex) => (
            <button key={ex} type="button" className="example" onClick={() => { setText(ex); setFilters([]); run(ex, []); }}>
              {ex}
            </button>
          ))}
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
              {res.engine !== "llm" && <span className="hint"> · reading your request with built-in rules until the OpenAI key is connected</span>}
            </p>
            <span className="need-actions">
              <ListenButton
                id="picks"
                label="Listen to the picks"
                text={() => picksScript({ summary: needSummary(res), picks: res.results.map((r) => ({ title: r.title, author: r.author, why: r.why, status: r.status })) })}
              />
              <button type="button" className="secondary start-over" onClick={reset}>
                ↺ Start over
              </button>
            </span>
          </div>

          <div className="chips-row" role="group" aria-label="Filters generated from your request">
            <AvailToggle on={onlyAvail} onChange={flipAvail} label={getBranch() ? "Only on the shelf at my library" : "Only available now"} />
            {res.chips.filter((c) => c.kind !== "branch").map((c) => (
              <button key={c.id} type="button" className={`fchip ${c.on ? "on" : ""}`} aria-pressed={c.on} onClick={() => toggle(c.id)}>
                {c.on ? "✓ " : ""}{c.label}
              </button>
            ))}
          </div>

          {res.results.length === 0 && <p className="hint">Nothing matches all those filters. Turn one off, or tell me more.</p>}
          {res.total > 0 && (
            <p className="hint count-line">
              Showing {res.results.length} of {res.total} {res.total === 1 ? "book" : "books"}
            </p>
          )}

          <ol className="rec-list">
            {res.results.map((r, i) => (
              <li key={r.id} className="rec" style={{ animationDelay: `${i * 50}ms` }}>
                <button type="button" className="rec-card" onClick={() => open(r)}>
                  <Cover book={{ id: r.id, title: r.title, author: r.author, subjects: [], summary: "", source: "seed" }} size="m" level={r.level} />
                  <span className="rec-main">
                    <span className="rec-kicker">
                      <span className="fit" title="How well it fits your request">{Math.round(r.fit * 100)}% fit</span>
                      {" · "}{r.category}
                    </span>
                    <strong className="rec-title">{r.title}</strong>
                    <span className="by">{r.author}</span>
                    <span className="rec-why">{r.why}</span>
                    <ReadinessMeter level={r.level} hours={r.hours} compact />
                    <span className="rec-foot">
                      <span className={`where ${r.status.startsWith("Available") ? "ok" : r.status.startsWith("Not there") ? "alt" : "no"}`}>{r.status}</span>
                      {r.hot_at.length > 0 && <span className="badge hot small">Hot at {r.hot_at[0]}</span>}
                      {r.is_target && r.before_count > 0 && <span className="hint">{r.before_count} PreReads first</span>}
                    </span>
                  </span>
                  <span className="chev" aria-hidden="true">›</span>
                </button>
              </li>
            ))}
          </ol>
          <div className="more-row">
            {res.has_more && (
              <button type="button" className="secondary load-more" onClick={loadMore} disabled={more}>
                {more ? "Loading…" : `Load more (${res.total - res.results.length} left)`}
              </button>
            )}
            {res.results.length > PAGE && (
              <button
                type="button"
                className="secondary load-more"
                onClick={() => {
                  setRes({ ...res, results: res.results.slice(0, PAGE), offset: 0, has_more: res.total > PAGE });
                  document.querySelector(".discover-results")?.scrollIntoView({ behavior: "smooth", block: "start" });
                }}
              >
                Show less
              </button>
            )}
          </div>
        </div>
      )}
    </section>
  );
}
