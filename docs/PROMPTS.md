# Prompt contracts

All prompts return structured outputs (Pydantic schemas in backend/app/models.py).
Rules live in code (engine.apply_rules), never in prompt text.

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

## Sanity rules enforced in code
- every candidate must resolve in NLB or Open Library, else dropped (noted)
- before: level < target level; confidence ≥ 0.6; ≤ 3; one per author; non-decreasing ramp
- after: level ≥ target level − 1; confidence ≥ 0.6; ≤ 3
- target never appears on its own line
