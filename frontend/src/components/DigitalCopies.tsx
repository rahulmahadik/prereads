import { useEffect, useState } from "react";
import { t, tn, useLang } from "../i18n";
import SampleReader from "./SampleReader";

type Format = { owned: number; available: number; holds: number; url: string; sample_url?: string } | null;
type Online = {
  gutenberg?: { url: string; read_url: string; formats: string[] } | null;
  openlibrary?: { access: "public" | "borrowable"; url: string; read_url: string } | null;
};
type Digital = {
  live: boolean;
  ebook?: Format;
  audiobook?: Format;
  search_url?: string;
};

function describe(f: NonNullable<Format>): { text: string; cls: "ok" | "alt" | "no" } {
  if (f.available > 0) return { text: t("dig.available", { a: f.available, o: f.owned }), cls: "ok" };
  return { text: tn("dig.waitlist", f.holds), cls: "alt" };
}

export default function DigitalCopies({ title, author }: { title: string; author?: string }) {
  useLang();
  const [d, setD] = useState<Digital | null>(null);
  const [o, setO] = useState<Online>({});
  const [reading, setReading] = useState(false);
  useEffect(() => {
    let off = false;
    setD(null);
    const q = new URLSearchParams({ title, author: author || "" });
    fetch(`/api/digital?${q}`)
      .then((r) => (r.ok ? r.json() : { live: false }))
      .then((j) => !off && setD(j))
      .catch(() => !off && setD({ live: false }));
    setO({});
    fetch(`/api/online?${q}`)
      .then((r) => (r.ok ? r.json() : {}))
      .then((j) => !off && setO(j || {}))
      .catch(() => !off && setO({}));
    return () => {
      off = true;
    };
  }, [title, author]);

  const search = d?.search_url || `https://nlb.overdrive.com/search?query=${encodeURIComponent(title)}`;
  const rows: [string, Format | undefined][] = d?.live
    ? [[t("dig.ebook"), d.ebook], [t("dig.audio"), d.audiobook]]
    : [];
  const gid = Number(o.gutenberg?.url.match(/\/ebooks\/(\d+)/)?.[1]) || 0;
  const found = rows.filter(([, f]) => f);

  return (
    <section className="digital" aria-label={t("dig.title")}>
      <h3>{t("dig.title")}</h3>
      {found.map(([label, f]) => {
        const s = describe(f!);
        return (
          <div className="row-head" key={label}>
            <span>{label}</span>
            <span className={`status ${s.cls}`}>{s.text}</span>
            <a className="link-btn" style={{ minHeight: 44, display: "inline-flex", alignItems: "center" }}
               href={f!.url} target="_blank" rel="noreferrer">
              {s.cls === "ok" ? t("dig.borrow") : t("dig.join")} ↗
            </a>
          </div>
        );
      })}
      {d?.live && d.ebook?.sample_url && (
        <a className="link-btn online-link" href={d.ebook.sample_url} target="_blank" rel="noreferrer">
          {t("dig.sample")} ↗
        </a>
      )}
      {gid ? (
        <button type="button" className="link-btn online-link" onClick={() => setReading(true)}>
          {t("dig.readHere")}
        </button>
      ) : null}
      {o.gutenberg && (
        <a className="link-btn online-link" href={o.gutenberg.read_url} target="_blank" rel="noreferrer">
          {t("dig.gutenberg")} ↗
        </a>
      )}
      {o.openlibrary && (
        <a className="link-btn online-link" href={o.openlibrary.read_url} target="_blank" rel="noreferrer">
          {o.openlibrary.access === "public" ? t("dig.olPublic") : t("dig.olBorrow")} ↗
        </a>
      )}
      {o.openlibrary?.access === "borrowable" && <p className="hint">{t("dig.olNote")}</p>}
      {reading && gid && <SampleReader gutenbergId={gid} onClose={() => setReading(false)} />}
      {d?.live && found.length === 0 && <p className="hint">{t("dig.notIn")}</p>}
      {d?.live && <p className="hint">{t("dig.live")}</p>}
      {(!d?.live || found.length === 0) && d && (
        <a className="link-btn" style={{ minHeight: 44, display: "inline-flex", alignItems: "center" }}
           href={search} target="_blank" rel="noreferrer">
          {t("dig.search")} ↗
        </a>
      )}
    </section>
  );
}
