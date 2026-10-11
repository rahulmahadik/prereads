# PreReads

**Say what you want to read. PreReads finds real library books, the ones to read before them, and the shelf they're on.**

A hard book is easier when you've read the right books first. PreReads builds *your reading path* (easier books first, then your book, then what to read next) from books that exist in the catalogue, and shows where each one is at your library today.

- **Live demo:** https://prereads.vitbhatti.com
- **No-server prototype:** [`docs/index.html`](docs/index.html) (embedded data, works offline)
- **Design:** [Figma screens and clickable prototype](https://www.figma.com/design/c5wM6zZUx2NT91NIEYwbFZ) · [architecture diagrams](https://www.figma.com/board/5TEfAaBhbQFeLO91qIPSuP)

All AI runs locally on the device (open models via Ollama); no cloud AI calls by default. Not an NLB product.

| | | |
|:---:|:---:|:---:|
| <img src="docs/screenshots/home.jpg" width="220" alt="Home with My shelf"><br>Home and My shelf | <img src="docs/screenshots/discover.jpg" width="220" alt="Discovery results"><br>Tell it what you want | <img src="docs/screenshots/path.jpg" width="220" alt="Reading path with same-shelf trip"><br>Your reading path |
| <img src="docs/screenshots/book.jpg" width="220" alt="Book page"><br>About the book and where it is | <img src="docs/screenshots/map.jpg" width="220" alt="Shelf map"><br>Walk to the shelf | <img src="docs/screenshots/chat.jpg" width="220" alt="Chat with steps"><br>Chat that shows its steps |

## What it does
- **Find books** by describing what you want, typing a title, scanning a cover, or speaking.
- **Your reading path**: PreReads → your book → NextReads, each with a reading level, hours and a reason. Rules are enforced in code: before-books must be easier, confidence ≥ 0.6, at most 3 before and 3 after, one author per before-path, and no book appears twice.
- **At the library**: shelf status per branch, the same-shelf trip ("3 of your PreReads are on the same shelf (332)"), an animated walk to the bay and row, the nearest library with opening hours, reserve or waitlist links.
- **Read or borrow digitally**: live eBook and audiobook copies from NLB's digital collection, publisher samples, and the first chapter in-app for public-domain books.
- **Yours**: My shelf, notes, Meet at the book (two readers, one target), share by QR, printable A6 shelf-talkers.
- **For everyone**: English, 中文, Bahasa Melayu and தமிழ், senior mode, voice in and out, works offline once opened.

## Tech stack
| Layer | Technology |
|---|---|
| Frontend | React 18 + TypeScript, Vite, hand-written CSS tokens, service worker (PWA), vitest |
| Backend | Python 3.11+, FastAPI, Pydantic v2, httpx, pytest |
| Local AI (Ollama) | gpt-oss:20b (chat, discovery, reading levels), gpt-oss:120b (optional heavy model for judging paths), qwen2.5vl:7b (cover scan), nomic-embed-text (semantic search), gemma3:12b as fallback; optional OpenAI via `AI_PROVIDER=openai` |
| Speech | faster-whisper large-v3-turbo (speech to text), Kokoro (voice); browser speech as fallback |
| Data | Open Library, NLB open data and library locations (data.gov.sg), NLB's OverDrive catalogue, Project Gutenberg (Gutendex), NLB Catalogue v2 when keyed |
| Ops | Make, `scripts/setup.py`, Cloudflare Tunnel (`scripts/tunnel.sh`) |

```
backend/app/
  api/           HTTP routers (paths, discover, chat, media, library, system)
  core/          configuration and domain models
  ai/            local model provider, embeddings, speech-to-text, voice
  integrations/  NLB/Open Library catalogue, NLB open data, OverDrive, Gutenberg, availability
  services/      reading-path engine, discovery, chat, answers, reading age
frontend/src/    screens (Home, Line, Book, Meet), components, i18n, wayfinding
```
More in [`backend/app/README.md`](backend/app/README.md).

## Quick start
```bash
make setup          # Python venv + npm install (copies .env.example to .env)
make serve          # build the UI and serve everything on http://localhost:8000
```
Optional local AI: install [Ollama](https://ollama.com), then `ollama pull gpt-oss:20b gemma3:12b qwen2.5vl:7b nomic-embed-text`. Optional voice: `pip install -r backend/requirements-optional.txt`. Without these the app still runs on cached reading paths and built-in rules.

Useful: `python3 scripts/setup.py doctor` (checks everything), `make test` (backend + frontend tests), `make eval` (audits every cached path), `make warmup` (primes caches before a demo), `bash scripts/tunnel.sh quick` (share a public link).

## Data: what's real and what's demo
- **Real**: catalogue checks, descriptions and Dewey classes (Open Library); library locations, opening hours and NLB's yearly loan totals (NLB open data); eBook and audiobook copies (NLB's OverDrive catalogue); public-domain texts (Project Gutenberg).
- **Demo, labelled in the app**: per-branch shelf copies, queue lengths and "popular" trends, until NLB Catalogue API keys are added. Choose the source with `DATA_SOURCE=auto|demo|dataset|api` in `.env` or in Settings.

Full guide (setup, modes, API, adding titles, troubleshooting): [`docs/GUIDE.md`](docs/GUIDE.md).

## Credits
Open Library (CC0), data.gov.sg (Singapore Open Data Licence), NLB's public OverDrive catalogue, Project Gutenberg, Ollama and the open models above, faster-whisper, Kokoro, and Google Fonts (Atkinson Hyperlegible, Fraunces, Noto Sans SC, Noto Sans Tamil; SIL OFL).

## License
[MIT](LICENSE)
