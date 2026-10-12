import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { speak, stop, subscribe, type SpeechState } from "./speech";

// The natural voice loads over the network; each request resolves only when the test says so.
let pending: { resolve: () => void; signal?: AbortSignal }[] = [];
let played: string[] = [];

class FakeAudio {
  src: string;
  onended: (() => void) | null = null;
  onerror: (() => void) | null = null;
  constructor(src: string) {
    this.src = src;
  }
  play() {
    played.push(this.src);
    return Promise.resolve();
  }
  pause() {}
}

beforeEach(() => {
  pending = [];
  played = [];
  let n = 0;
  vi.stubGlobal("window", {});
  vi.stubGlobal("Audio", FakeAudio);
  vi.stubGlobal("URL", { createObjectURL: () => `blob:${++n}` });
  vi.stubGlobal("fetch", (_url: string, init: { signal?: AbortSignal }) =>
    new Promise((resolve, reject) => {
      init.signal?.addEventListener("abort", () => reject(new DOMException("aborted", "AbortError")));
      pending.push({ signal: init.signal, resolve: () => resolve({ ok: true, status: 200, blob: async () => new Blob(["x"]) }) });
    }),
  );
});

afterEach(() => {
  stop();
  vi.unstubAllGlobals();
});

const settle = () => new Promise((r) => setTimeout(r, 0));
const finishAll = async () => {
  pending.forEach((p) => p.resolve());
  await settle();
  await settle();
};

describe("speak", () => {
  it("shows the reading as started while the voice loads, so the button turns into Stop", async () => {
    const seen: SpeechState[] = [];
    const off = subscribe((s) => seen.push(s));
    void speak("About this book.", "book:1");
    expect(seen[seen.length - 1]).toEqual({ speaking: true, id: "book:1", source: null });
    await finishAll();
    expect(seen[seen.length - 1]).toEqual({ speaking: true, id: "book:1", source: "natural" });
    off();
  });

  it("plays at most one reading when the same button is tapped quickly several times", async () => {
    for (let i = 0; i < 5; i++) void speak("About this book.", "book:1");
    await finishAll();
    expect(played.length).toBeLessThanOrEqual(1);
  });

  it("plays only the last reading when different buttons are tapped quickly", async () => {
    void speak("First book.", "book:1");
    void speak("Second book.", "book:2");
    void speak("Third book.", "book:3");
    await finishAll();
    expect(played).toHaveLength(1);
  });

  it("plays nothing when stopped before the voice has loaded", async () => {
    let last: SpeechState | null = null;
    const off = subscribe((s) => (last = s));
    void speak("About this book.", "book:1");
    stop();
    await finishAll();
    expect(played).toHaveLength(0);
    expect(last).toEqual({ speaking: false, id: null, source: null });
    off();
  });
});
