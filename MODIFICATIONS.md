# Modifications

This repository is a fork of [QwenPaw](https://github.com/agentscope-ai/QwenPaw)
(Apache License 2.0 — see [LICENSE](LICENSE)). As required by Section 4(b) of
the license, this file records the changes made in this fork relative to the
upstream project. Upstream history is preserved in git; run
`git log --oneline` or compare against `agentscope-ai/QwenPaw` for the full
per-file record.

## 2026-07

- **Rebrand of user-visible surfaces** (`QwenPaw` → `NousAIPaw`): product name
  in READMEs (en/zh/ja/ru/vi), contributor docs, product documentation
  (`website/public/docs/`), website UI strings and metadata, console UI
  strings and locale files, desktop window title, installer script prose, and
  plugin display metadata (including the Creator app manifest and UI).
  Internal identifiers are unchanged: the `qwenpaw` Python package and CLI,
  `QWENPAW_*` environment variables, `~/.qwenpaw` data directories, the
  `window.QwenPaw` plugin API, `QwenPaw-Flash` model repository IDs, release
  artifact names, the Tauri `productName`/bundle identifier, and upstream
  URLs. Historical release notes and blog posts were left as published.
- **Brand images** (`logo.svg/png`, `qwenpaw-symbol.svg/png`, `qwenpaw_ip.png`,
  `paw.png`, console `logo-light/dark.svg`, `qwenpaw.png`, `qwenpawBack.png`)
  replaced with placeholder artwork under the same filenames and dimensions.
- **Install and source-clone URLs** in `scripts/install.sh` / `install.ps1` /
  `install.bat`, READMEs, and docs point to this fork
  (`uaixo/awesome-NousAI-PAW`) instead of the upstream repository.
- **`deploy/Dockerfile`**: set `NODE_OPTIONS=--max-old-space-size=4096` in the
  console build stage to prevent an out-of-memory failure (exit 134) during
  `npm run build`.
- **`.github/workflows/pr-ai-review.yml`**: the AI review workflow is gated
  behind the repository variable `ENABLE_AI_REVIEW` (this fork does not carry
  the `REVIEW_DASHSCOPE_API_KEY` secret); `enable_ai_review` declared in
  `.github/actionlint.yaml`.
- **Documentation formatting**: markdown tables re-aligned with Prettier after
  the rebrand changed cell widths.
- Added this `MODIFICATIONS.md` and the top-level `NOTICE` file.
- **Console header**: removed the "Documentation" dropdown and the "GitHub"
  button, including their entries in the mobile overflow menu. The overflow
  menu is retitled with a new `header.preferences` locale key. The upstream
  `header.resources` / `header.github` / `header.tutorial` strings are left in
  the locale files.
- **Assistant display name**: the chat response identity (`welcome.nick`, shown
  above every assistant response) and the Voice/SIP `welcome_greeting` defaults
  read `NousAIPaw`, matching the already-rebranded channel documentation.

## 2026-08

- **`tests/unit/tauri/test_entry.py`** — *resolved, no longer a fork
  modification.* The CORS-preservation test was briefly patched here to clear
  `qwenpaw.app._app` from `sys.modules` before calling
  `_install_desktop_runtime()`: upstream's
  `tests/unit/app/test_scroll_startup_io.py` (added in agentscope-ai/QwenPaw
  #6237) imports that module and leaves it loaded, which tripped the
  `_ensure_qwenpaw_app_not_loaded()` guard for every later test in the process,
  deterministically, since `tests/unit/app/` collects before
  `tests/unit/tauri/`. Upstream subsequently applied the identical fix, so this
  file is byte-identical to upstream again and carries no fork divergence.

- **`src/qwenpaw/providers/context_windows.py`** — added DeepSeek V4 entries to
  the static context-window catalog: `deepseek-v4-flash` and `deepseek-v4-pro`
  → 1,000,000 tokens. Upstream ships no DeepSeek patterns, so these models fell
  through to the 131,072-token default — the Console reported "131.1K" and
  context compaction fired at 128k for a 1M-context model. The official API
  documents 1M for both (2026-04-24 V4 release news; OpenRouter lists
  1,048,576 — entered as the catalog-conventional conservative `1_000_000`).
  Substring matching also covers gateway ids (`deepseek-v4-flash-free`,
  `deepseek-ai/DeepSeek-V4-Flash`). Older V3.x families deliberately keep the
  128k default.

Subsequent modifications will be appended to this file.
