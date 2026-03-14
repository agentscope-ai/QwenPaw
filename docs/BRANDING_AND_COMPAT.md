# Branding and CoPaw compatibility

BoostClaw is a fork of [CoPaw](https://github.com/agentscope-ai/CoPaw). This document describes naming and compatibility choices.

## Constraints

1. **Package name is not changed**: The Python package remains `copaw` (directory `src/copaw`, imports `from copaw...`). We do not rename it to avoid a large diff and to ease merging upstream.
2. **No COPAW_HOME / legacy install compatibility**: We do not preserve compatibility with environments that rely on `COPAW_HOME` or the old CoPaw install paths. Install scripts and defaults use BoostClaw naming only.

## What is BoostClaw

- **Project name**: `boostclaw` in `pyproject.toml`
- **CLI entry point**: `boostclaw` (e.g. `boostclaw app`, `boostclaw init`)
- **Install scripts**: Use `BOOSTCLAW_HOME` only (default `~/.boostclaw`). Wrapper and PATH use `boostclaw` and `~/.boostclaw/bin`.
- **Default working directory**: `~/.boostclaw` (config, data, venv, bin all under this directory by default).

## Environment variables: dual prefix (app config only)

We support **both** prefixes so that:

- New deployments can use `BOOSTCLAW_*` (e.g. `BOOSTCLAW_WORKING_DIR`, `BOOSTCLAW_LOG_LEVEL`).
- Existing configs and scripts that set `COPAW_*` continue to work.

**Resolution order**: for each app-level variable we read `BOOSTCLAW_<SUFFIX>` first; if unset, we use `COPAW_<SUFFIX>`, then the default.

Implemented in:

- `src/copaw/_env_compat.py` — helpers `get_app_env()`, `get_app_env_bool()`, `get_app_env_int()`, `get_app_env_float()`.
- `src/copaw/constant.py` — all path, log level, CORS, LLM retry, tool guard timeout, memory compaction, etc., use these helpers.
- `src/copaw/envs/store.py` — bootstrap working/secret dir resolution and protected-keys set (both prefixes excluded from envs.json persistence).

**Examples:**

- `BOOSTCLAW_WORKING_DIR` or `COPAW_WORKING_DIR` → working directory (default `~/.boostclaw`).
- `BOOSTCLAW_LOG_LEVEL` or `COPAW_LOG_LEVEL` → log level (default `info`).
- Same pattern for `SECRET_DIR`, `LOG_LEVEL`, `CORS_ORIGINS`, `RUNNING_IN_CONTAINER`, `OPENAPI_DOCS`, `LLM_MAX_RETRIES`, `MEMORY_COMPACT_*`, `TOOL_GUARD_APPROVAL_TIMEOUT_SECONDS`, etc.

**Not yet dual-prefix:** Some modules still read only `COPAW_*` (e.g. channel config, skills hub, tool guard allow/deny lists, reload mode). They remain compatible because `COPAW_*` is still honored; adding `BOOSTCLAW_*` fallback there is optional and can be done incrementally.

## Summary

- **Package name**: Unchanged; remains `copaw`.
- **Install / default paths**: `BOOSTCLAW_HOME` and default working dir `~/.boostclaw`; no `COPAW_HOME` or legacy CoPaw install compatibility.
- **App env vars**: Dual prefix (`BOOSTCLAW_*` preferred, `COPAW_*` fallback) for app config.
- **User-facing branding**: Use “BoostClaw” and the `boostclaw` CLI everywhere in docs and install scripts; env vars can be either prefix.
