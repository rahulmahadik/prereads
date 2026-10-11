import { t, useLang } from "../i18n";

const label = (level: number) => t(`level.${level}` as "level.1");

/** A ladder: rungs filled to the level. Reads as "how far up", never as a rating. */
function Ladder({ level, size }: { level: number; size: number }) {
  const w = size * 0.75;
  const h = size;
  const rungs = [1, 2, 3, 4, 5];
  const gap = (h - 4) / 5;
  return (
    <svg width={w} height={h} viewBox={`0 0 ${w} ${h}`} aria-hidden="true" className="ladder">
      <line x1="2" y1="1" x2="2" y2={h - 1} className="rail" />
      <line x1={w - 2} y1="1" x2={w - 2} y2={h - 1} className="rail" />
      {rungs.map((n) => {
        const y = h - 2 - (n - 1) * gap - gap / 2;
        return <line key={n} x1="3" x2={w - 3} y1={y} y2={y} className={`rung ${n <= level ? "on" : ""}`} />;
      })}
    </svg>
  );
}

export default function ReadinessMeter({ level, hours, compact = false }: { level: number; hours: number; compact?: boolean }) {
  useLang();
  const lvl = Math.max(1, Math.min(5, level));
  const h = Math.round(hours);
  return (
    <div className={`meter ${compact ? "compact" : ""} lvl-${lvl}`} role="img" aria-label={t("meter.aria", { n: lvl, label: label(lvl), hours: h })}>
      <span className="level-pill">
        <Ladder level={lvl} size={compact ? 16 : 22} />
        <span className="level-pill-text">
          <strong>{t("meter.level", { n: lvl })}</strong>
          <span className="level-pill-sep" aria-hidden="true">·</span>
          <span>{label(lvl)}</span>
        </span>
      </span>
      <span className="hours-chip" aria-hidden="true">
        {t("meter.hours", { hours: h })}
      </span>
    </div>
  );
}
