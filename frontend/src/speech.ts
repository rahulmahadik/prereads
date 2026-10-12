/* Listen & speak.
   speak(text): tries the server's natural voice (/api/tts); if unavailable, uses
   the browser's best built-in voice. Only one thing speaks at a time.
   listen(): browser speech recognition for voice input (Chrome/Edge/Safari).
   lang is a BCP-47 code (en-SG, zh-CN, ms-MY, ta-IN; see voiceLang() in i18n.ts). The natural
   voice (Kokoro) is English-only, so other languages go straight to the browser voice. */
import { t } from "./i18n";

type Listener = (state: SpeechState) => void;
export type SpeechState = { speaking: boolean; id: string | null; source: "natural" | "browser" | null };

let state: SpeechState = { speaking: false, id: null, source: null };
const listeners = new Set<Listener>();
let audio: HTMLAudioElement | null = null;
let naturalAvailable: boolean | null = null; // learned on first call
// Every speak() and stop() starts a new turn. A voice that finishes loading after its turn
// has passed is dropped, so quick repeated taps never stack up several readings.
let turn = 0;
let loading: AbortController | null = null;
const IDLE: SpeechState = { speaking: false, id: null, source: null };

function emit(next: SpeechState) {
  state = next;
  listeners.forEach((l) => l(state));
}

/** Ends the reading only if it still belongs to the current turn. */
const endFor = (mine: number) => () => {
  if (mine === turn) emit(IDLE);
};

export function subscribe(l: Listener): () => void {
  listeners.add(l);
  l(state);
  return () => listeners.delete(l);
}

export function stop() {
  turn++;
  loading?.abort();
  loading = null;
  if (audio) {
    audio.pause();
    audio.src = "";
    audio = null;
  }
  if ("speechSynthesis" in window) window.speechSynthesis.cancel();
  emit(IDLE);
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
  const best = [...voices].sort((a, b) => score(b) - score(a))[0];
  // Only a voice in the right language; otherwise let the browser choose one for u.lang.
  return best && score(best) >= 5 ? best : undefined;
}

async function speakBrowser(text: string, id: string, lang: string, mine: number): Promise<void> {
  if (!("speechSynthesis" in window)) return endFor(mine)();
  await new Promise<void>((resolve) => {
    if (window.speechSynthesis.getVoices().length) return resolve();
    const t = setTimeout(resolve, 400);
    window.speechSynthesis.onvoiceschanged = () => {
      clearTimeout(t);
      resolve();
    };
  });
  if (mine !== turn) return;
  window.speechSynthesis.cancel();
  const u = new SpeechSynthesisUtterance(text);
  const v = pickVoice(lang);
  if (v) u.voice = v;
  u.lang = v?.lang || lang;
  u.rate = 0.96;
  u.pitch = 1;
  u.onend = endFor(mine);
  u.onerror = endFor(mine);
  emit({ speaking: true, id, source: "browser" });
  window.speechSynthesis.speak(u);
}

export async function speak(text: string, id = "x", lang = "en-SG"): Promise<void> {
  if (state.speaking && state.id === id) return stop();
  stop();
  const clean = text.replace(/\s+/g, " ").trim();
  if (!clean) return;
  const mine = turn;
  // Show Stop straight away, while the voice loads; a second tap cancels the load.
  emit({ speaking: true, id, source: null });
  if (naturalAvailable !== false && lang.toLowerCase().startsWith("en")) {
    const ctl = new AbortController();
    loading = ctl;
    try {
      const res = await fetch("/api/tts", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ text: clean, lang }), signal: ctl.signal });
      if (res.ok) {
        naturalAvailable = true;
        const blob = await res.blob();
        if (mine !== turn) return;
        loading = null;
        audio = new Audio(URL.createObjectURL(blob));
        audio.onended = endFor(mine);
        audio.onerror = endFor(mine);
        emit({ speaking: true, id, source: "natural" });
        await audio.play();
        return;
      }
      if (res.status === 503) naturalAvailable = false;
    } catch {
      /* cancelled, or fall through to the browser voice */
    }
    if (mine !== turn) return;
    loading = null;
  }
  await speakBrowser(clean, id, lang, mine);
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

let serverStt: boolean | null = null; // learned on first call: is /api/stt (faster-whisper) available?

export function canListen(): boolean {
  const w = window as unknown as { SpeechRecognition?: RecognitionCtor; webkitSpeechRecognition?: RecognitionCtor };
  return Boolean(w.SpeechRecognition || w.webkitSpeechRecognition || (serverStt !== false && navigator.mediaDevices && typeof MediaRecorder !== "undefined"));
}

/* Record until about 1.2 s of quiet after speech (max 12 s). */
async function recordClip(): Promise<Blob> {
  const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
  const rec = new MediaRecorder(stream);
  const chunks: Blob[] = [];
  rec.ondataavailable = (e) => e.data.size && chunks.push(e.data);
  const ctx = new AudioContext();
  const analyser = ctx.createAnalyser();
  analyser.fftSize = 1024;
  ctx.createMediaStreamSource(stream).connect(analyser);
  const buf = new Uint8Array(analyser.fftSize);
  return new Promise((resolve) => {
    const started = Date.now();
    let heard = false;
    let quietSince = Date.now();
    const tick = setInterval(() => {
      analyser.getByteTimeDomainData(buf);
      const peak = buf.reduce((m, v) => Math.max(m, Math.abs(v - 128)), 0);
      if (peak > 12) {
        heard = true;
        quietSince = Date.now();
      }
      const quietFor = Date.now() - quietSince;
      if ((heard && quietFor > 1200) || Date.now() - started > 12000 || (!heard && Date.now() - started > 6000)) rec.stop();
    }, 100);
    rec.onstop = () => {
      clearInterval(tick);
      stream.getTracks().forEach((t) => t.stop());
      void ctx.close();
      resolve(new Blob(chunks, { type: rec.mimeType || "audio/webm" }));
    };
    rec.start();
  });
}

async function listenLocal(lang: string): Promise<string | null> {
  if (serverStt === false || !navigator.mediaDevices || typeof MediaRecorder === "undefined") return null;
  let clip: Blob;
  try {
    clip = await recordClip();
  } catch {
    return null; // mic blocked: let the browser path ask again / explain
  }
  const form = new FormData();
  form.append("audio", clip, "clip.webm");
  const res = await fetch(`/api/stt?lang=${encodeURIComponent(lang.slice(0, 2))}`, { method: "POST", body: form }).catch(() => null);
  if (!res || res.status === 503) {
    serverStt = false;
    return null;
  }
  if (!res.ok) throw new Error("Didn't catch that. Try again, closer to the mic.");
  serverStt = true;
  return ((await res.json()) as { text: string }).text;
}

export async function listen(lang = "en-SG"): Promise<string> {
  stop();
  const local = await listenLocal(lang);
  if (local) return local;
  return listenBrowser(lang);
}

function listenBrowser(lang: string): Promise<string> {
  const w = window as unknown as { SpeechRecognition?: RecognitionCtor; webkitSpeechRecognition?: RecognitionCtor };
  const Ctor = w.SpeechRecognition || w.webkitSpeechRecognition;
  if (!Ctor) return Promise.reject(new Error("Voice input isn't supported in this browser."));
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
/** "Level n of 5: …" words, in the current UI language. */
export const LEVEL_WORDS: Record<number, string> = {
  get 1() { return t("level.words.1"); },
  get 2() { return t("level.words.2"); },
  get 3() { return t("level.words.3"); },
  get 4() { return t("level.words.4"); },
  get 5() { return t("level.words.5"); },
};

/** Book page narration: the title, then the book's About text (the reason it's on the path
 *  when the catalogue has no description). */
export function bookScript(o: { title: string; author: string; about: string; why: string }): string {
  return [t("say.by", { title: o.title, author: o.author }), o.about || o.why].join(" ");
}

export function lineScript(o: { target: string; before: { title: string; why: string; hours: number; where: string }[]; hours: number; trip?: string }): string {
  if (!o.before.length) return t("say.readyNow", { target: o.target });
  const items = o.before.map((b, i) => t("say.item", { i: i + 1, title: b.title, why: b.why, hours: Math.round(b.hours), where: b.where }));
  const n = o.before.length;
  return `${t(n === 1 ? "say.before.one" : "say.before.other", { n, target: o.target, hours: Math.round(o.hours) })} ${items.join(" ")}${o.trip ? t("say.trip", { trip: o.trip }) : ""}`;
}

export function picksScript(o: { summary: string; picks: { title: string; author: string; why: string; status: string }[] }): string {
  const items = o.picks.slice(0, 3).map((p, i) => `${["First", "Second", "Third"][i]}: ${p.title}, by ${p.author}. ${p.why} ${p.status}.`);
  return `${o.summary}. Here are my top picks. ${items.join(" ")}`;
}
