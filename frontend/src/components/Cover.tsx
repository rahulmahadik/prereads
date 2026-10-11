import type { Book } from "../types";

// Library-binding colours. Picked by a stable hash of the title so a book always
// gets the same cover, and neighbours on a line rarely share one.
const BINDINGS = [
  { bg: "#6E2A2A", ink: "#F3E9DA" }, // oxblood
  { bg: "#1F4D3A", ink: "#EAF1E6" }, // bottle green
  { bg: "#223A5E", ink: "#E8EEF7" }, // navy
  { bg: "#8A6D1F", ink: "#1D1A12" }, // mustard
  { bg: "#4A4E69", ink: "#EEEEF4" }, // slate
  { bg: "#5C3D6E", ink: "#F1E9F5" }, // plum
  { bg: "#2E6B6B", ink: "#E6F2F2" }, // teal
  { bg: "#A1512A", ink: "#FBEFE6" }, // brick
];

function hash(s: string): number {
  let h = 2166136261;
  for (let i = 0; i < s.length; i++) {
    h ^= s.charCodeAt(i);
    h = Math.imul(h, 16777619);
  }
  return Math.abs(h);
}

export function bindingFor(book: Book) {
  return BINDINGS[hash(book.title) % BINDINGS.length];
}

interface Props {
  book: Book;
  size?: "s" | "m" | "l";
  level?: number;
}

export default function Cover({ book, size = "m", level }: Props) {
  const b = bindingFor(book);
  const words = book.title.split(" ");
  const big = words.length > 4 ? words.slice(0, 4).join(" ") : book.title;
  const rest = words.length > 4 ? words.slice(4).join(" ") : "";
  return (
    <div className={`cover cover-${size}`} style={{ background: b.bg, color: b.ink }} aria-hidden="true">
      <span className="cover-spine" />
      {book.cover_url ? (
        <img className="cover-img" src={book.cover_url} alt="" loading="lazy" onError={(e) => ((e.currentTarget as HTMLImageElement).style.display = "none")} />
      ) : null}
      <div className="cover-text">
        <span className="cover-title">
          {big}
          {rest && <span className="cover-title-rest"> {rest}</span>}
        </span>
        <span className="cover-author">{book.author}</span>
      </div>
      {typeof level === "number" && (
        <span className="cover-level" style={{ color: b.bg, background: b.ink }}>
          {level}
        </span>
      )}
    </div>
  );
}
