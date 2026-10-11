import { useEffect, useState } from "react";
import { api } from "../api";
import { Sheet } from "./ui";
import { LanguageSegments } from "./LanguagePicker";
import { rich, t, useLang } from "../i18n";

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
  useLang();
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
    <Sheet open={open} title={t("settings.title")} onClose={onClose}>
      <section className="settings-lang">
        <h3 className="small-h">{t("lang.title")}</h3>
        <LanguageSegments />
        <p className="hint">{t("lang.hint")}</p>
      </section>
      <h3 className="small-h">{t("settings.dataMode")}</h3>
      {!info ? (
        <p className="hint">{t("common.loading")}</p>
      ) : (
        <div className="settings">
          <div className="mode-switch" role="radiogroup" aria-label={t("settings.dataMode")}>
            <button type="button" role="radio" aria-checked={info.demo} className={`mode-opt ${info.demo ? "on" : ""}`} disabled={busy || info.prototype} onClick={() => set({ demo: true })}>
              <strong>{t("settings.demo")}</strong>
              <span>{t("settings.demoSub")}</span>
            </button>
            <button type="button" role="radio" aria-checked={!info.demo} className={`mode-opt ${!info.demo ? "on" : ""}`} disabled={busy || info.prototype} onClick={() => set({ demo: false })}>
              <strong>{t("settings.real")}</strong>
              <span>{t("settings.realSub")}</span>
            </button>
          </div>

          <ul className="keys">
            {info.provider === "ollama" ? (
              <>
                <li>
                  <span>{t("settings.ollama")}</span>
                  <Pill ok={!!info.ollama?.reachable} text={info.ollama?.reachable ? t("settings.running") : t("settings.notRunning")} />
                </li>
                {info.ollama?.reachable &&
                  Object.entries(info.ollama.models).map(([kind, m]) => (
                    <li key={kind}>
                      <span>{["llm", "heavy", "vision", "embed"].includes(kind) ? t(`settings.model.${kind}` as "settings.model.llm") : kind}</span>
                      <Pill ok={m.installed} text={m.installed ? m.name : t("settings.notPulled", { name: m.name })} />
                    </li>
                  ))}
              </>
            ) : (
              <li>
                <span>{t("settings.openaiKey")}</span>
                <Pill ok={info.openai_key} text={info.openai_key ? t("settings.connected") : t("settings.openaiMissing")} />
              </li>
            )}
            <li>
              <span>{t("settings.nlbKey")}</span>
              <Pill ok={info.nlb_key} text={info.nlb_key ? t("settings.connected") : t("settings.nlbWaiting")} />
            </li>
            <li>
              <span>{t("settings.engine")}</span>
              <code>{info.mode}</code>
            </li>
            <li>
              <span>{t("settings.cached")}</span>
              <code>{info.cached_routes}</code>
            </li>
          </ul>

          {!info.demo && (
            <div className="fine-toggles">
              <label className={`fine ${info.provider === "ollama" ? (!info.ollama?.reachable ? "off" : "") : !info.openai_key ? "off" : ""}`}>
                <input type="checkbox" checked={info.use_llm} disabled={busy || (info.provider === "ollama" ? !info.ollama?.reachable : !info.openai_key)} onChange={(e) => set({ use_llm: e.target.checked })} />
                {info.provider === "ollama" ? t("settings.useLocal") : t("settings.useOpenai")}
              </label>
              <label className={`fine ${!info.nlb_key ? "off" : ""}`}>
                <input type="checkbox" checked={info.use_nlb} disabled={busy || !info.nlb_key} onChange={(e) => set({ use_nlb: e.target.checked })} />
                {t("settings.useNlb")}
              </label>
            </div>
          )}

          {info.prototype && <p className="hint">{t("settings.prototype")}</p>}
          <p className="hint">{rich("settings.instant", { env: <code>.env</code>, cmd: <code>make precompute</code> })}</p>
        </div>
      )}
    </Sheet>
  );
}
