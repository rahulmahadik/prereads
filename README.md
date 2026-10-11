# PreReads

**AI book recommendations, and the books to read before the one you want.**

Scan or type a book. PreReads draws a reading line: the books that prepare you for
it, the book itself, and where to go next — each stop with a readiness level, hours
to read, why it is on the line, and which NLB branch has it on the shelf today.

Built for the Common Ground makeathon (Design × Tech), Singapore, 11 Oct 2026.
Not an NLB product; built on NLB Labs open APIs and Open Library.

---

## 1. Local setup (10 minutes)

Requirements: Python 3.11+, Node 18+, macOS/Linux.

```bash
git clone <your-repo-url> prereads && cd prereads
make setup            # python venv + pip deps, npm deps, copies .env.example -> .env
make precompute-demo  # builds the 22 cached routes offline (no keys needed)
make serve            # http://localhost:8000  (API + built UI in one process)
```

Open http://localhost:8000 on your laptop, or from your phone on the same Wi-Fi
use `http://<your-mac-ip>:8000`.

For development with hot reload run two terminals:

```bash
make backend   # FastAPI on :8000 with --reload
make frontend  # Vite on :5173, proxies /api to :8000
```

## 2. Modes

Switch at runtime from the ⚙️ chip on the home screen (Data mode sheet): **Demo data**
or **Real calls**, with per-source toggles for OpenAI and NLB once their keys are in
`.env`. The sheet also shows which keys are connected. `/api/mode` backs it; `.env`
sets the default at startup.

| Mode | `.env` | What works |
|---|---|---|
| Offline demo | `DEMO=1` | Everything from the cache: search, line, cards, ask (templates), walk-in, share card. Scan is disabled with a typed fallback. |
| OpenAI only | `DEMO=0`, `OPENAI_API_KEY` | Live readiness scoring, prerequisite judgments, cover scan, grounded "ask the line". Metadata from Open Library. Availability/demand from the labelled demo table. |
| Fully live | + `NLB_API_KEY`, `NLB_APP_CODE` | Real per-branch availability and call numbers; demand from the checkout-trends endpoint. |

Switch modes by editing `.env` and restarting. After adding keys, rebuild the cache:

```bash
make precompute       # --refresh with live engines; ~20–60 s per title with the LLM
```

## 3. Getting the NLB key

Apply at https://go.gov.sg/nlblabs-form (NLB Labs). Approval comes by email with an
**API key and an App Code** (6 months validity); both go in `.env`. Then:

```bash
cd backend && . .venv/bin/activate && python scripts/nlb_check.py "Thinking, Fast and Slow"
```

prints what each endpoint returns for one title. The client is written against the
Catalogue v2 OpenAPI contract: `GetTitles` (Title + Author, ANDed) with `SearchTitles`
(Keywords) as fallback, `GetTitleDetails` (BRN/ISBN), `GetAvailabilityInfo` (items with
`location{code,name}`, `status{name,code}`, `formattedCallNumber`), and
`GetMostCheckoutsTrendsTitles` (`LocationCode`, `Duration=past30days`). Title records
also carry `activeReservationsCount`, which the UI shows as the queue length.

If the key has not arrived by the event, stay in OpenAI-only mode. The UI labels
availability as demo data; say so in the video.

## 4. API

| Endpoint | Purpose |
|---|---|
| `GET /api/health` | mode + cached route count |
| `GET /api/resolve?q=` | title search (cache first, then catalogue) |
| `GET /api/route?id=` | the line for a target id (ISBN-13 or `ol:` slug); builds and caches if missing (not in DEMO) |
| `POST /api/scan` (multipart `image`) | cover/spine → title/author via vision model |
| `POST /api/ask` `{target_id, intent, weeks}` | `why_before` / `time_budget` / `large_print` |
| `GET /api/branches` | branch list for walk-in mode |
| `GET /api/targets` | seed targets |

## 5. Adding titles

Edit `backend/data/targets.json`. A target needs `title`, `author`, `level`,
`hours`, `one_line`, and optional `before`/`after` picks (these are the
librarian-verified seeds; the LLM adds more in live mode). Then:

```bash
cd backend && . .venv/bin/activate && python scripts/precompute.py --only "part of title" --refresh
```

Every candidate must resolve in a catalogue or it is dropped — check the `notes`
in the route JSON if a pick disappears.

## 6. Tests

```bash
make test
```

## 7. Troubleshooting

- **`/api/route` 404 in demo mode** — the title is not cached. Run `make precompute-demo`
  or pick a suggested title.
- **Scan returns 503** — `DEMO=1` or no `OPENAI_API_KEY`. Type the title.
- **Phone can't reach the app** — run `make serve` (binds 0.0.0.0) and use your Mac's
  LAN IP; or share your Mac's hotspot if venue Wi-Fi blocks peer traffic.
- **Fonts look different** — Atkinson Hyperlegible loads from Google Fonts; offline it
  falls back to system sans. Fine for the demo.
- **Model name error from OpenAI** — set `OPENAI_MODEL` in `.env` to a model string you
  can see in your dashboard.

## 8. Screens

**Ways in (Home):** **Tell me what you want** (AI discovery: your sentence → a structured
need — topic, level, time budget, age, language, mood — → real books proposed by the
model and verified in the catalogue → ranked by fit, with filter chips *generated from
your request* that re-rank instantly) · I know the title · Scan or upload a cover. Plus
**Ask PreReads**, a guided chat on every screen that ends in one-tap directions.
In demo mode the need is parsed by built-in rules and candidates come from the cached
lines; with `OPENAI_API_KEY` the model parses and proposes, and new books get their
line built when opened.

**Find it on the shelf (Book):** a floor-plan schematic (doors, counter, self-checkout,
non-fiction bays with shelf lines in Dewey order, fiction stacks, children's corner,
magazines, reading tables, lift) with an animated route from the entrance, a walker, a
pulsing pin, and emoji-led steps. Derived from the call number; labelled "not to scale".

Home (pick a book) → Your line (vertical route, mark books read; "You" and "At" chips open
familiarity and library sheets; share sheet) → Book (page-turn, reader-facing status —
Available / Nearest copy / Waiting — then schematic directions from the entrance to the
bay with the call number to look for; bottom bar: Reserve or Mark read · Find on shelf · Ask).
The Ready screen still exists for deep links but is no longer in the default path. Hash routes (`#/line?id=…`) so the back button works in
browsers and WebViews, and any line is linkable.

## 9. Natural voice

Every book, line and set of picks has a **Listen** button; the discovery box and the chat
have a **🎤** for voice input, and the chat can read its replies aloud. With
`OPENAI_API_KEY` the voice is OpenAI's TTS (warm-librarian style, cached as MP3);
without it the browser's built-in voice is used, so it works in the prototype too.
See `docs/GAPS_VS_NLB.md` for how this maps to what NLB's portals lack.

## 10. Web first, mobile later

The UI is one responsive web app: phone layout below 760px, two-column layout above it,
no horizontal page scroll (only the reading line scrolls). It ships a PWA manifest and
icons, respects safe areas, and is WebView-safe (camera via file input, share-card
preview when downloads are blocked). To wrap it as a mobile app later, see
`docs/MOBILE_SHELL.md`. For a split deploy (UI on a CDN, API elsewhere) build with
`VITE_API_BASE=https://your-api.example.com npm run build`.

## 11. Project files

- `AGENTS.md` — Codex working contract and build-day task list
- `docs/PLAN.md` — hour-by-hour plan, roles, risks
- `docs/DEMO_SCRIPT.md` — 60-second video and finalist pitch
- `docs/PROMPTS.md` — prompt contracts and sanity rules
- `docs/MOBILE_SHELL.md` — wrapping the web app in a WebView (Capacitor) later
- `docs/BACKLOG.md` — prioritised feature backlog after the build
- `docs/GAPS_VS_NLB.md` — what NLB's portals lack and how PreReads fills it
- `docs/CODE_REVIEW.md` — static end-to-end code review findings
- `design/figma/README.md` — importable mobile screens and Mobbin handoff
