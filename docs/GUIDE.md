# PreReads: full guide

The short version is in the [README](../README.md). This guide has the details: setup, modes, data sources, API, adding titles, tests and troubleshooting.

**Say what you want to read. PreReads finds catalogue-verified books and the ones to read before them.**
Your reading path shows each book's reading level, hours, the shelf status per library, and floor-plan directions to the shelf.

Live demo: https://prereads.vitbhatti.com
Design: [Figma screens with desktop and phone clickable prototypes](https://www.figma.com/design/c5wM6zZUx2NT91NIEYwbFZ) and [FigJam architecture diagrams](https://www.figma.com/board/5TEfAaBhbQFeLO91qIPSuP)

All AI runs locally on-device (open models via Ollama), with no cloud AI calls by default.

Built for the Common Ground makeathon (Design × Tech), Singapore, 11 Oct 2026, by team
"404 Not Found". Not an NLB product. Book data comes from Open Library, library
locations and opening hours from NLB open data (data.gov.sg), and digital copies from NLB's
OverDrive catalogue. Per-branch shelf copies, queue lengths and "popular" trends are demo
data until an NLB Catalogue API key is added.

---

## 1. Local setup (10 minutes)

Requirements: Python 3.11+, Node 18+, macOS/Linux. Ollama is optional but recommended:
without it the app still runs, using built-in heuristics and the cached reading paths
(scan, voice and fresh AI picks are then unavailable).

```bash
cd prereads            # the cloned repository
make setup            # python venv + pip deps, npm deps (copies .env.example to .env if that file exists)
make precompute-demo  # optional: rebuild the cached reading paths offline (DEMO=1, no AI needed)
make serve            # builds the UI, then serves API + UI on http://localhost:8000
```

Open http://localhost:8000 on your laptop, or from your phone on the same Wi-Fi
use `http://<your-mac-ip>:8000` (`make serve` binds 0.0.0.0).

For the full local AI stack, install Ollama and pull the models once:

```bash
ollama pull gpt-oss:20b         # chat, discovery, answers (the default model)
ollama pull gemma3:12b          # reading levels, judgments, and the fallback for any missing model
ollama pull qwen2.5vl:7b        # cover scan
ollama pull nomic-embed-text    # semantic search, "Because you liked..."
# optional: gpt-oss:120b is the heavy model for precompute and judging; it is picked up automatically
```

Voice input uses `faster-whisper` (large-v3-turbo) and the natural voice uses `kokoro-onnx`;
both are optional, and the browser's own speech is the fallback.

For development with hot reload run two terminals:

```bash
make backend   # FastAPI on :8000 with --reload
make frontend  # Vite on :5173, proxies /api to :8000
```

### Run and share

`scripts/setup.py` (Python stdlib only) runs the app as a background service, so you do
not need a terminal tab for it. `scripts/tunnel.sh` puts it on the internet.

```bash
python3 scripts/setup.py doctor    # check Python/Node, Ollama + models, ports, optional speech packages
python3 scripts/setup.py install   # backend/.venv + pip install, npm install + build
python3 scripts/setup.py start     # ensure Ollama, rebuild the UI if stale, serve in the background
python3 scripts/setup.py status    # pid, port, /api/health, Ollama models loaded
python3 scripts/setup.py logs      # follow .run/app.log
python3 scripts/setup.py restart   # or: stop
python3 scripts/setup.py dev       # backend --reload on :8000 + Vite on :5173, Ctrl+C stops both
```

`start` prints the local URL and, when bound to the LAN (`PREREADS_HOST=0.0.0.0`), the LAN
URL for a phone on the same Wi-Fi. Env: `PREREADS_HOST` (default `127.0.0.1`),
`PREREADS_PORT` (default `8000`). Ollama settings and model names come from `.env` or the
environment (`OLLAMA_BASE_URL`, `LOCAL_LLM_MODEL`, `LOCAL_LLM_MODEL_HEAVY`,
`LOCAL_VISION_MODEL`, `LOCAL_EMBED_MODEL`); `doctor` shows which models are pulled and which
fallback (for example `gemma3:12b`) the app would use. A missing `gpt-oss` model is a warning,
not an error. `faster-whisper` and `kokoro-onnx` (local speech) are reported as optional.
If Ollama is not running, `start` launches `ollama serve` in the background; `stop` does not
stop Ollama. PID and logs live in `.run/` (git-ignored).

To share the running app outside your network with Cloudflare:

```bash
bash scripts/tunnel.sh quick    # no account: prints a random https://<words>.trycloudflare.com URL
bash scripts/tunnel.sh setup    # one-time: named tunnel "prereads" + DNS prereads.vitbhatti.com
bash scripts/tunnel.sh          # run the named tunnel (status: bash scripts/tunnel.sh status)
```

Needs `cloudflared` (`brew install cloudflare/cloudflare/cloudflared`). Override with
`PREREADS_TUNNEL`, `PREREADS_HOSTNAME` and `PREREADS_PORT`. Anyone with the link can use the
app, so stop the tunnel (Ctrl+C) when you are done.

## 2. Modes

The AI provider is local by default (`AI_PROVIDER=ollama`). Switch the data mode at runtime
from the settings chip on the home screen (Settings sheet): **Demo data** or **Real calls**, plus the shelf-data source.
`/api/mode` backs it; `.env` sets the default at startup. `AI_PROVIDER=openai` with
`OPENAI_API_KEY` is an optional alternative, not the default.

| Mode | `.env` | What works |
|---|---|---|
| Offline demo | `DEMO=1` | Everything from the cache: search, path, cards, ask (templates), walk-in, share card. Scan is disabled with a typed fallback. |
| Local AI (default) | `AI_PROVIDER=ollama`, Ollama running | Live readiness scoring, prerequisite judgments, discovery, cover scan, embeddings, grounded answers, all on local models. Metadata from Open Library. Shelf copies from the labelled demo table. |
| No Ollama | nothing | Heuristics plus cached paths. Typed search of cached and catalogue titles still works. |
| NLB open data | `DATA_SOURCE=dataset` (or `auto` with `backend/data/nlb/` present) | Real opening hours and NLB's yearly loan totals; per-branch copies, queues and popularity stay labelled demo. |
| Fully live shelves | + `NLB_API_KEY`, `NLB_APP_CODE` | Real per-branch availability and call numbers; demand from the checkout-trends endpoint. |

Switch modes by editing `.env` and restarting. After adding keys, rebuild the cache:

```bash
make precompute       # --refresh with the local models; ~20–60 s per title
```

### Data sources

Shelf data comes from one of three sources, set by `DATA_SOURCE` in `.env` (`auto` by default)
or at runtime from **Settings → Shelf data** (`POST /api/mode {"data_source": ...}`):

| Source | What it gives | Label in the UI |
|---|---|---|
| `api` | NLB Catalogue v2: per-branch copies, call numbers, checkout trends. Needs `NLB_API_KEY` + `NLB_APP_CODE`. | none (live) |
| `dataset` | NLB open data in `backend/data/nlb/`: real opening hours from the nlb.gov.sg library pages, and all-of-NLB yearly loans and digital use (data.gov.sg, Singapore Open Data Licence). No per-title or per-branch loans exist as open data, so copies and "Popular right now" stay demo. | "Hours from NLB, checked <date>", "NLB in <year>: …" |
| `demo` | The deterministic demo table. | "(demo data)" |

`auto` picks `api` when both NLB keys are set, else `dataset` when `backend/data/nlb/` has files, else `demo`.
Rebuild the open data with `cd backend && .venv/bin/python scripts/fetch_nlb_datasets.py`
(set `DATAGOV_API_KEY` to avoid rate limits; Playwright reads the hours), then
`.venv/bin/python scripts/fetch_libraries.py --hours-only` to copy the hours into `libraries.json`.

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

Without the key, per-branch shelf copies, queues and popularity are demo data (labelled in Settings and next to the numbers), and the README says so.

## 4. API

All routes live under `/api`.

| Endpoint | Purpose |
|---|---|
| `GET /api/health` | mode + cached route count |
| `GET /api/mode`, `POST /api/mode` | read or change demo, AI and NLB switches and `data_source` (`auto|demo|dataset|api`) at runtime |
| `GET /api/resolve?q=&offset=&limit=` | title search (cache first, then catalogue), paged |
| `GET /api/route?id=` | the reading path for a target id (ISBN-13 or `ol:` slug); builds and caches if missing (not in DEMO); `refresh=true` rebuilds |
| `POST /api/discover` | "tell me what you want": need, ranked verified books, filter chips, paging; `mode` fast or deep |
| `GET /api/similar?id=&branch=` | "Because you liked...": embedding neighbours with a reason |
| `GET /api/browse`, `GET /api/targets`, `GET /api/popular` | browse by category, seed targets, popular picks |
| `POST /api/ask` `{target_id, intent, weeks}` | `why_before` / `time_budget` / `large_print` |
| `POST /api/chat`, `POST /api/chat/stream` | guided chat; the stream sends its real steps as they happen |
| `POST /api/scan` (multipart `image`) | cover/spine to title/author via the vision model |
| `POST /api/stt`, `POST /api/tts` | local speech to text and text to speech |
| `GET /api/digital?title=&author=` | NLB eBook and audiobook copies (OverDrive) |
| `GET /api/online?title=&author=`, `GET /api/online/chapter?gutenberg_id=` | free online editions and the first chapter of public-domain books |
| `GET /api/branches` | libraries with location, hours and distance data |

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
make test   # backend pytest (101 tests) + frontend vitest (56 tests)
```

`make warmup` loads the local models and fills the caches before a demo (`QUICK=1` for the demo paths only).
`make eval` re-scores the cached paths with the heavy local model and reports rule
violations and low-confidence hops (read-only).

## 7. Troubleshooting

- **`/api/route` 404 in demo mode** — the title is not cached. Run `make precompute-demo`
  or pick a suggested title.
- **Scan returns 503** — `DEMO=1`, or Ollama is not running or `qwen2.5vl:7b` is not pulled. Type the title.
- **Phone can't reach the app** — run `make serve` (binds 0.0.0.0) and use your Mac's
  LAN IP; or share your Mac's hotspot if venue Wi-Fi blocks peer traffic.
- **Fonts look different** — Atkinson Hyperlegible loads from Google Fonts; offline it
  falls back to system sans. Fine for the demo.
- **Slow or missing AI answers** — run `python3 scripts/setup.py doctor` to see which Ollama
  models are pulled; a missing preferred model falls back to an installed one (for example `gemma3:12b`).

## 8. Screens

**Ways in (Home):** **Tell me what you want** (AI discovery: your sentence → a structured
need — topic, level, time budget, age, language, mood — → real books proposed by the
model and verified in the catalogue → ranked by fit, with filter chips *generated from
your request* that re-rank instantly) · I know the title · Scan or upload a cover. Plus
**Ask PreReads**, a guided chat on every screen that ends in one-tap directions.
In demo mode the need is parsed by built-in rules and candidates come from the cached
paths; with a local model the model parses and proposes, and new books get their path built
when opened. Semantic search and "Because you liked..." use `nomic-embed-text`.

**Find it on the shelf (Book):** a floor-plan schematic (doors, counter, self-checkout,
non-fiction bays with shelf lines in Dewey order, fiction stacks, children's corner,
magazines, reading tables, lift) with an animated route from the entrance, a walker, a
pulsing pin, and emoji-led steps. Derived from the call number; labelled "not to scale".

Home (pick a book) → Your reading path (vertical route, mark books read; "You" and "At" chips open
familiarity and library sheets; share sheet) → Book (page-turn, reader-facing status —
Available / Nearest copy / Waiting — then schematic directions from the entrance to the
bay with the call number to look for; bottom bar: Reserve or Mark read · Find on shelf · Ask).
The Ready screen still exists for deep links but is no longer in the default path. Meet at the book (`#/meet`) puts two readers on one target. Hash routes (`#/line?id=…`) so the back button works in
browsers and WebViews, and any line is linkable.

## 9. Voice

Every book, path and set of picks has a **Listen** button; the discovery box and the chat have
a mic for voice input. Speech-to-text is `faster-whisper` large-v3-turbo (`/api/stt`) and the
natural voice is Kokoro (`/api/tts`, cached), both on the laptop. If either is missing the
browser's built-in speech is used, so it still works. See `docs/GAPS_VS_NLB.md`.

## 10. Web first, mobile later

The UI is one responsive web app: phone layout below 760px, two-column layout above it,
no horizontal page scroll (only the reading path scrolls). It ships a PWA manifest and
icons, respects safe areas, and is WebView-safe (camera via file input, share-card
preview when downloads are blocked). To wrap it as a mobile app later, see
`docs/MOBILE_SHELL.md`. For a split deploy (UI on a CDN, API elsewhere) build with
`VITE_API_BASE=https://your-api.example.com npm run build`.

## 11. Project files

- `backend/app/README.md` — backend package map and request flow. The backend is layered:
  `api/` (FastAPI routers) → `services/` (reading-path engine, discovery, chat, ask) →
  `integrations/` (NLB, NLB open data, Open Library, OverDrive, Gutenberg, availability) and `ai/` (LLM, embeddings,
  speech) → `core/` (config, models). Entry point stays `app.main:app`.
- `docs/DEMO_SCRIPT.md` — 60-second video shot list, finalist pitch
- `docs/PROMPTS.md` — prompt contracts and sanity rules
- `docs/MOBILE_SHELL.md` — wrapping the web app in a WebView (Capacitor) later
- `docs/BACKLOG.md` — prioritised feature backlog after the build
- `docs/GAPS_VS_NLB.md` — what NLB's portals lack and how PreReads fills it

## Credits and data sources

- [Open Library](https://openlibrary.org): catalogue checks, descriptions, subjects, covers and Dewey classes (data released under CC0).
- [data.gov.sg](https://data.gov.sg): NLB library locations and NLB open datasets (Singapore Open Data Licence).
- NLB's digital collection via its public OverDrive catalogue (`thunder.api.overdrive.com`): eBook and audiobook copies, holds and publisher samples. Light, cached, user-triggered lookups; not an official integration.
- [Project Gutenberg](https://www.gutenberg.org) via [Gutendex](https://gutendex.com): public-domain texts for "read the first chapter".
- Local models via [Ollama](https://ollama.com) (gpt-oss, Gemma 3, Qwen2.5-VL, nomic-embed-text), [faster-whisper](https://github.com/SYSTRAN/faster-whisper) and [Kokoro](https://github.com/thewh1teagle/kokoro-onnx), each under its own licence.
- Fonts: Atkinson Hyperlegible, Fraunces, Noto Sans SC and Noto Sans Tamil from Google Fonts (SIL Open Font License).

PreReads is not an NLB product. Shelf availability, queue lengths and trends are demo data unless NLB Catalogue API keys are configured.

