.PHONY: setup backend frontend build serve precompute precompute-demo eval test clean warmup

setup:            ## one-time: python venv + deps, npm deps
	cd backend && python3 -m venv .venv && . .venv/bin/activate && pip install -r requirements.txt
	cd frontend && npm install
	@test -f .env || cp .env.example .env
	@echo "setup done. next: make precompute-demo && make serve"

precompute-demo:  ## build the cache offline (no keys needed)
	cd backend && . .venv/bin/activate && DEMO=1 python scripts/precompute.py

precompute:       ## build the cache with whatever keys are in .env
	cd backend && . .venv/bin/activate && python scripts/precompute.py --refresh

eval:             ## re-score cached paths with the heavy model (read-only)
	cd backend && . .venv/bin/activate && python scripts/eval_paths.py

backend:          ## API only, hot reload, http://localhost:8000
	cd backend && . .venv/bin/activate && python -m uvicorn app.main:app --reload --port 8000

frontend:         ## Vite dev server with API proxy, http://localhost:5173
	cd frontend && npm run dev

build:            ## production frontend bundle (served by the API)
	cd frontend && npm run build

serve: build      ## one process serves API + UI on http://localhost:8000
	cd backend && . .venv/bin/activate && python -m uvicorn app.main:app --port 8000 --host 0.0.0.0

test:             ## backend pytest + frontend vitest
	cd backend && . .venv/bin/activate && python -m pytest -q tests
	cd frontend && npm test --silent

warmup:           ## load the Ollama models and fill caches via a running app (QUICK=1, EXAMPLES=file.md)
	python3 scripts/warmup.py $(if $(QUICK),--quick,) $(if $(EXAMPLES),--examples $(EXAMPLES),)

clean:            ## remove the UI build and the cached reading paths (rebuild: make precompute-demo)
	rm -rf frontend/dist backend/data/cache/routes/*.json backend/data/cache/index.json
