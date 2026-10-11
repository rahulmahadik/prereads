# PreReads — design system (for the designer on the day)

## Screens (hash-routed, back button works in browsers and WebViews)
| # | Screen | Job | Primary action |
|---|---|---|---|
| 1 | Home `#/` | Say what you want or pick a book; My shelf | Type / speak / scan; tap a recommendation |
| 2 | Line `#/line` | See the reading path, track progress | Tap a book; tap a circle to mark read; sheets for walk-in, ask, share |
| 3 | Book `#/book` | Decide on one book | Reserve / Join waitlist; Find on shelf; Ask; swipe/‹ › to turn |
| 4 | Meet `#/meet` | Two readers, two levels, one book | Pick both levels, see the two paths converge |
| - | Ready `#/ready` | One question: how familiar are you | Still routed, but nothing links to it; familiarity is a chip on Line |

## Wayfinding (the unique feature)
Every NLB branch shelves non-fiction in Dewey order, fiction A–Z, children's in its own
zone. `WayfindMap.tsx` draws that shared layout as a schematic, parses the call number
(e.g. `English 153.4 KAH` → 100s bay), animates a path from the entrance, and writes four
plain steps. It is labelled "schematic, not to scale". When a reader sets their branch
(the "At" chip), every status and map uses that branch; if the book isn't there, it says so
and routes to the nearest copy.

## Clicks
Home → tap a book → line (2 taps). Familiarity and branch are chips on the line that open
sheets; they are remembered. Book screen shows status + directions with no extra tap; the
bottom bar holds Reserve/Mark read · Find on shelf · Ask.

## v2 tokens (the `:root` block near the end of styles.css wins over the original one)
paper #F3F6F9 · surface #FFF · surface-2 #E9EEF5 · ink #0E1A24 · muted #5B6B7A · accent (`--line`) #1F5EFF with
`--line-soft` #E6EDFF · available (`--stamp`) #0E9F6E / soft #E3F6EE · elsewhere (`--alt`) #C47A0A / soft #FFF1DC ·
waiting (`--hot`) #E2493B / soft #FDE7E4 · radius 14 / 20 · pill controls · one soft shadow (`--shadow-1`).
Status blocks are tonal (green/amber/red backgrounds), never raw counts. The wordmark is the accent colour by default.

## UI inventory added on 11 Oct (all use v2 tokens, 44px targets, 52px in senior mode)
| Element | Where | Look |
|---|---|---|
| Wordmark | Home header (`.wordmark-btn`) | accent `--line`; tap starts over; focus ring in accent |
| Heart (`HeartButton`) | row (top-right, 36px) and Book page (44px) | circle outline in `--rule`; on = `--hot` icon on `--hot-soft` |
| Note chip | path row under a hearted book | pill, `--surface-2`, 14px ink text; tap opens the note |
| Trip note (`.trip-note`) | Line, above the stops | `--stamp-soft` panel, green text, muted second line; "N of your PreReads are on shelf 332" |
| Similar row (`.similar-list`) | Book page, "Because you liked" | stacked cards: surface, 1px `--rule`, accent border on hover/focus, one-line reason |
| Nearest libraries (`NearestLibraries`) | library sheet | accent-tinted "Use my location" button; list items with name, distance, open/closed (`--stamp` open, muted closed); hours are labelled as default |
| Share QR (`.share-qr`) | share sheet and card | SVG, 200px max, 1.5px `--rule` border; also on print-only A6 shelf talkers |
| Reserve link (`.reserve-link`) | Book page | "Reserve on NLB" or "Join waitlist (N in queue)", opens the catalogue |
| Offline badge | top of app | appears only when the browser is offline |
| My shelf section | Home | hearts plus paths in progress with hours left |

## Idea in one line
A reading line (MRT stops) whose stops are physical books. The memorable thing is
the page turn; everything else stays quiet.

## Tokens (styles.css :root)
| Token | Value | Use |
|---|---|---|
| paper | #F5F7F6 | page background (cool paper, not cream) |
| paper-page | #FFFDF8 | the open book's pages |
| ink | #16211F | text, borders, progress segment |
| muted | #5E6A66 | secondary text |
| line | #0B5FD6 | the reading line, primary button |
| stamp | #157A4B | "copies in" stamp |
| hot | #C8321A | demand badge |
| covers | 8 library-binding colours | procedural covers (Cover.tsx) |

## Type
- UI: Atkinson Hyperlegible (made for low vision; 16px body, 20px in senior mode)
- Books: Fraunces (variable serif) for titles, covers and the "why" paragraph with a drop cap
- Never all-caps labels; sentence case everywhere

## Motion inventory (all CSS, all respect prefers-reduced-motion)
| Moment | Effect | Duration |
|---|---|---|
| Line loads | path draws itself left→right | 1.4 s |
| Change stop | book rotates in like a page (direction-aware) | 520 ms |
| Select stop | dot pulses once; progress segment extends | 520 / 420 ms |
| Card opens | readiness dots pop in sequence; concept chips settle | 320 / 300 ms |
| Availability | "x of y in" stamps on with a rubber-stamp overshoot | 420 ms |
| Pick a book | search collapses into a punched ticket | 360 ms |
| Loading | book-shaped skeleton shimmer | — |

## Interaction
- Phone: swipe left/right on the book; ‹ › buttons; tap any stop on the line
- Desktop: ← → keys; click stops; the ask/walk-in/share column is sticky
- Senior mode (Aa): bigger type and 52px targets, persisted

## Rules
- One memorable element per screen: the book. No decorative shadows elsewhere.
- Borders encode meaning: solid ink = a card; dashed = page fold; stamp-green = available.
- Demo data is always labelled. The footer "Not an NLB product" never moves.
- If you add motion, it must answer a user action; no idle animation.
