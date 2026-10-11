# What NLB's portals don't do today — and what PreReads adds

Checked October 2026: catalogue.nlb.gov.sg, the NLB Mobile app (store listings, feature
pages, 2.9k Play reviews at 3.1★), Bukit Batok's Scan-n-Discover pilot.

| Gap in NLB's web/app today | Evidence | PreReads answer |
|---|---|---|
| Search needs the right words: title/author/keyword only | Catalogue and app search fields; a reviewer searched a book they were holding and got "no such title" | **Tell me what you want** — a sentence in your own words becomes a structured need; filters are generated from it |
| No "am I ready?" and no "what to read first" | Nothing in the catalogue, app or Scan-n-Discover (which shows *similar* books) | Readiness meter + PreReads/NextReads line with the reason for every book |
| Availability is a per-copy status list ("Available / On loan" rows) | Catalogue item view | Reader-facing status: Available at X · Nearest copy at Y · Waiting (with queue length) · eBook instead |
| No directions inside the building | Not a feature anywhere; floor plans are signage only | Floor-plan route from the doors to the range, with the call number to look for |
| Demand is invisible to readers | Trends exist in the API but are not surfaced in the catalogue UI | "Hot at Jurong West" from checkout trends; queue length from reservation counts |
| No reading-progress across a plan | App tracks loans, not a plan | Mark PreReads read; the line recounts and "Start here" moves |
| No voice: nothing can be listened to, nothing can be asked by voice | App supports audiobooks, not spoken UI | **Listen** on every book, line and set of picks; **🎤** to say what you want; chat can read replies aloud |
| Seniors get no large-text / simplified mode | Default UI only | Aa mode: 20px type, 52px targets, plain labels |
| App reliability complaints: slow loads, crashes after updates, scanner SDK expiry | Play Store reviews Feb–Aug 2026 | PreReads is a static web app with a cached engine; no login, nothing to install |

What NLB does well and we deliberately don't rebuild: borrowing/renewing, eBooks via Libby,
reservations, account management. PreReads links out to the catalogue for those.

## Natural voice — how it works (all local by default)

- `POST /api/tts` → local Kokoro voice (`kokoro-onnx`, model files in `backend/data/models`, voice
  `LOCAL_TTS_VOICE`, default `bf_emma`). If Kokoro is missing it uses the macOS `say` voice. With
  `AI_PROVIDER=openai` it uses OpenAI TTS (`OPENAI_TTS_MODEL`, `OPENAI_TTS_VOICE`). Audio is cached on disk
  by text hash. Nothing leaves the device in the default setup.
- When nothing is available the API returns 503 and the frontend uses the browser's best built-in voice
  (it prefers en-SG/en-GB natural voices), so **Listen** always works.
- Narration is scripted, not read verbatim: book page = title, why, readiness in words,
  hours, assumed concepts, where it is, call number, then the walking steps; line =
  numbered PreReads with reasons and where each is; picks = the need summary + top three.
- Voice input: `POST /api/stt` runs faster-whisper (`large-v3-turbo`, CPU int8) locally and is tried first,
  which copes better with accents and dialects than the browser. If it is not installed or fails (503/422), the
  browser's SpeechRecognition (Chrome, Edge, Safari) takes over. Used in the discovery box and the chat.
- Languages: Kokoro and Whisper handle more than English, but the UI text and narration are English only
  for now; Chinese/Malay/Tamil narration waits on translated catalogue text.

## Since this was written

Built after the first check: nearest library with distance and open/closed (data.gov.sg list; hours are the
typical default until the Library API is available), same-shelf trip, My shelf and notes, reserve/waitlist link,
"Because you liked", share by QR, shelf talkers, Meet at the book, offline PWA. Still true that live
availability, real queue lengths and live hours need the NLB key.
