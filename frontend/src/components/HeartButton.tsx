import { isHearted, toggleHeart, useStoreVersion, type Heart } from "../myshelf";
import { t, useLang } from "../i18n";

/** Heart a book onto "My shelf" (on-device). */
export default function HeartButton({ book, className = "" }: { book: Omit<Heart, "at">; className?: string }) {
  useStoreVersion();
  useLang();
  const on = isHearted(book.id);
  return (
    <button
      type="button"
      className={`heart-btn ${on ? "on" : ""} ${className}`}
      aria-pressed={on}
      aria-label={on ? t("heart.remove", { title: book.title }) : t("heart.save", { title: book.title })}
      title={on ? t("heart.on") : t("heart.saveShort")}
      onClick={(e) => {
        e.stopPropagation();
        toggleHeart(book);
      }}
    >
      <span aria-hidden="true">{on ? "♥" : "♡"}</span>
    </button>
  );
}
