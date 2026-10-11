import { useEffect } from "react";
import { createPortal } from "react-dom";
import { qrSvgPath } from "../qr";
import { LEVEL_WORDS } from "../speech";
import { t } from "../i18n";
import type { Route } from "../types";
import { getBranch, shelfStatus } from "./ui";

/** Print-only A6 cards: one "Read this first" card per PreRead on a reading path. */
export function ShelfTalkers({ route, qr, onDone }: { route: Route; qr: boolean[][] | null; onDone: () => void }) {
  const target = route.stops.find((s) => s.role === "target")!;
  const picks = route.stops.filter((s) => s.role === "before");
  const branch = getBranch();

  useEffect(() => {
    window.addEventListener("afterprint", onDone);
    const t = window.setTimeout(() => window.print(), 100);
    return () => {
      window.clearTimeout(t);
      window.removeEventListener("afterprint", onDone);
    };
  }, [onDone]);

  return createPortal(
    <div className="shelf-talkers" data-testid="shelf-talkers">
      {picks.map((s) => {
        const st = shelfStatus(s, branch || undefined);
        const call = st.kind === "none" ? "" : st.callNumber;
        const where = st.kind === "available" || st.kind === "elsewhere" ? st.branch : "";
        return (
          <article className="talker" key={s.book.id}>
            <p className="talker-kicker">{t("talker.kicker")}</p>
            <h2 className="talker-title">{s.book.title}</h2>
            <p className="talker-author">{s.book.author}</p>
            <p className="talker-before">{t("talker.before", { title: target.book.title })}</p>
            <p className="talker-why">{s.why}</p>
            <p className="talker-meta">
              {t("talker.meta", { n: s.readiness.level, words: LEVEL_WORDS[s.readiness.level] || "", hours: Math.round(s.readiness.hours) })}
            </p>
            {call && (
              <p className="talker-call">
                {t("talker.call")} <strong>{call}</strong>
                {where ? ` · ${where}` : ""}
              </p>
            )}
            <div className="talker-foot">
              {qr && (
                <svg viewBox={`0 0 ${qr.length + 8} ${qr.length + 8}`} className="talker-qr" role="img" aria-label={t("share.qrAria")} shapeRendering="crispEdges">
                  <rect width="100%" height="100%" fill="#fff" />
                  <path transform="translate(4 4)" d={qrSvgPath(qr)} fill="#000" />
                </svg>
              )}
              <p className="talker-small">
                {t("talker.scan")}
                <br />
                {t("talker.foot")}
              </p>
            </div>
          </article>
        );
      })}
    </div>,
    document.body,
  );
}
