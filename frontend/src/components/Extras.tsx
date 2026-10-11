import { useState } from "react";
import type { Route } from "../types";

/* --------------------------------------------------------------- Share */
export function ShareCard({ route }: { route: Route }) {
  const [preview, setPreview] = useState<string>("");

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
      {preview && (
        <figure className="card-preview">
          <img src={preview} alt="Your reading line as a shareable card" />
          <figcaption className="hint">If the download did not start, press and hold the image to save or share it.</figcaption>
        </figure>
      )}
    </section>
  );
}
