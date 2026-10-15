# PreReads: full guide

The short version is in the [README](../README.md). This guide has the details: setup, modes, data sources, API, adding titles, tests and troubleshooting.

**Say what you want to read. PreReads finds catalogue-verified books and the ones to read before them.**
Your reading path shows each book's reading level, hours, the shelf status per library, and floor-plan directions to the shelf.

Demo video: https://youtu.be/q-sLmH-rzR0
Design: [Figma screens with desktop and phone clickable prototypes](https://www.figma.com/design/c5wM6zZUx2NT91NIEYwbFZ) and [FigJam architecture diagrams](https://www.figma.com/board/5TEfAaBhbQFeLO91qIPSuP)

PreReads uses open-source AI models via Ollama.

Built for the Common Ground makeathon (Design × Tech), Singapore, 11 Oct 2026, by team
"404 Not Found". Not an NLB product. Book data comes from Open Library, library
locations and opening hours from NLB open data (data.gov.sg), and digital copies from NLB's
OverDrive catalogue. Per-branch copies, call numbers and queues come from the NLB Catalogue
API when its keys are set (see [Data sources](#data-sources)).

---

## 1. Setup

Requirements: Python 3.11+, Node 18+, macOS/Linux. Ollama is optional but recommended:
without it the app still runs, using built-in heuristics and the cached reading paths
(scan and fresh AI picks are then unavailable).

```bash
cd prereads            # the cloned repository
make setup            # python venv + pip deps, npm deps (copies .env.example to .env if .env is missing)
make precompute-demo  # optional: rebuild the cached reading paths offline (DEMO=1, no AI needed)
make serve            # builds the UI, then serves API + UI on http://localhost:8000
```

Open http://localhost:8000, or from a phone on the same Wi-Fi use
`http://<your-lan-ip>:8000` (`make serve` binds 0.0.0.0).

For the AI features, install Ollama and pull the models once:

```bash
ollama pull gpt-oss:20b         # discovery, reading levels, path judgments
ollama pull gemma3:12b          # chat and answers, and the fallback for any missing model
ollama pull qwen2.5vl:7b        # cover scan
ollama pull nomic-embed-text    # semantic search, "Because you liked..."
# optional: gpt-oss:120b is the heavy model for precompute and eval; it is picked up automatically
```

Voice input uses `faster-whisper` (large-v3-turbo) and the natural voice uses `kokoro-onnx`;
both are optional (`backend/.venv/bin/pip install -r backend/requirements-optional.txt`),
and the browser's own speech is the fallback.

For development with hot reload run two terminals:

```bash
make backend   # FastAPI on :8000 with --reload
make frontend  # Vite on :5173, proxies /api to :8000
```

### Run

`scripts/setup.py` (Python stdlib only) runs the app as a background service, so you do
not need a terminal tab for it.

```bash
python3 scripts/setup.py doctor    # check Python/Node, Ollama + models, ports, optional speech packages
python3 scripts/setup.py install   # backend/.venv + pip install, npm install + build
python3 scripts/setup.py start     # ensure Ollama, rebuild the UI if stale, serve in the background
python3 scripts/setup.py status    # pid, port, /api/health, Ollama models loaded
python3 scripts/setup.py logs      # follow .run/app.log
python3 scripts/setup.py restart   # or: stop
python3 scripts/setup.py dev       # backend --reload on :8000 + Vite on :5173, Ctrl+C stops both
```

`start` prints the app URL and, when bound to the LAN (`PREREADS_HOST=0.0.0.0`), the LAN
URL for a phone on the same Wi-Fi. Env: `PREREADS_HOST` (default `127.0.0.1`),
`PREREADS_PORT` (default `8000`). Ollama settings and model names come from `.env` or the
environment (`OLLAMA_BASE_URL`, `LOCAL_LLM_MODEL`, `LOCAL_CHAT_MODEL`, `LOCAL_LLM_MODEL_HEAVY`,
`LOCAL_VISION_MODEL`, `LOCAL_EMBED_MODEL`); `doctor` shows which models are pulled and which
fallback (for example `gemma3:12b`) the app would use. A missing `gpt-oss` model is a warning,
not an error. `faster-whisper` and `kokoro-onnx` (speech) are reported as optional.
If Ollama is not running, `start` launches `ollama serve` in the background; `stop` does not
stop Ollama. PID and logs live in `.run/` (git-ignored).

## 2. Modes

The AI provider is Ollama by default (`AI_PROVIDER=ollama`). Switch the data mode at runtime
from the settings chip on the home screen (Settings sheet): **Demo data** or **Live**, plus the shelf-data source.
`/api/mode` backs it; `.env` sets the default at startup. `AI_PROVIDER=openai` with
`OPENAI_API_KEY` is an optional alternative, not the default.

| Mode | `.env` | What works |
|---|---|---|
| Offline | `DEMO=1` | Everything from the cache: search, path, cards, ask (templates), walk-in, share card. Scan is disabled with a typed fallback. |
| Ollama (default) | `AI_PROVIDER=ollama`, Ollama running | Live readiness scoring, prerequisite judgments, discovery, cover scan, embeddings, grounded answers. Metadata from Open Library. |
| No Ollama | nothing | Heuristics plus cached paths. Typed search of cached and catalogue titles still works. |
| NLB open data | `DATA_SOURCE=dataset` (or `auto` with `backend/data/nlb/` present) | Opening hours and NLB's yearly loan totals from NLB open data. |
| NLB Catalogue API | + `NLB_API_KEY`, `NLB_APP_CODE` | Per-branch availability and call numbers; demand from the checkout-trends endpoint. |

Switch modes by editing `.env` and restarting. After adding keys, rebuild the cache:

```bash
make precompute       # --refresh with the configured models; ~20–60 s per title
```

### Data sources

Shelf data comes from one of three sources, set by `DATA_SOURCE` in `.env` (`auto` by default)
or at runtime from **Settings → Shelf data** (`POST /api/mode {"data_source": ...}`):

| Source | What it gives |
|---|---|
| `api` | NLB Catalogue v2: per-branch copies, call numbers, checkout trends. Needs `NLB_API_KEY` + `NLB_APP_CODE`. |
| `dataset` | NLB open data in `backend/data/nlb/`: opening hours from the nlb.gov.sg library pages ("Hours from NLB, checked <date>"), and all-of-NLB yearly loans and digital use ("NLB in <year>: …"; data.gov.sg, Singapore Open Data Licence). Open data has no per-title or per-branch loans, so per-title copies and "Popular right now" come from the built-in table. |
| `demo` | The built-in, deterministic table only. |

`auto` picks `api` when both NLB keys are set, else `dataset` when `backend/data/nlb/` has files, else `demo`.
Rebuild the open data with `cd backend && .venv/bin/python scripts/fetch_nlb_datasets.py`
(set `DATAGOV_API_KEY` to avoid rate limits; Playwright, if installed, reads the hours), then
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
| `GET /api/suggestions?lang=&n=` | example requests for the home screen, drawn from the catalogue |
| `GET /api/browse?by=`, `GET /api/targets`, `GET /api/popular` | browse by author or category, seed targets, popular picks |
| `POST /api/ask` `{target_id, intent, weeks}` | `why_before` / `time_budget` / `large_print` |
| `POST /api/chat`, `POST /api/chat/stream` | guided chat; the stream sends its real steps as they happen |
| `POST /api/scan` (multipart `image`) | cover/spine to title/author via the vision model |
| `POST /api/stt`, `POST /api/tts` | speech to text and text to speech |
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
make test   # backend pytest + frontend vitest
```

`make warmup` loads the Ollama models and fills the caches against a running app (`QUICK=1`
for the five showcase paths only). `make eval` re-scores the cached paths with the heavy
model and reports rule violations and low-confidence hops (read-only).

## 7. Troubleshooting

- **`/api/route` 404 with `DEMO=1`** — the title is not cached. Run `make precompute-demo`
  or pick a suggested title.
- **Scan returns 503** — `DEMO=1`, or Ollama is not running or `qwen2.5vl:7b` is not pulled. Type the title.
- **Phone can't reach the app** — run `make serve` (binds 0.0.0.0) and use the computer's
  LAN IP; or use a hotspot if the Wi-Fi blocks peer traffic.
- **Fonts look different** — Atkinson Hyperlegible loads from Google Fonts; offline it
  falls back to the system sans-serif.
- **Slow or missing AI answers** — run `python3 scripts/setup.py doctor` to see which Ollama
  models are pulled; a missing preferred model falls back to an installed one (for example `gemma3:12b`).

## 8. Screens

**Ways in (Home):** **Tell me what you want** (AI discovery: your sentence → a structured
need — topic, level, time budget, age, language, mood — → real books proposed by the
model and verified in the catalogue → ranked by fit, with filter chips *generated from
your request* that re-rank instantly) · I know the title · Scan or upload a cover. Plus
**Ask PreReads**, a guided chat on every screen that ends in one-tap directions.
In offline mode (`DEMO=1`) the need is parsed by built-in rules and candidates come from the
cached paths; with a model the model parses and proposes, and new books get their path built
when opened. Semantic search and "Because you liked..." use `nomic-embed-text`.

**Find it on the shelf (Book):** a floor-plan schematic (doors, counter, self-checkout,
non-fiction bays with shelf lines in Dewey order, fiction stacks, children's corner,
magazines, reading tables, lift) with an animated route from the entrance, a walker, a
pulsing pin, and emoji-led steps. Derived from the call number; labelled "not to scale".

Home (pick a book) → Your reading path (vertical route, mark books read; "You" and "At" chips open
familiarity and library sheets; share sheet) → Book (page-turn, reader-facing status —
Available / Nearest copy / Waiting — then schematic directions from the entrance to the
bay with the call number to look for; bottom bar: Reserve or Mark read · Find on shelf · Ask).
Meet at the book (`#/meet`) puts two readers on one target. Hash routes (`#/line?id=…`) so the back button works in
browsers and WebViews, and any line is linkable.

## 9. Voice

Every book, path and set of picks has a **Listen** button; the discovery box and the chat have
a mic for voice input. Speech-to-text is `faster-whisper` large-v3-turbo (`/api/stt`) and the
natural voice is Kokoro (`/api/tts`, cached), both open source. If either is missing the
browser's built-in speech is used, so it still works.

## 10. Web first, mobile later

The UI is one responsive web app: phone layout below 760px, two-column layout above it,
no horizontal page scroll (only the reading path scrolls). It ships a PWA manifest and
icons, respects safe areas, and is WebView-safe (camera via file input, share-card
preview when downloads are blocked). To wrap it as a mobile app later, use a WebView wrapper such as Capacitor. For a split deploy (UI on a CDN, API elsewhere) build with
`VITE_API_BASE=https://your-api.example.com npm run build`.

## 11. Project files

- `backend/app/README.md` — backend package map and request flow. The backend is layered:
  `api/` (FastAPI routers) → `services/` (reading-path engine, discovery, chat, ask) →
  `integrations/` (NLB, NLB open data, Open Library, OverDrive, Gutenberg, availability) and `ai/` (LLM, embeddings,
  speech) → `core/` (config, models). Entry point stays `app.main:app`.

## Credits and data sources

- [Open Library](https://openlibrary.org): catalogue checks, descriptions, subjects, covers and Dewey classes (data released under CC0).
- [data.gov.sg](https://data.gov.sg): NLB library locations and NLB open datasets (Singapore Open Data Licence).
- NLB's digital collection via its public OverDrive catalogue (`thunder.api.overdrive.com`): eBook and audiobook copies, holds and publisher samples. Light, cached, user-triggered lookups; not an official integration.
- [Project Gutenberg](https://www.gutenberg.org) via [Gutendex](https://gutendex.com): public-domain texts for "read the first chapter".
- Open-source models via [Ollama](https://ollama.com) (gpt-oss, Gemma 3, Qwen2.5-VL, nomic-embed-text), [faster-whisper](https://github.com/SYSTRAN/faster-whisper) and [Kokoro](https://github.com/thewh1teagle/kokoro-onnx), each under its own licence.
- Fonts: Atkinson Hyperlegible, Fraunces, Noto Sans SC and Noto Sans Tamil from Google Fonts (SIL Open Font License).

PreReads is not an NLB product.

