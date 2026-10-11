import { useEffect, useRef, useState } from "react";
import { api } from "../api";
import { navigate } from "../router";
import { setBranch, setReaderLevel } from "./ui";
import { canListen, listen, speak, stop } from "../speech";

interface Msg {
  from: "bot" | "me";
  text: string;
}

interface Option {
  label: string;
  value: string;
}

type ChatState = { step: string; book_id?: string | null; candidates?: unknown[]; level?: number | null; branch?: string | null };

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

const GREETING = "Hi! Tell me a book, an author, or something you want to learn — I'll find what to read first and where it is on a shelf.";

export default function ChatPanel() {
  const [open, setOpen] = useState(false);
  const [msgs, setMsgs] = useState<Msg[]>([{ from: "bot", text: GREETING }]);
  const [options, setOptions] = useState<Option[]>([]);
  const [state, setState] = useState<ChatState>({ step: "start" });
  const [result, setResult] = useState<Result | null>(null);
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [voice, setVoice] = useState(() => localStorage.getItem("prereads.voice") === "1");
  const [hearing, setHearing] = useState(false);
  const endRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    localStorage.setItem("prereads.voice", voice ? "1" : "0");
    if (!voice) stop();
  }, [voice]);

  useEffect(() => {
    endRef.current?.scrollIntoView({ block: "end" });
  }, [msgs, options, result, open]);

  const send = async (value: string, label?: string) => {
    if (!value.trim() && state.step === "start") return;
    setMsgs((m) => [...m, { from: "me", text: label ?? value }]);
    setOptions([]);
    setBusy(true);
    setText("");
    try {
      const r = await api.chat(value, state);
      setMsgs((m) => [...m, ...r.messages.map((t) => ({ from: "bot" as const, text: t }))]);
      if (voice) speak(r.messages.join(" ") + (r.options.length ? " Your options are: " + r.options.map((o) => o.label).join(", ") + "." : ""), "chat");
      setOptions(r.options);
      setState(r.state);
      setResult(r.result ?? null);
    } catch (e) {
      setMsgs((m) => [...m, { from: "bot", text: (e as Error).message }]);
    } finally {
      setBusy(false);
    }
  };

  const reset = () => {
    setMsgs([{ from: "bot", text: GREETING }]);
    setOptions([]);
    setState({ step: "start" });
    setResult(null);
  };

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
              <button type="button" className="icon-btn small" onClick={reset} aria-label="Start over" title="Start over">
                ↺
              </button>
              <button type="button" className="icon-btn small" onClick={() => setOpen(false)} aria-label="Close">
                ✕
              </button>
            </span>
          </div>
          <div className="chat-body">
            {msgs.map((m, i) => (
              <div key={i} className={`bubble ${m.from}`}>
                {m.text}
              </div>
            ))}
            {busy && <div className="bubble bot typing">…</div>}
            {options.length > 0 && (
              <div className="chat-options">
                {options.map((o) => (
                  <button key={o.value + o.label} type="button" onClick={() => send(o.value, o.label)}>
                    {o.label}
                  </button>
                ))}
              </div>
            )}
            {result && (
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
              if (!busy) send(text);
            }}
          >
            <input value={text} onChange={(e) => setText(e.target.value)} placeholder={state.step === "start" ? "A title, author or topic…" : "Or type your answer…"} aria-label="Message" autoComplete="off" />
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
                    setMsgs((m) => [...m, { from: "bot", text: (e as Error).message }]);
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
