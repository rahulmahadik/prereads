/** Catalogue descriptions (Open Library especially) arrive with markdown links, source
 *  footnotes and separator lines. Turn them into one plain paragraph a reader can scan. */
export function cleanSummary(raw: string | null | undefined): string {
  if (!raw) return "";
  // Everything after a separator line is "Also contained in…" / edition notes, not the description.
  const cut = raw.search(/^\s*[-=*_]{3,}\s*$/m);
  let s = (cut >= 0 ? raw.slice(0, cut) : raw)
    .replace(/<[^>]*>?/g, " ") // stray HTML tags from catalogue records
    .replace(/&amp;/g, "&").replace(/&quot;/g, '"').replace(/&#39;/g, "'")
    .replace(/\[([^\]]+)\]\[\d+\]/g, "$1") // [text][1] reference links
    .replace(/\[([^\]]+)\]\((https?:[^)]+)\)/g, "$1") // [text](url)
    .replace(/^\s*\[\d+\]:\s*\S+.*$/gm, "") // footnote definitions
    .replace(/\(\s*\[?source\]?[^)]*\)/gi, "") // "([source][1])"
    .replace(/https?:\/\/\S+/g, "")
    .replace(/[*_`#>]+/g, "")
    .replace(/\s+/g, " ")
    .trim();
  s = s.replace(/^"(.*)"$/, "$1").trim();
  return s.length < 40 ? "" : s;
}
