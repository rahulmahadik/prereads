# backend/app

FastAPI backend for PreReads. Entry point: `app.main:app` (run from `backend/`).

## Packages

| Package | What lives there | May import |
|---|---|---|
| `api/` | One router per area (`routes_*.py`). Validate input, call a service, shape the response. No rules here. | services, integrations, ai, core |
| `services/` | Product logic: `engine` (reading paths), `discover`, `chat`, `ask`, `reading_age`. | integrations, ai, core |
| `integrations/` | External data: `catalog` (NLB Catalogue v2, Open Library, `resolve()`, `enrich()`), `sources` (enrichment fetchers), `nlb_datasets` (NLB open data: hours, yearly totals), `digital` (OverDrive), `online` (free editions, Gutenberg chapters), `availability` (shelf copies + demand; source chosen by `DATA_SOURCE`, demo fallback). | core |
| `ai/` | Model providers: `llm` (Ollama or OpenAI, structured outputs), `embeddings`, `stt`, `tts`. | core |
| `core/` | `config` (env, data paths, runtime modes), `models` (shared Pydantic models, also the prompt schemas). | nothing at import time (`config` asks `ai.llm` for Ollama status inside two functions) |
| `main.py` | Creates the app, mounts `api.ROUTERS`, warms embeddings, serves `frontend/dist`. | anything |

Data lives in `backend/data` (`config.DATA_DIR`); caches in `backend/data/cache` (`config.CACHE_DIR`).
Always build paths from `config`, never from a module's own `__file__`.

## Request flow: `GET /api/route?id=`

```
api/routes_paths.route
  -> services.engine.load_route(id)              cached JSON in data/cache/routes? return it
  -> (demo mode: 404, the cache is all there is)
  -> services.engine.find_seed(id) or integrations.catalog.resolve(title, author)
  -> services.engine.build_route
       propose        ai.llm.candidates (+ librarian seed picks), ordered by ai.embeddings
       verify         integrations.catalog.resolve: a title that resolves nowhere is dropped
       score          ai.llm.readiness, else heuristic_readiness
       judge          ai.llm.judge, else heuristic_judgment
       rules          apply_rules (code, not prompts: easier, confidence, author, max 3/3)
       shelf          integrations.availability.get_availability / get_demand
  -> save_route + index.json, return the Route
```

## Request flow: `POST /api/discover`

```
api/routes_discover.discover_  (422 if the text is under 2 characters)
  -> services.discover.discover(req)
       mode="fast"  heuristic_need (no model)  +  embedding shortlist with a 0.35 s budget
                    (keywords only if it is slow)  +  fit score over the cached catalogue
       mode="deep"  ai.llm proposes need + books  ->  each verified by catalog.resolve
                    ->  merged with the catalogue results (+ live catalogue pages)
       then: sort by fit, build filter chips, apply the ones that are on, page
```

The UI calls `fast` first, renders, then calls `deep` in the background when the fast
response's `deep` field says it would add something.

## Adding things

- **An endpoint**: add a handler to the matching `api/routes_*.py` (or a new
  `routes_<area>.py` with `router = APIRouter(prefix="/api", tags=[...])`, then add it to
  `ROUTERS` in `api/__init__.py`). Keep the handler thin; put logic in `services/`.
- **An external source**: a module in `integrations/` that never raises into a request
  (return `None`/`[]`, log a warning) and caches under `config.CACHE_DIR`. Book titles
  from it still go through `catalog.resolve()` before the UI sees them.
- **A model call**: a function in `ai/llm.py` built on `structured()` with a schema in
  `core/models.py`; update `docs/PROMPTS.md`. Callers check `config.llm_enabled()` and
  keep a heuristic fallback.
- **Tests** monkeypatch the module where a name is used (`services.discover.resolve`,
  not `integrations.catalog.resolve`) because `from x import name` makes a copy.
