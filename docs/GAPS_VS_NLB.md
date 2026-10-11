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

## Natural voice — how it works

- `POST /api/tts` → OpenAI text-to-speech (model/voice configurable: `OPENAI_TTS_MODEL`,
  `OPENAI_TTS_VOICE`), styled as a warm librarian, cached as MP3 on disk by text hash.
- Without the key (demo/prototype) the frontend uses the browser's best built-in voice,
  so **Listen** always works; the UI prefers en-SG/en-GB natural voices when present.
- Narration is scripted, not read verbatim: book page = title, why, readiness in words,
  hours, assumed concepts, where it is, call number, then the walking steps; line =
  numbered PreReads with reasons and where each is; picks = the need summary + top three.
- Voice input uses the browser's SpeechRecognition (Chrome, Edge, Safari) in the
  discovery box and the chat; Whisper on the server is the next step for dialects.
- Languages: the TTS is multilingual; pass `lang` for Chinese/Malay/Tamil narration once
  the catalogue text is in that language.
