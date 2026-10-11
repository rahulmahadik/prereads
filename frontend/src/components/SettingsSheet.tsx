import { useEffect, useState } from "react";
import { api } from "../api";
import { Sheet } from "./ui";

export interface ModeInfo {
  demo: boolean;
  provider?: string;
  ollama?: { reachable: boolean; base_url: string; models: Record<string, { name: string; installed: boolean }> } | null;
  openai_key: boolean;
  nlb_key: boolean;
  use_llm: boolean;
  use_nlb: boolean;
  mode: string;
  env_demo: boolean;
  cached_routes: number;
  prototype?: boolean;
}

function Pill({ ok, text }: { ok: boolean; text: string }) {
  return <span className={`status-pill ${ok ? "ok" : "no"}`}>{text}</span>;
}

export default function SettingsSheet({ open, onClose }: { open: boolean; onClose: () => void }) {
  const [info, setInfo] = useState<ModeInfo | null>(null);
  const [busy, setBusy] = useState(false);

  const load = () => api.mode().then(setInfo).catch(() => setInfo(null));
  useEffect(() => {
    if (open) load();
  }, [open]);

  const set = async (patch: Partial<Pick<ModeInfo, "demo" | "use_llm" | "use_nlb">>) => {
    setBusy(true);
    try {
      setInfo(await api.setMode(patch));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Sheet open={open} title="Data mode" onClose={onClose}>
      {!info ? (
        <p className="hint">Loading…</p>
      ) : (
        <div className="settings">
          <div className="mode-switch" role="radiogroup" aria-label="Data mode">
            <button type="button" role="radio" aria-checked={info.demo} className={`mode-opt ${info.demo ? "on" : ""}`} disabled={busy || info.prototype} onClick={() => set({ demo: true })}>
              <strong>Demo data</strong>
              <span>Cached reading paths, synthetic shelf data, built-in rules. Works offline.</span>
            </button>
            <button type="button" role="radio" aria-checked={!info.demo} className={`mode-opt ${!info.demo ? "on" : ""}`} disabled={busy || info.prototype} onClick={() => set({ demo: false })}>
              <strong>Real calls</strong>
              <span>Local AI models on this device for intelligence, scan and voice; NLB for shelf data when the key is in.</span>
            </button>
          </div>

          <ul className="keys">
            {info.provider === "ollama" ? (
              <>
                <li>
                  <span>Local AI (Ollama)</span>
                  <Pill ok={!!info.ollama?.reachable} text={info.ollama?.reachable ? "Running on this device" : "Not running — start Ollama"} />
                </li>
                {info.ollama?.reachable &&
                  Object.entries(info.ollama.models).map(([kind, m]) => (
                    <li key={kind}>
                      <span>{{ llm: "Chat model", heavy: "Precompute model", vision: "Cover scan model", embed: "Embedding model" }[kind] ?? kind}</span>
                      <Pill ok={m.installed} text={m.installed ? m.name : `${m.name} — not pulled`} />
                    </li>
                  ))}
              </>
            ) : (
              <li>
                <span>OpenAI key</span>
                <Pill ok={info.openai_key} text={info.openai_key ? "Connected" : "Missing — add OPENAI_API_KEY to .env"} />
              </li>
            )}
            <li>
              <span>NLB Labs key</span>
              <Pill ok={info.nlb_key} text={info.nlb_key ? "Connected" : "Waiting for the NLB email — shelf data stays demo"} />
            </li>
            <li>
              <span>Engine now</span>
              <code>{info.mode}</code>
            </li>
            <li>
              <span>Cached paths</span>
              <code>{info.cached_routes}</code>
            </li>
          </ul>

          {!info.demo && (
            <div className="fine-toggles">
              <label className={`fine ${info.provider === "ollama" ? (!info.ollama?.reachable ? "off" : "") : !info.openai_key ? "off" : ""}`}>
                <input type="checkbox" checked={info.use_llm} disabled={busy || (info.provider === "ollama" ? !info.ollama?.reachable : !info.openai_key)} onChange={(e) => set({ use_llm: e.target.checked })} />
                {info.provider === "ollama" ? "Use local AI models (readiness, proposals, scan, chat)" : "Use OpenAI (readiness, proposals, scan, chat, voice)"}
              </label>
              <label className={`fine ${!info.nlb_key ? "off" : ""}`}>
                <input type="checkbox" checked={info.use_nlb} disabled={busy || !info.nlb_key} onChange={(e) => set({ use_nlb: e.target.checked })} />
                Use NLB catalogue (availability, call numbers, trends)
              </label>
            </div>
          )}

          {info.prototype && <p className="hint">This hosted prototype runs on embedded demo data only. Run the repo locally to switch to real calls.</p>}
          <p className="hint">Switching here is instant and doesn't restart anything. Settings come from <code>.env</code>; run <code>make precompute</code> to rebuild the cached paths with the models.</p>
        </div>
      )}
    </Sheet>
  );
}
