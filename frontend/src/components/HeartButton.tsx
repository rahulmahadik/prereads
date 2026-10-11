import { isHearted, toggleHeart, useStoreVersion, type Heart } from "../myshelf";

/** Heart a book onto "My shelf" (on-device). */
export default function HeartButton({ book, className = "" }: { book: Omit<Heart, "at">; className?: string }) {
  useStoreVersion();
  const on = isHearted(book.id);
  return (
    <button
      type="button"
      className={`heart-btn ${on ? "on" : ""} ${className}`}
      aria-pressed={on}
      aria-label={on ? `Remove ${book.title} from My shelf` : `Save ${book.title} to My shelf`}
      title={on ? "On My shelf" : "Save to My shelf"}
      onClick={(e) => {
        e.stopPropagation();
        toggleHeart(book);
      }}
    >
      <span aria-hidden="true">{on ? "♥" : "♡"}</span>
    </button>
  );
}
