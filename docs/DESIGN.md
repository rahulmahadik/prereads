# PreReads — design system (for the designer on the day)

## Screens (hash-routed, back button works in browsers and WebViews)
| # | Screen | Job | Primary action |
|---|---|---|---|
| 1 | Home `#/` | Pick the book | Scan the cover / Type the title; quick-pick shelf |
| 2 | Ready `#/ready` | One question: how familiar are you | Three big choices, or skip |
| 3 | Line `#/line` | See the road, track progress | Tap a book; tap a circle to mark read; sheets for walk-in and share |
| 4 | Book `#/book` | Decide on one book | Find on NLB; Ask about this line (sheet); swipe/‹ › to turn |

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

## v2 tokens (overrides at the end of styles.css)
paper #F3F6F9 · surface #FFF · surface-2 #E9EEF5 · ink #0E1A24 · accent #1F5EFF ·
available #0E9F6E · elsewhere #C47A0A · waiting #E2493B · radius 14/20 · pill controls ·
one soft shadow. Status blocks are tonal (green/amber/red backgrounds), never raw counts.

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
