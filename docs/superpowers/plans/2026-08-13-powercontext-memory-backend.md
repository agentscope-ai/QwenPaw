# PowerContext Memory Backend Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add an optional QwenPaw memory backend that writes and searches structured memories through PowerContext's existing Python client, while preserving ReMeLight as the default and fallback.

**Architecture:** Add a standalone PowerContext client adapter and a `BaseMemoryManager` implementation registered as `powercontext`. The manager maps each agent to a configured PowerContext scope, performs non-blocking `remember_memory` writes, injects semantic search results before model calls, and degrades safely when PowerContext is unavailable.

**Tech Stack:** Python 3.11+, Pydantic settings/config models, `httpx`, PowerContext public HTTP client contract, pytest/pytest-asyncio.

## Global Constraints

- Do not modify the `powercontext` repository in this phase.
- Keep `remelight` as the default backend.
- Do not make PowerContext availability a prerequisite for starting QwenPaw.
- Never log API tokens or full authorization headers.
- Preserve existing QwenPaw memory message formats and registry behavior.

### Task 1: PowerContext client adapter

**Files:**
- Create: `src/qwenpaw/agents/memory/powercontext_client.py`
- Test: `tests/unit/agents/memory/test_powercontext_client.py`

- [ ] Write tests for request mapping, result normalization, timeout/error behavior, and close.
- [ ] Implement a small async client using the public PowerContext HTTP contract (`/v1/memory/remember`, `/v1/memory/search`) so QwenPaw does not require PowerContext as an import-time dependency.
- [ ] Run the focused client tests.

### Task 2: PowerContext memory manager

**Files:**
- Create: `src/qwenpaw/agents/memory/powercontext_memory_manager.py`
- Create: `src/qwenpaw/agents/memory/powercontext_prompts.py`
- Modify: `src/qwenpaw/agents/memory/__init__.py`
- Test: `tests/unit/agents/memory/test_powercontext_memory_manager.py`

- [ ] Write tests for registry discovery, start degradation, scope isolation, auto search injection, asynchronous persistence, explicit `memory_search`, and local fallback behavior.
- [ ] Implement `PowerContextMemoryManager` with `start`, `close`, `summarize`, `auto_memory`, `auto_memory_search`, `memory_search`, `get_memory_prompt`, and `list_memory_tools`.
- [ ] Encode summaries using bounded structured kinds (`project_goal`, `decision`, `constraint`, `task_state`, `tool_result`, `outcome`, `next_step`, `preference`) and preserve the current turn text as evidence.
- [ ] Run focused manager tests.

### Task 3: Configuration and backend wiring

**Files:**
- Modify: `src/qwenpaw/config/config.py`
- Test: `tests/unit/config/test_memory_config.py`

- [ ] Add `PowerContextMemoryConfig` with `base_url`, `token`, `scope_id`, `timeout`, `fallback_backend`, and auto-search settings.
- [ ] Add `powercontext_memory_config` to `AgentsRunningConfig` and validate defaults without changing existing configs.
- [ ] Run config and manager import tests.

### Task 4: Documentation and verification

**Files:**
- Create or modify: `docs/` integration documentation as appropriate
- Test: existing memory and startup test suites

- [ ] Document starting PowerContext and selecting `memory_manager_backend: powercontext` without exposing secrets.
- [ ] Run the focused tests, then the complete memory/config test subset and lint/type checks available in the repository.
- [ ] Verify the default `remelight` path remains unchanged.

