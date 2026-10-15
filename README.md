# PreReads

**Search, plan and manage your library reading from a few words.**

🏆 **People's Choice Award (Culture × Tech)** and **Top 4 finalist** at [Common Ground](https://luma.com/yjffwqr2), a one-day creative tech and AI makeathon in Singapore (11 October 2026), built solo among 100+ participants and 38+ teams. [All projects](https://thisisshaw-04.github.io/Common-Ground-Makeathon/).

Readers spend more time finding books than reading them: searching catalogues, guessing what to read first, then hunting for the right rack. Describe what you want and PreReads finds real library books, builds *your reading path* (easier books first, then your book, then what to read next), keeps your shelf, notes and progress, and shows where each book is at your library today.

- **Demo video:** https://youtu.be/q-sLmH-rzR0
- **No-server prototype:** [`docs/index.html`](docs/index.html) (embedded data, works offline)
- **Design:** [Figma screens and clickable prototype](https://www.figma.com/design/c5wM6zZUx2NT91NIEYwbFZ) (desktop and phone) · [architecture board](https://www.figma.com/board/5TEfAaBhbQFeLO91qIPSuP)
- **Architecture:** [diagram below](#architecture) · [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md)

Built solo by Rahul Mahadik on open data (Open Library, NLB open data on data.gov.sg, NLB's eBook catalogue, Project Gutenberg) and open-source AI models (via Ollama).

| | | |
|:---:|:---:|:---:|
| <img src="docs/screenshots/home.jpg" width="220" alt="Home"><br>Search in a few words | <img src="docs/screenshots/discover.jpg" width="220" alt="Discovery results ranked by AI"><br>Real books, ranked by AI | <img src="docs/screenshots/path.jpg" width="220" alt="Reading path with same-shelf trip"><br>Your reading path |
| <img src="docs/screenshots/book.jpg" width="220" alt="Book page"><br>About the book and where it is | <img src="docs/screenshots/map.jpg" width="220" alt="Shelf map"><br>Walk to the shelf | <img src="docs/screenshots/chat.jpg" width="220" alt="Chat with steps"><br>Chat that shows its steps |

## What it does
- 🔎 **Find**: describe what you want, say it, scan a book cover or type a title. Real library books only, with AI picks and the reason for each. "Because you liked…" suggests similar books.
- 🧭 **Plan**: *your reading path*. Easier PreReads first, then your book, then NextReads, each with a reading level, hours and a reason. Rules are enforced in code: before-books must be easier, confidence ≥ 0.6, at most 3 before and 3 after, one author per before-path, and no book appears twice.
- 📍 **Go**: shelf status at your branch (available, nearest copy or waiting list), the nearest library with opening hours, reserve or waitlist links, and an animated map to the exact bay and row. Several books on one shelf? One trip ("3 of your PreReads are on the same shelf (332)").
- 📖 **Read**: a publisher sample or the first chapter in the app (public-domain books), live eBook and audiobook copies from NLB's digital collection on Libby, and **Listen** to hear any book or path read aloud.
- 💬 **Ask**: a chat that suggests options, streams the steps it really runs (understanding, searching, ranking, checking shelves) and remembers what you said. Ask in any language and get English books.
- ❤️ **Keep**: My shelf with notes and progress (PreReads marked as read, hours left), share a path by QR code, Meet at the book (read it with a friend), printable A6 shelf cards.
- 🌏 **For everyone**: English, 中文, Bahasa Melayu and தமிழ் · light, dark and reading themes · larger text · voice in and out · works offline once opened · phone and desktop.

## Tech stack
| Layer | Technology |
|---|---|
| Frontend | React 18 + TypeScript, Vite, hand-written CSS tokens (no UI library), service worker (PWA), vitest |
| Animation | CSS keyframes and SVG path drawing (reading path, walk to the shelf), honouring `prefers-reduced-motion` |
| Backend | Python 3.11+, FastAPI, Pydantic v2, httpx, pytest |
| AI (open-source models via Ollama) | gpt-oss:20b (discovery, reading levels, path judgments), gemma3:12b (chat, and fallback for any missing model), gpt-oss:120b (optional heavy model for precompute and eval), qwen2.5vl:7b (cover scan), nomic-embed-text (semantic search); optional OpenAI via `AI_PROVIDER=openai` |
| Speech | faster-whisper large-v3-turbo (speech to text), Kokoro (voice); browser speech as fallback |
| Data | Open Library, NLB open data and library locations (data.gov.sg), NLB's OverDrive catalogue, Project Gutenberg (Gutendex), NLB Catalogue v2 when keyed |
| Ops | Make, `scripts/setup.py` |

```
backend/app/
  api/           HTTP routers (paths, discover, chat, media, library, system)
  core/          configuration and domain models
  ai/            model provider, embeddings, speech-to-text, voice
  integrations/  NLB/Open Library catalogue, NLB open data, OverDrive, Gutenberg, availability
  services/      reading-path engine, discovery, chat, answers, reading age
frontend/src/    screens (Home, Line, Book, Meet), components, i18n, wayfinding
```
More in [`backend/app/README.md`](backend/app/README.md).

## Architecture
```mermaid
flowchart LR
  UI["React + TypeScript app<br/>(PWA, works offline)"] -->|"/api"| API["FastAPI<br/>paths · discover · chat · media · library"]
  API --> SVC["Services<br/>reading-path engine · discovery · chat · reading age"]
  SVC --> AI["Open-source AI via Ollama<br/>LLM · vision · embeddings"]
  API --> SPEECH["Speech<br/>faster-whisper · Kokoro"]
  SVC --> DATA["Data<br/>Open Library · NLB open data · NLB eBooks (Libby)<br/>Project Gutenberg · NLB Catalogue API"]
  SVC --> CACHE[("Verified catalogue<br/>+ cached reading paths")]
```
How a reading path is built, what each layer owns, and the data flow: [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md).

## Quick start
Requirements: Python 3.11+, Node 18+, macOS or Linux. [Ollama](https://ollama.com) is optional but recommended.
```bash
make setup          # Python venv + npm install (copies .env.example to .env)
make serve          # build the UI and serve everything on http://localhost:8000
```
AI models (optional): install [Ollama](https://ollama.com), then pull each model:
```bash
for m in gpt-oss:20b gemma3:12b qwen2.5vl:7b nomic-embed-text; do ollama pull "$m"; done
```
Voice (optional): `backend/.venv/bin/pip install -r backend/requirements-optional.txt`. Without these the app still runs on cached reading paths and built-in rules.

Keys (optional, in `.env`): `NLB_API_KEY` and `NLB_APP_CODE` for live per-branch copies from the NLB Catalogue API, `DATAGOV_API_KEY` to avoid data.gov.sg rate limits. Nothing is required to try it: `make precompute-demo` builds the cache offline.

Prefer a background service? `python3 scripts/setup.py install` then `python3 scripts/setup.py start` (also `status`, `logs`, `stop`).

Useful: `python3 scripts/setup.py doctor` (checks everything), `make test` (backend + frontend tests), `make eval` (audits every cached path), `make warmup` (primes caches).

## Data sources
**Data provided by the National Library Board, Singapore (NLB)** ([NLB Labs](https://www.nlb.gov.sg/main/partner-us/contribute-and-create-with-us/NLBLabs)). The NLB datasets and APIs PreReads uses:

- [Libraries](https://data.gov.sg/datasets/d_27b8dae65d9ca1539e14d09578b17cbf/view) (data.gov.sg, `d_27b8dae65d9ca1539e14d09578b17cbf`): library names and locations.
- [National Library Board Library Reach Index, Collections And Loans, Annual](https://data.gov.sg/datasets/d_bf36da418f88e5485aff69079694ecef/view) (data.gov.sg, `d_bf36da418f88e5485aff69079694ecef`): yearly loan totals, refreshed daily.
- [NLB library pages](https://www.nlb.gov.sg/main/visit-us/our-libraries-and-locations): opening hours.
- [NLB's eBook catalogue](https://nlb.overdrive.com) (OverDrive/Libby): live eBook and audiobook copies.
- NLB Catalogue API v2 ([NLB Labs](https://www.nlb.gov.sg/main/partner-us/contribute-and-create-with-us/NLBLabs)): per-branch copies, call numbers and queues when `NLB_API_KEY` and `NLB_APP_CODE` are set; otherwise a built-in table. Pick the source with `DATA_SOURCE=auto|demo|dataset|api` in `.env` or in Settings.

Also: catalogue checks, descriptions and Dewey classes from Open Library; public-domain texts from Project Gutenberg.

Full guide (setup, modes, API, adding titles, troubleshooting): [`docs/GUIDE.md`](docs/GUIDE.md).

## Credits
Data provided by the National Library Board, Singapore (NLB), via data.gov.sg (Singapore Open Data Licence), NLB's library pages and NLB's public OverDrive catalogue; Open Library (CC0), Project Gutenberg, Ollama and the open models above, faster-whisper, Kokoro, and Google Fonts (Atkinson Hyperlegible, Fraunces, Noto Sans SC, Noto Sans Tamil; SIL OFL).

## License
[MIT](LICENSE)
