import { useEffect, useState } from "react";

type Format = { owned: number; available: number; holds: number; url: string } | null;
type Digital = {
  live: boolean;
  ebook?: Format;
  audiobook?: Format;
  search_url?: string;
};

function describe(f: NonNullable<Format>): { text: string; cls: "ok" | "alt" | "no" } {
  if (f.available > 0) return { text: `${f.available} of ${f.owned} available`, cls: "ok" };
  const h = f.holds;
  return { text: `Waitlist (${h} ${h === 1 ? "hold" : "holds"})`, cls: "alt" };
}

export default function DigitalCopies({ title, author }: { title: string; author?: string }) {
  const [d, setD] = useState<Digital | null>(null);
  useEffect(() => {
    let off = false;
    setD(null);
    const q = new URLSearchParams({ title, author: author || "" });
    fetch(`/api/digital?${q}`)
      .then((r) => (r.ok ? r.json() : { live: false }))
      .then((j) => !off && setD(j))
      .catch(() => !off && setD({ live: false }));
    return () => {
      off = true;
    };
  }, [title, author]);

  const search = d?.search_url || `https://nlb.overdrive.com/search?query=${encodeURIComponent(title)}`;
  const rows: [string, Format | undefined][] = d?.live
    ? [["eBook", d.ebook], ["Audiobook", d.audiobook]]
    : [];
  const found = rows.filter(([, f]) => f);

  return (
    <section className="digital" aria-label="Borrow it digitally">
      <h3>Borrow it digitally</h3>
      {found.map(([label, f]) => {
        const s = describe(f!);
        return (
          <div className="row-head" key={label}>
            <span>{label}</span>
            <span className={`status ${s.cls}`}>{s.text}</span>
            <a className="link-btn" style={{ minHeight: 44, display: "inline-flex", alignItems: "center" }}
               href={f!.url} target="_blank" rel="noreferrer">
              {s.cls === "ok" ? "Borrow on Libby" : "Join waitlist"} ↗
            </a>
          </div>
        );
      })}
      {d?.live && found.length === 0 && <p className="hint">Not in NLB's eBook or audiobook collection.</p>}
      {d?.live && <p className="hint">Live from NLB's OverDrive catalogue</p>}
      {(!d?.live || found.length === 0) && d && (
        <a className="link-btn" style={{ minHeight: 44, display: "inline-flex", alignItems: "center" }}
           href={search} target="_blank" rel="noreferrer">
          Search NLB eBooks and audiobooks ↗
        </a>
      )}
    </section>
  );
}
