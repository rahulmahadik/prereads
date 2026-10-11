import { useMemo, useState } from "react";
import { qrMatrix, qrSvgPath } from "../qr";
import { href } from "../router";
import type { Route } from "../types";

/** The reading path's own page URL, so a scan opens this path. */
function pathUrl(route: Route): string {
  const book = route.stops.find((s) => s.role === "target")!.book;
  return location.origin + location.pathname + href("line", { id: route.target_id, title: book.title, author: book.author });
}

function safeQr(url: string): boolean[][] | null {
  try {
    return qrMatrix(url);
  } catch {
    return null; // too long to encode: the card simply has no QR
  }
}

/* --------------------------------------------------------------- Share */
export function ShareCard({ route }: { route: Route }) {
  const [preview, setPreview] = useState<string>("");
  const qr = useMemo(() => safeQr(pathUrl(route)), [route]);

  const download = () => {
    const target = route.stops.find((s) => s.role === "target")!;
    const W = 1080;
    const H = 1350;
    const c = document.createElement("canvas");
    c.width = W;
    c.height = H;
    const ctx = c.getContext("2d")!;
    ctx.fillStyle = "#F5F7F6";
    ctx.fillRect(0, 0, W, H);
    ctx.fillStyle = "#16211F";
    ctx.font = "700 64px Atkinson Hyperlegible, Arial";
    ctx.fillText("PreReads", 80, 140);
    ctx.font = "400 34px Atkinson Hyperlegible, Arial";
    ctx.fillStyle = "#5E6A66";
    ctx.fillText("The books to read before the book you want to read", 80, 195);

    const stops = route.stops;
    const x0 = 120;
    const gap = Math.min(170, (W - 240) / Math.max(1, stops.length - 1));
    const y = 420;
    ctx.strokeStyle = "#0B5FD6";
    ctx.lineWidth = 14;
    ctx.lineCap = "round";
    ctx.beginPath();
    ctx.moveTo(x0, y);
    ctx.lineTo(x0 + gap * (stops.length - 1), y);
    ctx.stroke();
    stops.forEach((s, i) => {
      const x = x0 + gap * i;
      ctx.beginPath();
      ctx.arc(x, y, s.role === "target" ? 26 : 18, 0, Math.PI * 2);
      ctx.fillStyle = s.role === "target" ? "#0B5FD6" : "#FFFFFF";
      ctx.fill();
      ctx.lineWidth = 8;
      ctx.stroke();
    });

    ctx.fillStyle = "#16211F";
    let ty = 560;
    stops.forEach((s, i) => {
      ctx.font = `${s.role === "target" ? "700" : "400"} 36px Atkinson Hyperlegible, Arial`;
      ctx.fillText(`${i + 1}. ${s.book.title}`, 80, ty);
      ctx.font = "400 28px Atkinson Hyperlegible, Arial";
      ctx.fillStyle = "#5E6A66";
      const best = [...s.availability].sort((a, b) => b.available - a.available)[0];
      const where = best && best.available > 0 ? `${best.branch} · ${best.call_number}` : "reserve and read the path meanwhile";
      ctx.fillText(`level ${s.readiness.level} · ${Math.round(s.readiness.hours)} h · ${where}`.slice(0, 70), 80, ty + 38);
      ctx.fillStyle = "#16211F";
      ty += 100;
    });
    if (qr) {
      const quiet = 4;
      const mod = Math.max(2, Math.floor(200 / (qr.length + quiet * 2)));
      const box = (qr.length + quiet * 2) * mod;
      const qx = W - 80 - box;
      const qy = H - 120 - box;
      ctx.fillStyle = "#FFFFFF";
      ctx.fillRect(qx, qy, box, box);
      ctx.fillStyle = "#16211F";
      qr.forEach((row, ry) => row.forEach((dark, rx) => dark && ctx.fillRect(qx + (rx + quiet) * mod, qy + (ry + quiet) * mod, mod, mod)));
      ctx.font = "400 26px Atkinson Hyperlegible, Arial";
      ctx.fillStyle = "#5E6A66";
      ctx.fillText("Scan to open this reading path", qx + box - 380, qy - 16);
    }
    ctx.font = "400 26px Atkinson Hyperlegible, Arial";
    ctx.fillStyle = "#5E6A66";
    ctx.fillText("Built on NLB Labs open APIs · not an NLB product", 80, H - 70);

    const dataUrl = c.toDataURL("image/png");
    setPreview(dataUrl);
    // Native download works in browsers; WebViews often ignore it, so the
    // preview below is the fallback (long-press / share from the image).
    const a = document.createElement("a");
    a.download = `prereads-path-${target.book.title.replace(/[^a-z0-9]+/gi, "-").toLowerCase()}.png`;
    a.href = dataUrl;
    a.click();
  };

  return (
    <section className="section">
      <button type="button" className="primary" onClick={download}>
        Save this path as a card
      </button>
      {qr && (
        <figure className="share-qr">
          <svg viewBox={`0 0 ${qr.length + 8} ${qr.length + 8}`} role="img" aria-label="QR code that opens this reading path" shapeRendering="crispEdges">
            <rect width="100%" height="100%" fill="#fff" />
            <path transform="translate(4 4)" d={qrSvgPath(qr)} fill="var(--ink)" />
          </svg>
          <figcaption className="hint">Scan to open this reading path</figcaption>
        </figure>
      )}
      {preview && (
        <figure className="card-preview">
          <img src={preview} alt="Your reading line as a shareable card" />
          <figcaption className="hint">If the download did not start, press and hold the image to save or share it.</figcaption>
        </figure>
      )}
    </section>
  );
}
