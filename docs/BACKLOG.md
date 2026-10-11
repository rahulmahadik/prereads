# Feature backlog (after the makeathon build)

Ordered by reader value ÷ effort. ✦ = needs the NLB key. ✅ = built (state at 11 Oct 2026); the rest is still open, in the same order.

| # | Feature | Reader value | Needs | Effort |
|---|---|---|---|---|
| 1 ✅ | **Same-shelf trip** — "3 of your PreReads are on the same shelf (332) — grab them in one visit" | Turns the most common pattern into a win | call numbers (demo or ✦) | S |
| 2 ✅ | **My shelf** — heart any book; "My shelf" on Home with paths in progress and hours left | Return visits | on-device | S |
| 3 ✅ | **Notes per book** — one tap, on-device | Readers already annotate | on-device | S |
| 4 ✅ | **Reserve / waitlist deep link with queue length** ✦ | Closes the loop from "waiting" | `activeReservationsCount` + catalogue link | S |
| 5 | **eBook / audiobook instead** ✦ | No copy near you? Borrow digitally | eResources API | M |
| 6 ✅ | **Nearest library** ✦ | "Available at Bishan" → "Bishan, 12 min away" | Library API (list + hours) + browser geolocation | M |
| 7 ✅ | **Reading-age chips** — "Reading age 12+", "Teen", labelled estimated | Parents, teachers | `audience` from catalogue + LLM estimate | S |
| 8 | **Kids narrator** — an original library-cat mascot tells the book in 20 seconds, voice + captions | Kids section | TTS + LLM summary at reading age | M |
| 9 ✅ | **Share a path by QR** — on the share card and the open-mic table | People's Choice | none | S |
| 10 ✅ | **Meet at the book** — two readers, two levels, two paths converging on one target | Book clubs, parent + child | engine already supports level | M |
| 11 ✅ | **Shelf-talker print** — A6 card per PreRead for the physical shelf | Librarians | PDF template | S |
| 12 | **Multilingual UI** — 中文 / Melayu / தமிழ் chrome, then catalogue search in those languages | Singapore reality | translations; catalogue `languages` filter ✦ | M |
| 13 ✅ | **Offline PWA** — service worker caching paths you've opened | Inside libraries with poor signal | SW | M |
| 14 ✅ | **Whisper voice-in on the server** — dialect-tolerant speech input | Seniors | OpenAI STT | S |
| 15 | **Availability alerts** — "a copy of X is in at Bishan" | Waiting readers | account + polling ✦ | L (vision) |

Notes on what shipped:
- #1 Same-shelf trip: `shelf.ts` groups stops by Dewey class; the trip note shows on the path. Demo call numbers use the real Open Library Dewey class (`backfill_ddc.py`).
- #2 / #3 My shelf and notes: `myshelf.ts`, on-device only (localStorage); heart on rows and the book page, note chip on the row.
- #4 Reserve / waitlist: a catalogue link on the book page. The queue length is real only once the NLB key works (demo is labelled).
- #6 Nearest library: `data/libraries.json` (data.gov.sg), `/api/branches` with lat/lng/hours, "Use my location" in the library sheet. Hours are the typical 10:00-21:00 default (`hours_source`), not live.
- #7 Reading-age: `reading_age.py` / `readingAge.ts`, labelled estimated unless the catalogue gives the audience.
- #9 QR: own encoder in `qr.ts`; on the share card and shelf talkers. #10 Meet: `#/meet`. #11 Shelf talkers: print-only A6 cards.
- #13 Offline PWA: `public/sw.js` plus an offline badge. #14 Whisper: local faster-whisper at `/api/stt` (not OpenAI), the browser's recognition stays the fallback.
- Also shipped, not on the original list: "Because you liked" (`/api/similar`, local embeddings), local Kokoro voice (`/api/tts`), local AI via Ollama, `make eval`, one-command run and tunnel scripts.

Still open: #5 eBook/audiobook (needs eResources API), #8 kids narrator, #12 multilingual UI, #15 availability alerts. Real queue lengths, live hours and live availability wait for the NLB key.

Not doing: our own borrowing/renewals/reservations (NLB does these; we link), ratings and
reviews (no trustworthy source without accounts), demographic "most liked by" claims.
