"""PreReads backend. Layers, top to bottom (each imports only from the ones below it):

  api/           HTTP routers (thin handlers)
  services/      the product logic: reading paths, discovery, chat, ask, reading age
  integrations/  external data: NLB catalogue + availability, Open Library, OverDrive
  ai/            model providers: LLM, embeddings, speech-to-text, text-to-speech
  core/          config and the shared Pydantic models

One exception: core.config imports ai.llm inside two functions (Ollama status for
/api/mode), never at import time. Entry point: app.main:app. See app/README.md.
"""
