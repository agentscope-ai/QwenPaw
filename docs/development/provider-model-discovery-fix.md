# Provider Model Discovery Fix

## Scope

Fix model discovery for custom OpenAI-compatible providers across legacy
configuration loading, provider configuration updates, background discovery,
and the console model picker.

## Design

1. Normalize discovery capability from the configured chat protocol whenever a
   custom provider is created or loaded.
2. Mark a provider as syncing before returning from a configuration request so
   the console cannot miss the background task state.
3. Persist successful discovery results atomically and preserve the previous
   cache when discovery fails.
4. Persist add-model preview discovery so the backend can merge canonical
   model metadata when the user adds a discovered model.
5. Represent pending, failed, empty, and successful discovery states with
   distinct UI text and expose a Refresh models action.

## Acceptance Checklist

- [x] Legacy custom OpenAI-compatible providers load with discovery enabled.
- [x] Changing a custom provider protocol recomputes discovery capability.
- [x] Configuration responses expose `models_syncing=true` before background
      discovery runs.
- [x] Successful `/models` responses persist model candidates and sync time.
- [x] Failed discovery preserves the last successful cache and stores a
      sanitized error.
- [x] Preview discovery populates the Model ID selector and persists canonical
      metadata for the add-model flow.
- [x] Refresh models reports success, empty, and failure states accurately.
- [x] Settings and chat selectors refresh while discovery is running.
- [x] Backend unit, frontend unit, and end-to-end provider discovery tests pass.
