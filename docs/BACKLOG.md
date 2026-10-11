# Feature backlog (after the makeathon build)

Ordered by reader value ÷ effort. ✦ = needs the NLB key.

| # | Feature | Reader value | Needs | Effort |
|---|---|---|---|---|
| 1 | **Same-shelf trip** — "3 of your PreReads are on the same shelf (332) — grab them in one visit" | Turns the most common pattern into a win | call numbers (demo or ✦) | S |
| 2 | **My shelf** — heart any book; "My shelf" on Home with paths in progress and hours left | Return visits | on-device | S |
| 3 | **Notes per book** — one tap, on-device | Readers already annotate | on-device | S |
| 4 | **Reserve / waitlist deep link with queue length** ✦ | Closes the loop from "waiting" | `activeReservationsCount` + catalogue link | S |
| 5 | **eBook / audiobook instead** ✦ | No copy near you? Borrow digitally | eResources API | M |
| 6 | **Nearest library** ✦ | "Available at Bishan" → "Bishan, 12 min away" | Library API (list + hours) + browser geolocation | M |
| 7 | **Reading-age chips** — "Reading age 12+", "Teen", labelled estimated | Parents, teachers | `audience` from catalogue + LLM estimate | S |
| 8 | **Kids narrator** — an original library-cat mascot tells the book in 20 seconds, voice + captions | Kids section | TTS + LLM summary at reading age | M |
| 9 | **Share a path by QR** — on the share card and the open-mic table | People's Choice | none | S |
| 10 | **Meet at the book** — two readers, two levels, two paths converging on one target | Book clubs, parent + child | engine already supports level | M |
| 11 | **Shelf-talker print** — A6 card per PreRead for the physical shelf | Librarians | PDF template | S |
| 12 | **Multilingual UI** — 中文 / Melayu / தமிழ் chrome, then catalogue search in those languages | Singapore reality | translations; catalogue `languages` filter ✦ | M |
| 13 | **Offline PWA** — service worker caching paths you've opened | Inside libraries with poor signal | SW | M |
| 14 | **Whisper voice-in on the server** — dialect-tolerant speech input | Seniors | OpenAI STT | S |
| 15 | **Availability alerts** — "a copy of X is in at Bishan" | Waiting readers | account + polling ✦ | L (vision) |

Not doing: our own borrowing/renewals/reservations (NLB does these; we link), ratings and
reviews (no trustworthy source without accounts), demographic "most liked by" claims.
