import { useEffect, useRef, useState } from "react";
import { api } from "../api";
import { navigate } from "../router";
import { setBranch, setReaderLevel } from "./ui";
import { canListen, listen, speak, stop } from "../speech";

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
  | { kind: "trace"; steps: TraceStep[]; open: boolean };

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

const GREETING = "Hi! Tell me a book, an author, or something you want to learn. I'll find what to read first and where it is on a shelf.";

// Progress only: these advance on a timer while a request is in flight. The real steps come back in `trace`.
const PROGRESS_START = ["Understanding your request…", "Searching the catalogue…", "Checking shelves…", "Writing an answer…"];
const PROGRESS_FINISH = ["Building your reading path…", "Checking shelves…", "Writing an answer…"];

const fresh = (): Item[] => [{ kind: "msg", from: "bot", text: GREETING }];

const fmtMs = (ms: number) => (ms < 1000 ? `${Math.max(0, Math.round(ms))} ms` : `${(ms / 1000).toFixed(1)} s`);

const reducedMotion = () => typeof window !== "undefined" && window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;

function Progress({ steps }: { steps: string[] }) {
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
    <ol className="chat-steps live" role="status" aria-label="Working on it">
      {steps.slice(0, phase + 1).map((s, i) => (
        <li key={s} className={i < phase ? "done" : "now"}>
          <span className="chat-step-mark" aria-hidden="true">{i < phase ? "✓" : ""}</span>
          <span className="chat-step-name">{s}</span>
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
        How I found this · {steps.length} {steps.length === 1 ? "step" : "steps"} · {fmtMs(total)}
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
  const [open, setOpen] = useState(false);
  const [items, setItems] = useState<Item[]>(fresh);
  const [options, setOptions] = useState<Option[]>([]);
  const [state, setState] = useState<ChatState>({ step: "start" });
  const [result, setResult] = useState<Result | null>(null);
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [progress, setProgress] = useState<string[]>(PROGRESS_START);
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
      const r = (await api.chat("", { step: "start" })) as Reply;
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
    setItems((m) => [...m, { kind: "msg", from: "me", text: label ?? value }]);
    setOptions([]);
    setResult(null);
    setProgress(state.step === "branch" ? PROGRESS_FINISH : PROGRESS_START);
    setBusy(true);
    setText("");
    try {
      const r = (await api.chat(value, state)) as Reply;
      if (id !== reqId.current) return; // started over meanwhile
      const trace = r.trace ?? [];
      const add: Item[] = [];
      if (trace.length > 1) {
        traces.current += 1;
        add.push({ kind: "trace", steps: trace, open: traces.current === 1 }); // expanded on the first reply only
      }
      add.push(...r.messages.map((t) => ({ kind: "msg" as const, from: "bot" as const, text: t })));
      setItems((m) => [...m.map((x) => (x.kind === "trace" && x.open && traces.current > 1 ? { ...x, open: false } : x)), ...add]);
      if (voice) speak(r.messages.join(" ") + (r.options.length ? " Your options are: " + r.options.map((o) => o.label).join(", ") + "." : ""), "chat");
      setOptions(r.options);
      setState(r.state);
      setResult(r.result ?? null);
    } catch (e) {
      if (id === reqId.current) setItems((m) => [...m, { kind: "msg", from: "bot", text: (e as Error).message || "Something went wrong. Try again." }]);
    } finally {
      if (id === reqId.current) {
        setBusy(false);
        window.setTimeout(() => inputRef.current?.focus(), 0);
      }
    }
  };

  const reset = () => {
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
      <button type="button" className={`chat-fab ${open ? "hide" : ""}`} onClick={() => setOpen(true)} aria-label="Ask PreReads">
        <span aria-hidden="true">💬</span> Ask PreReads
      </button>

      {open && (
        <div className="chat-panel" role="dialog" aria-label="Ask PreReads">
          <div className="chat-head">
            <span className="chat-title">
              <span aria-hidden="true">📚</span> Ask PreReads
            </span>
            <span className="chat-head-actions">
              <button type="button" className={`icon-btn small ${voice ? "on" : ""}`} onClick={() => setVoice((v) => !v)} aria-pressed={voice} aria-label="Read replies aloud" title="Read replies aloud">
                🔊
              </button>
              <button type="button" className="chat-restart" onClick={reset} disabled={items.length <= 1 && !busy}>
                <span aria-hidden="true">↺</span> Start over
              </button>
              <button type="button" className="icon-btn small" onClick={() => setOpen(false)} aria-label="Close">
                ✕
              </button>
            </span>
          </div>
          <div className="chat-body" role="log" aria-live="polite" aria-relevant="additions">
            {items.map((m, i) =>
              m.kind === "trace" ? (
                <TraceRow key={i} steps={m.steps} open={m.open} onToggle={() => toggleTrace(i)} />
              ) : (
                <div key={i} className={`bubble ${m.from}`}>
                  {m.text}
                </div>
              ),
            )}
            {busy && <Progress steps={progress} />}
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
                  🧭 Directions to {result.start_title}
                </button>
                <button type="button" className="secondary" onClick={openLine}>
                  See the whole path
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
              placeholder={busy ? "Working on it…" : state.step === "start" ? "A title, author or topic…" : "Or type your answer…"}
              aria-label="Message"
              autoComplete="off"
              enterKeyHint="send"
              disabled={busy}
            />
            {canListen() && (
              <button
                type="button"
                className={`icon-btn small ${hearing ? "on" : ""}`}
                aria-label="Speak your message"
                title="Speak"
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
            <button type="submit" className="primary" disabled={busy || !text.trim()} aria-label="Send">
              ➤
            </button>
          </form>
        </div>
      )}
    </>
  );
}
