# Prompt contracts

All prompts return structured outputs (Pydantic schemas in backend/app/core/models.py).
Rules live in code (engine.apply_rules), never in prompt text.

## How a prompt is sent
`llm.structured(schema, system, user, ...)` calls the provider's `chat.completions` with
`response_format={"type": "json_schema", "json_schema": {"name": <Schema>, "strict": true, "schema": <Pydantic JSON schema>}}`
and validates the reply with Pydantic. The default provider is local Ollama (OpenAI-compatible endpoint,
`AI_PROVIDER=ollama`); `AI_PROVIDER=openai` sends the same request to OpenAI; `none` skips the model and the
callers use heuristics. There are two tiers: fast (`LOCAL_LLM_MODEL`, interactive) and heavy
(`LOCAL_LLM_MODEL_HEAVY`, used by precompute.py and eval_paths.py for readiness, candidates and pairwise judgments).
A model that is not pulled falls back through the `*_FALLBACKS` lists. Vision (scan) uses `LOCAL_VISION_MODEL`.
Embeddings (`llm.embed`, nomic-embed-text) are not prompts; they only shortlist candidates in discover.py and
power `/api/similar`. A None return from any call means "model unavailable": callers degrade, they never invent books.

## Readiness (per book)
Role: public-library readers' advisor. Level 1 anyone / 3 some familiarity / 5 specialist;
hours = average adult; 3–6 assumed concepts; one_line = what you need going in, warm, plain.
Output: {level, hours, assumed_concepts[], style_tags[], one_line}

## Candidates (per target)
Propose 6 real "before" books (easier, introductory, on-ramps) and 5 "after" books
(deeper, adjacent, author's follow-on), each with a one-sentence specific why. Prefer
public-library availability. Never the target itself.
Output: {before:[{title,author,why}], after:[{title,author,why}]}

## Judgment (per pair)
Does A prepare a reader for B? relation ∈ prepares_for | same_level | follows | unrelated;
confidence 0–1; reason = one sentence a librarian would say, naming the concept or skill.
Output: {relation, confidence, reason}

## Scan (per image)
Read title/author as printed; ISBN if legible; confidence; empty title if no book.
Output: {title, author, isbn?, confidence}

## Ask (per question, grounded)
Answer ONLY from the route JSON; never add books; ≤ 90 words; warm and plain; time
questions use hours per stop; large print → say what the data shows, suggest staff.

## Other model calls
- Discovery need parsing and proposals (discover.py): a reader's sentence -> structured need (topics, level, audience, format) and proposed titles, all verified in the catalogue before they show.
- Similar (`/api/similar`): embedding neighbours, then a one-line reason per neighbour (falls back to shared subjects when the model is down).
- Reading age (reading_age.py): catalogue audience first; the model only estimates when the catalogue is silent. Labelled estimated.

## Sanity rules enforced in code
- every candidate must resolve in NLB or Open Library, else dropped (noted)
- before: level < target level; confidence ≥ 0.6; ≤ 3; one per author; non-decreasing ramp
- after: level ≥ target level − 1; confidence ≥ 0.6; ≤ 3; never a book already on the before-line
- target never appears on its own line
