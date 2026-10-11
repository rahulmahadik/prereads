import { useEffect, useRef, useState } from "react";
import { api } from "../api";
import { navigate } from "../router";
import { setBranch, setReaderLevel } from "./ui";
import { canListen, listen, speak, stop } from "../speech";
import { getLang, t, tn, useLang, voiceLang, type Key } from "../i18n";

interface Option {
  label: string;
  value: string;
  hint?: string;
}

interface TraceStep {
  step: string;
  detail: string;
  ms: number;
}

type Item =
  | { kind: "msg"; from: "bot" | "me"; text: string }
  | { kind: "hello" }
  | { kind: "trace"; steps: TraceStep[]; open: boolean }
  | { kind: "choices"; options: Option[]; chosen: string } // earlier options, kept read-only in the thread
  | { kind: "result"; result: Result };

type ChatState = { step: string; book_id?: string | null; focus_id?: string | null; candidates?: unknown[]; level?: number | null; branch?: string | null };

interface Result {
  book_id: string;
  title: string;
  author: string;
  level: number;
  branch: string;
  start_id: string;
  start_title: string;
  start_status: string;
}

interface Reply {
  messages: string[];
  options: Option[];
  state: ChatState;
  result?: Result | null;
  trace?: TraceStep[];
}

type LiveStep = { step: string; detail?: string; ms?: number; done: boolean };

/** The steps the server is actually running, as they start and finish (streamed). */
function LiveSteps({ steps }: { steps: LiveStep[] }) {
  useLang();
  if (steps.length === 0) return <div className="bubble bot typing" aria-hidden="true">…</div>;
  return (
    <ol className="chat-steps live" role="status" aria-label={t("chat.workingAria")}>
      {steps.map((s, i) => (
        <li key={`${s.step}-${i}`} className={s.done ? "done" : "now"}>
          <span className="chat-step-mark" aria-hidden="true">{s.done ? "✓" : ""}</span>
          <span className="chat-step-name">{s.step}</span>
          {s.done && (s.detail || s.ms !== undefined) && (
            <span className="chat-step-detail">{[s.detail, s.ms !== undefined ? fmtMs(s.ms) : ""].filter(Boolean).join(" · ")}</span>
          )}
        </li>
      ))}
    </ol>
  );
}

// Fallback only (no streaming): generic steps on a timer. The real steps still come back in `trace`.
const PROGRESS_START: Key[] = ["chat.p.understand", "chat.p.search", "chat.p.shelves", "chat.p.write"];
const PROGRESS_FINISH: Key[] = ["chat.p.build", "chat.p.shelves", "chat.p.write"];

const fresh = (): Item[] => [{ kind: "hello" }];

const fmtMs = (ms: number) => (ms < 1000 ? `${Math.max(0, Math.round(ms))} ms` : `${(ms / 1000).toFixed(1)} s`);

const reducedMotion = () => typeof window !== "undefined" && window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;

function Progress({ steps }: { steps: Key[] }) {
  useLang();
  const [phase, setPhase] = useState(0);
  const [shown, setShown] = useState(false);
  useEffect(() => {
    const show = window.setTimeout(() => setShown(true), 150); // fast replies never flash the list
    const tick = window.setInterval(() => setPhase((p) => Math.min(p + 1, steps.length - 1)), 900);
    return () => {
      window.clearTimeout(show);
      window.clearInterval(tick);
    };
  }, [steps]);
  if (!shown) return <div className="bubble bot typing" aria-hidden="true">…</div>;
  return (
    <ol className="chat-steps live" role="status" aria-label={t("chat.workingAria")}>
      {steps.slice(0, phase + 1).map((s, i) => (
        <li key={s} className={i < phase ? "done" : "now"}>
          <span className="chat-step-mark" aria-hidden="true">{i < phase ? "✓" : ""}</span>
          <span className="chat-step-name">{t(s)}</span>
        </li>
      ))}
    </ol>
  );
}

function TraceRow({ steps, open, onToggle }: { steps: TraceStep[]; open: boolean; onToggle: () => void }) {
  const total = steps.reduce((a, s) => a + s.ms, 0);
  return (
    <div className="chat-trace">
      <button type="button" className="chat-trace-toggle" aria-expanded={open} onClick={onToggle}>
        <span aria-hidden="true" className="chat-trace-caret">{open ? "▾" : "▸"}</span>
        {tn("chat.trace", steps.length, { time: fmtMs(total) })}
      </button>
      {open && (
        <ol className="chat-steps">
          {steps.map((s, i) => (
            <li key={i} className="done">
              <span className="chat-step-mark" aria-hidden="true">✓</span>
              <span className="chat-step-text">
                <span className="chat-step-name">{s.step}</span>
                {s.detail && <span className="chat-step-detail">{s.detail}</span>}
              </span>
              <span className="chat-step-ms">{fmtMs(s.ms)}</span>
            </li>
          ))}
        </ol>
      )}
    </div>
  );
}

export default function ChatPanel() {
  useLang();
  const [open, setOpen] = useState(false);
  const [maxed, setMaxed] = useState(() => {
    try {
      return localStorage.getItem("prereads.chatMax") === "1";
    } catch {
      return false;
    }
  });
  const toggleMax = () =>
    setMaxed((v) => {
      try {
        localStorage.setItem("prereads.chatMax", v ? "0" : "1");
      } catch {
        /* on-device preference only */
      }
      return !v;
    });
  const [live, setLive] = useState<LiveStep[] | null>(null);
  const ctrl = useRef<AbortController | null>(null);
  const lastSend = useRef<{ value: string; label?: string } | null>(null);
  const [failed, setFailed] = useState(false);
  const CHAT_TIMEOUT_MS = 60000; // the local model normally answers in ~5 s; past this, say so instead of spinning
  const cancel = () => {
    ctrl.current?.abort("cancel");
    ctrl.current = null;
  };
  const [items, setItems] = useState<Item[]>(fresh);
  const [options, setOptions] = useState<Option[]>([]);
  const [state, setState] = useState<ChatState>({ step: "start" });
  const [result, setResult] = useState<Result | null>(null);
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [progress, setProgress] = useState<Key[]>(PROGRESS_START);
  const [voice, setVoice] = useState(() => {
    try {
      return localStorage.getItem("prereads.voice") === "1";
    } catch {
      return false;
    }
  });
  const [hearing, setHearing] = useState(false);
  const endRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const reqId = useRef(0);
  const traces = useRef(0);
  const starters = useRef(false);

  useEffect(() => {
    try {
      localStorage.setItem("prereads.voice", voice ? "1" : "0");
    } catch {
      /* private mode */
    }
    if (!voice) stop();
  }, [voice]);

  useEffect(() => {
    endRef.current?.scrollIntoView({ block: "end", behavior: reducedMotion() ? "auto" : "smooth" });
  }, [items, options, result, open, busy]);

  // Starter chips under the greeting (subjects and a popular title from the catalogue); no model call.
  const loadStarters = async () => {
    const id = reqId.current;
    try {
      const r = (await api.chat("", { step: "start" }, getLang())) as Reply;
      if (id === reqId.current) setOptions(r.options);
    } catch {
      /* the greeting still works without chips */
    }
  };

  useEffect(() => {
    if (open && !starters.current) {
      starters.current = true;
      loadStarters();
    }
    if (open) window.setTimeout(() => inputRef.current?.focus(), 50);
  }, [open]);

  const send = async (value: string, label?: string) => {
    if (busy) return;
    if (!value.trim() && state.step === "start") return;
    const id = ++reqId.current;
    const keep: Item[] = [];
    if (options.length) keep.push({ kind: "choices", options, chosen: value });
    if (result) keep.push({ kind: "result", result });
    setItems((m) => [...m, ...keep, { kind: "msg", from: "me", text: label ?? value }]);
    setOptions([]);
    setResult(null);
    setProgress(state.step === "branch" ? PROGRESS_FINISH : PROGRESS_START);
    setBusy(true);
    setText("");
    try {
      setLive([]);
      setFailed(false);
      lastSend.current = { value, label };
      cancel();
      const ac = new AbortController();
      ctrl.current = ac;
      const timer = window.setTimeout(() => ac.abort("timeout"), CHAT_TIMEOUT_MS);
      let r: Reply;
      try {
        r = (await api.chatStream(value, state, getLang(), (e) => {
          if (id !== reqId.current) return;
          setLive((cur) => {
            const list = [...(cur ?? [])];
            if (e.type === "start") list.push({ step: e.step ?? "", done: false });
            else if (e.type === "done") {
              const i = list.map((x) => x.step).lastIndexOf(e.step ?? "");
              const rec = { step: e.step ?? "", detail: e.detail, ms: e.ms, done: true };
              if (i >= 0) list[i] = rec;
              else list.push(rec);
            }
            return list;
          });
        }, ac.signal)) as Reply;
      } catch (err) {
        window.clearTimeout(timer);
        if (ac.signal.aborted) {
          if (ac.signal.reason === "cancel" || id !== reqId.current) return; // cancelled by the reader
          throw new Error(t("chat.err.timeout", { s: Math.round(CHAT_TIMEOUT_MS / 1000) }));
        }
        if (!navigator.onLine) throw new Error(t("chat.err.offline"));
        // streaming unavailable (old proxy, etc.): one plain request with the same timeout
        setLive(null);
        r = (await Promise.race([
          api.chat(value, state, getLang()),
          new Promise((_, rej) => window.setTimeout(() => rej(new Error(t("chat.err.timeout", { s: Math.round(CHAT_TIMEOUT_MS / 1000) }))), CHAT_TIMEOUT_MS)),
        ])) as Reply;
      }
      window.clearTimeout(timer);
      if (id !== reqId.current) return; // started over meanwhile
      const trace = r.trace ?? [];
      const add: Item[] = [];
      if (trace.length > 1) {
        traces.current += 1;
        add.push({ kind: "trace", steps: trace, open: traces.current === 1 }); // expanded on the first reply only
      }
      add.push(...r.messages.map((t) => ({ kind: "msg" as const, from: "bot" as const, text: t })));
      setItems((m) => [...m.map((x) => (x.kind === "trace" && x.open && traces.current > 1 ? { ...x, open: false } : x)), ...add]);
      if (voice) speak(r.messages.join(" ") + (r.options.length ? " " + t("chat.options", { list: r.options.map((o) => o.label).join(", ") }) : ""), "chat", voiceLang());
      setOptions(r.options);
      setState(r.state);
      setResult(r.result ?? null);
    } catch (e) {
      if (id === reqId.current) {
        const msg = (e as Error).message || "";
        const text = /^stream 5\d\d|HTTP 5\d\d|^5\d\d/.test(msg) ? t("chat.err.server") : msg || t("chat.error");
        setItems((m) => [...m, { kind: "msg", from: "bot", text }]);
        setFailed(true);
      }
    } finally {
      if (id === reqId.current) {
        setLive(null);
        setBusy(false);
        window.setTimeout(() => inputRef.current?.focus(), 0);
      }
    }
  };

  const reset = () => {
    cancel();
    setFailed(false);
    reqId.current += 1;
    traces.current = 0;
    setItems(fresh());
    setOptions([]);
    setState({ step: "start" });
    setResult(null);
    setBusy(false);
    setText("");
    loadStarters();
  };

  const toggleTrace = (i: number) => setItems((m) => m.map((x, j) => (j === i && x.kind === "trace" ? { ...x, open: !x.open } : x)));

  const openLine = () => {
    if (!result) return;
    setReaderLevel(result.level);
    setBranch(result.branch);
    setOpen(false);
    navigate("line", { id: result.book_id, title: result.title, author: result.author });
  };

  const openDirections = () => {
    if (!result) return;
    setReaderLevel(result.level);
    setBranch(result.branch);
    setOpen(false);
    navigate("book", { id: result.book_id, title: result.title, author: result.author, stop: result.start_id });
  };

  const bookChoices = options.some((o) => o.hint && /^\d+$/.test(o.value));

  return (
    <>
      <button type="button" className={`chat-fab ${open ? "hide" : ""}`} onClick={() => setOpen(true)} aria-label={t("chat.ask")}>
        <span aria-hidden="true">💬</span> <span className="fab-label">{t("chat.ask")}</span>
      </button>

      {open && (
        <div className={`chat-panel ${maxed ? "max" : ""}`} role="dialog" aria-label={t("chat.ask")}>
          <div className="chat-head">
            <span className="chat-title">
              <span aria-hidden="true">📚</span> {t("chat.ask")}
            </span>
            <span className="chat-head-actions">
              <button type="button" className={`icon-btn small ${voice ? "on" : ""}`} onClick={() => setVoice((v) => !v)} aria-pressed={voice} aria-label={t("chat.voice")} title={t("chat.voice")}>
                🔊
              </button>
              <button type="button" className="icon-btn small chat-max" onClick={toggleMax} aria-pressed={maxed} aria-label={maxed ? t("chat.restore") : t("chat.maximise")} title={maxed ? t("chat.restore") : t("chat.maximise")}>
                <svg aria-hidden="true" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  {maxed ? <path d="M9 4v5H4M15 4v5h5M9 20v-5H4M15 20v-5h5" /> : <path d="M4 9V4h5M20 9V4h-5M4 15v5h5M20 15v5h-5" />}
                </svg>
              </button>
              <button type="button" className="chat-restart" onClick={reset} disabled={items.length <= 1 && !busy}>
                <span aria-hidden="true">↺</span> <span className="chat-restart-label">{t("chat.startOver")}</span>
              </button>
              <button type="button" className="icon-btn small" onClick={() => { cancel(); reqId.current += 1; setBusy(false); setLive(null); setOpen(false); }} aria-label={t("common.close")}>
                ✕
              </button>
            </span>
          </div>
          <div className="chat-body" role="log" aria-live="polite" aria-relevant="additions">
            {items.map((m, i) =>
              m.kind === "hello" ? (
                <div key={i} className="bubble bot">
                  {t("chat.greeting")}
                </div>
              ) : m.kind === "trace" ? (
                <TraceRow key={i} steps={m.steps} open={m.open} onToggle={() => toggleTrace(i)} />
              ) : m.kind === "choices" ? (
                <div key={i} className="chat-options past" aria-label={t("chat.earlier")}>
                  {m.options.map((o) => (
                    <span key={o.value + o.label} className={`chat-past-option ${o.value === m.chosen ? "chosen" : ""}`}>
                      <span className="chat-option-label">{o.value === m.chosen ? "✓ " : ""}{o.label}</span>
                      {o.hint && <span className="chat-option-hint">{o.hint}</span>}
                    </span>
                  ))}
                </div>
              ) : m.kind === "result" ? (
                <div key={i} className="chat-result past">
                  <button type="button" className="secondary" onClick={() => navigate("book", { id: m.result.book_id, title: m.result.title, author: m.result.author, stop: m.result.start_id })}>
                    {t("chat.directions", { title: m.result.start_title })}
                  </button>
                </div>
              ) : (
                <div key={i} className={`bubble ${m.from}`}>
                  {m.text}
                </div>
              ),
            )}
            {busy && (live ? <LiveSteps steps={live} /> : <Progress steps={progress} />)}
            {busy && (
              <button type="button" className="chat-cancel" onClick={() => { cancel(); reqId.current += 1; setBusy(false); setLive(null); setItems((m) => [...m, { kind: "msg", from: "bot", text: t("chat.cancelled") }]); }}>
                {t("chat.cancel")}
              </button>
            )}
            {!busy && failed && lastSend.current && (
              <button type="button" className="chat-retry" onClick={() => { const l = lastSend.current!; setItems((m) => m.slice(0, -2)); send(l.value, l.label); }}>
                ↻ {t("chat.retry")}
              </button>
            )}
            {!busy && options.length > 0 && (
              <div className={`chat-options ${bookChoices ? "stacked" : ""}`}>
                {options.map((o) => (
                  <button key={o.value + o.label} type="button" onClick={() => send(o.value, o.label)}>
                    <span className="chat-option-label">{o.label}</span>
                    {o.hint && <span className="chat-option-hint">{o.hint}</span>}
                  </button>
                ))}
              </div>
            )}
            {result && !busy && (
              <div className="chat-result">
                <button type="button" className="primary" onClick={openDirections}>
                  {t("chat.directions", { title: result.start_title })}
                </button>
                <button type="button" className="secondary" onClick={openLine}>
                  {t("chat.wholePath")}
                </button>
              </div>
            )}
            <div ref={endRef} />
          </div>
          <form
            className="chat-input"
            onSubmit={(e) => {
              e.preventDefault();
              if (!busy && text.trim()) send(text);
            }}
          >
            <input
              ref={inputRef}
              value={text}
              onChange={(e) => setText(e.target.value)}
              placeholder={t(busy ? "chat.ph.working" : state.step === "start" ? "chat.ph.start" : "chat.ph.answer")}
              aria-label={t("chat.message")}
              autoComplete="off"
              enterKeyHint="send"
              disabled={busy}
            />
            {canListen() && (
              <button
                type="button"
                className={`icon-btn small ${hearing ? "on" : ""}`}
                aria-label={t("chat.speakAria")}
                title={t("chat.speak")}
                disabled={busy}
                onClick={async () => {
                  setHearing(true);
                  try {
                    const heard = await listen();
                    send(heard);
                  } catch (e) {
                    setItems((m) => [...m, { kind: "msg", from: "bot", text: (e as Error).message }]);
                  } finally {
                    setHearing(false);
                  }
                }}
              >
                {hearing ? "●" : "🎤"}
              </button>
            )}
            <button type="submit" className="primary" disabled={busy || !text.trim()} aria-label={t("chat.send")}>
              ➤
            </button>
          </form>
        </div>
      )}
    </>
  );
}
