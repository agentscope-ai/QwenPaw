# Embedding Backend Split Commits (2026-03-24)

This report records the incremental commit strategy for embedding backend
alignment work on `feature/embedding-config-local`.

## Commit Groups

1. **C1 backend core**
   - Normalize Ollama embedding base URL for `/api/embed` calls.
   - Add focused unit coverage for URL normalization and request path.
2. **C2 config/API**
   - Add canonical `/api/config/agents/embedding` GET/PUT endpoints.
   - Keep `/agents/local-embedding` as compatibility slice.
3. **C3 console**
   - Add explicit remote backend selection (`openai` / `ollama`) in the
     embedding settings card.
   - Avoid forcing `backend_type` back to `openai` when local mode is off.
4. **C4 tests/docs**
   - Add integration tests for canonical embedding config endpoints and
     compatibility behavior.
   - Record split strategy and verification notes in this report.

## Verification Notes

- Unit: `tests/unit/test_ollama_embedding_model.py`
- Integration: `tests/integrated/test_local_embedding_api.py`
- Provider conflict follow-up: `tests/unit/providers/test_ollama_provider.py`

All commands were run locally on this branch before finalizing commits.
