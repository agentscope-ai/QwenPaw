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

Subsequent modifications will be appended to this file.
