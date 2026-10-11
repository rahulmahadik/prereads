/* Listen & speak.
   speak(text): tries the server's natural voice (/api/tts); if unavailable, uses
   the browser's best built-in voice. Only one thing speaks at a time.
   listen(): browser speech recognition for voice input (Chrome/Edge/Safari). */

type Listener = (state: SpeechState) => void;
export type SpeechState = { speaking: boolean; id: string | null; source: "natural" | "browser" | null };

let state: SpeechState = { speaking: false, id: null, source: null };
const listeners = new Set<Listener>();
let audio: HTMLAudioElement | null = null;
let naturalAvailable: boolean | null = null; // learned on first call

function emit(next: SpeechState) {
  state = next;
  listeners.forEach((l) => l(state));
}

export function subscribe(l: Listener): () => void {
  listeners.add(l);
  l(state);
  return () => listeners.delete(l);
}

export function stop() {
  if (audio) {
    audio.pause();
    audio.src = "";
    audio = null;
  }
  if ("speechSynthesis" in window) window.speechSynthesis.cancel();
  emit({ speaking: false, id: null, source: null });
}

function pickVoice(lang: string): SpeechSynthesisVoice | undefined {
  const voices = window.speechSynthesis.getVoices();
  const score = (v: SpeechSynthesisVoice) => {
    let s = 0;
    if (v.lang.toLowerCase().startsWith(lang.toLowerCase())) s += 10;
    else if (v.lang.toLowerCase().startsWith(lang.slice(0, 2))) s += 5;
    if (/natural|neural|premium|enhanced|google|siri|samantha|daniel|karen|moira/i.test(v.name)) s += 3;
    if (v.localService) s += 1;
    return s;
  };
  return [...voices].sort((a, b) => score(b) - score(a))[0];
}

async function speakBrowser(text: string, id: string, lang: string): Promise<void> {
  if (!("speechSynthesis" in window)) return;
  await new Promise<void>((resolve) => {
    if (window.speechSynthesis.getVoices().length) return resolve();
    const t = setTimeout(resolve, 400);
    window.speechSynthesis.onvoiceschanged = () => {
      clearTimeout(t);
      resolve();
    };
  });
  window.speechSynthesis.cancel();
  const u = new SpeechSynthesisUtterance(text);
  const v = pickVoice(lang);
  if (v) u.voice = v;
  u.lang = v?.lang || lang;
  u.rate = 0.96;
  u.pitch = 1;
  u.onend = () => emit({ speaking: false, id: null, source: null });
  u.onerror = () => emit({ speaking: false, id: null, source: null });
  emit({ speaking: true, id, source: "browser" });
  window.speechSynthesis.speak(u);
}

export async function speak(text: string, id = "x", lang = "en-SG"): Promise<void> {
  if (state.speaking && state.id === id) return stop();
  stop();
  const clean = text.replace(/\s+/g, " ").trim();
  if (!clean) return;
  if (naturalAvailable !== false) {
    try {
      const res = await fetch("/api/tts", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ text: clean, lang }) });
      if (res.ok) {
        naturalAvailable = true;
        const blob = await res.blob();
        audio = new Audio(URL.createObjectURL(blob));
        audio.onended = () => emit({ speaking: false, id: null, source: null });
        audio.onerror = () => emit({ speaking: false, id: null, source: null });
        emit({ speaking: true, id, source: "natural" });
        await audio.play();
        return;
      }
      if (res.status === 503) naturalAvailable = false;
    } catch {
      /* fall through to the browser voice */
    }
  }
  await speakBrowser(clean, id, lang);
}

/* ---------------- voice input ---------------- */
type RecognitionCtor = new () => {
  lang: string;
  interimResults: boolean;
  maxAlternatives: number;
  onresult: ((e: { results: ArrayLike<ArrayLike<{ transcript: string }>> }) => void) | null;
  onerror: ((e: unknown) => void) | null;
  onend: (() => void) | null;
  start: () => void;
  stop: () => void;
};

export function canListen(): boolean {
  const w = window as unknown as { SpeechRecognition?: RecognitionCtor; webkitSpeechRecognition?: RecognitionCtor };
  return Boolean(w.SpeechRecognition || w.webkitSpeechRecognition);
}

export function listen(lang = "en-SG"): Promise<string> {
  const w = window as unknown as { SpeechRecognition?: RecognitionCtor; webkitSpeechRecognition?: RecognitionCtor };
  const Ctor = w.SpeechRecognition || w.webkitSpeechRecognition;
  if (!Ctor) return Promise.reject(new Error("Voice input isn't supported in this browser."));
  stop();
  return new Promise((resolve, reject) => {
    const r = new Ctor();
    r.lang = lang;
    r.interimResults = false;
    r.maxAlternatives = 1;
    let done = false;
    r.onresult = (e) => {
      done = true;
      resolve(e.results[0][0].transcript);
    };
    r.onerror = (e) => {
      if (!done) reject(new Error("Didn't catch that. Try again, closer to the mic."));
      void e;
    };
    r.onend = () => {
      if (!done) reject(new Error("Didn't catch that. Try again."));
    };
    r.start();
  });
}

/* ---------------- narration scripts ---------------- */
const short = (b: string) => b.replace(" Public Library", "").replace(" Regional Library", "").replace(" Library", "");

export const LEVEL_WORDS: Record<number, string> = {
  1: "anyone can start it",
  2: "a little background helps",
  3: "some familiarity is needed",
  4: "it needs real background",
  5: "it's specialist territory",
};

export function bookScript(o: { title: string; author: string; why: string; level: number; hours: number; status: string; callNumber?: string; branch?: string; steps?: string[]; assumes?: string[] }): string {
  const parts = [
    `${o.title}, by ${o.author}.`,
    o.why,
    `Level ${o.level} of 5: ${LEVEL_WORDS[o.level] || ""}. About ${Math.round(o.hours)} hours of reading.`,
  ];
  if (o.assumes && o.assumes.length) parts.push(`It assumes you know ${o.assumes.slice(0, 4).join(", ")}.`);
  parts.push(o.status + (o.callNumber ? `, call number ${o.callNumber.replace(/\./g, " point ")}.` : "."));
  if (o.steps && o.steps.length) parts.push("To find it: " + o.steps.join(" Then, ").replace(/Then, Go/g, "Then go"));
  return parts.join(" ");
}

export function lineScript(o: { target: string; before: { title: string; why: string; hours: number; where: string }[]; hours: number }): string {
  if (!o.before.length) return `You can start ${o.target} today. Nothing needs to come first.`;
  const items = o.before.map((b, i) => `${i + 1}. ${b.title}. ${b.why} About ${Math.round(b.hours)} hours. ${b.where}.`);
  return `${o.before.length} ${o.before.length === 1 ? "book" : "books"} before ${o.target}, about ${Math.round(o.hours)} hours in total. ${items.join(" ")}`;
}

export function picksScript(o: { summary: string; picks: { title: string; author: string; why: string; status: string }[] }): string {
  const items = o.picks.slice(0, 3).map((p, i) => `${["First", "Second", "Third"][i]}: ${p.title}, by ${p.author}. ${p.why} ${p.status}.`);
  return `${o.summary}. Here are my top picks. ${items.join(" ")}`;
}

export { short as shortBranchName };
