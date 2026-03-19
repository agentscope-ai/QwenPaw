## ✨ Added

**Architecture**

- **Multi-Agent / Multi-Workspace Architecture**: Support running multiple agents simultaneously, each with its own isolated workspace containing independent config, memory, skills, and tools. Includes a console agent selector for easy switching between agents ([#1375](https://github.com/agentscope-ai/CoPaw/pull/1375), [#1625](https://github.com/agentscope-ai/CoPaw/pull/1625), [#1670](https://github.com/agentscope-ai/CoPaw/pull/1670), [#1714](https://github.com/agentscope-ai/CoPaw/pull/1714), [#1664](https://github.com/agentscope-ai/CoPaw/pull/1664), [#1614](https://github.com/agentscope-ai/CoPaw/pull/1614))
- **Context Management**: Added token counting, `/dump_history` and `/load_history` commands, configurable history length limits, and progress indicators during memory compaction ([#1628](https://github.com/agentscope-ai/CoPaw/pull/1628), [#1754](https://github.com/agentscope-ai/CoPaw/pull/1754), [#1689](https://github.com/agentscope-ai/CoPaw/pull/1689))

**Security**

- **Skill Security Scanner**: Skills are now scanned for security risks (prompt injection, command injection, hardcoded secrets, data exfiltration) before installation using static analysis ([#564](https://github.com/agentscope-ai/CoPaw/pull/564))
- **Destructive Shell Command Detection**: Added security rules to detect dangerous shell commands such as disk formatting, fork bombs, reverse shells, and privilege escalation attempts ([#1484](https://github.com/agentscope-ai/CoPaw/pull/1484), [#1529](https://github.com/agentscope-ai/CoPaw/pull/1529))
- **Web Authentication**: Added optional web authentication with single-user registration, token-based login, localhost bypass, and CLI command ([#1329](https://github.com/agentscope-ai/CoPaw/pull/1329), [#1666](https://github.com/agentscope-ai/CoPaw/pull/1666))

**Channels**

- **WeCom Channel**: Added WeCom as a messaging channel with media support, QR code access, and console configuration UI ([#1407](https://github.com/agentscope-ai/CoPaw/pull/1407), [#1706](https://github.com/agentscope-ai/CoPaw/pull/1706), [#1725](https://github.com/agentscope-ai/CoPaw/pull/1725), [#1728](https://github.com/agentscope-ai/CoPaw/pull/1728), [#1681](https://github.com/agentscope-ai/CoPaw/pull/1681), [#1747](https://github.com/agentscope-ai/CoPaw/pull/1747), [#1766](https://github.com/agentscope-ai/CoPaw/pull/1766), [#1618](https://github.com/agentscope-ai/CoPaw/pull/1618), [#1631](https://github.com/agentscope-ai/CoPaw/pull/1631))
- **XiaoYi Channel**: Added XiaoYi as a messaging channel ([#1213](https://github.com/agentscope-ai/CoPaw/pull/1213))
- **DingTalk AI Card Reply**: DingTalk now supports AI Card-based replies with incremental streaming, falling back to webhook/markdown when unavailable ([#1118](https://github.com/agentscope-ai/CoPaw/pull/1118))

**Skills**

- **LobeHub Skill Import**: Skills can now be imported directly from LobeHub ([#1350](https://github.com/agentscope-ai/CoPaw/pull/1350))
- **ModelScope Skill Hub**: Skills can now be imported from ModelScope Skill Hub ([#1673](https://github.com/agentscope-ai/CoPaw/pull/1673))
- **Version-Aware Builtin Skill Sync**: Built-in skills now track versions and automatically sync updates while preserving user customizations ([#1674](https://github.com/agentscope-ai/CoPaw/pull/1674), [#1716](https://github.com/agentscope-ai/CoPaw/pull/1716), [#1749](https://github.com/agentscope-ai/CoPaw/pull/1749))
- **Guidance Skill**: Added a built-in skill that answers CoPaw installation and configuration questions using local docs and the official website ([#1522](https://github.com/agentscope-ai/CoPaw/pull/1522))

**Multimodal**

- **View Image Tool**: Added a `view_image` tool that lets the LLM analyze local images for multimodal conversations ([#1526](https://github.com/agentscope-ai/CoPaw/pull/1526))
- **Non-Multimodal LLM Media Fallback**: When a non-multimodal LLM receives image/audio/video content, the system now automatically strips media blocks and retries the request ([#1676](https://github.com/agentscope-ai/CoPaw/pull/1676))
- **Audio Transcription**: Added voice message transcription via Whisper API or local Whisper model, with audio format conversion and a Voice Transcription settings page in the console ([#1476](https://github.com/agentscope-ai/CoPaw/pull/1476), [#1726](https://github.com/agentscope-ai/CoPaw/pull/1726))

**Providers**

- **Gemini Provider**: Added Google Gemini as a built-in LLM provider ([#1507](https://github.com/agentscope-ai/CoPaw/pull/1507))
- **DeepSeek Provider**: Added DeepSeek as a built-in LLM provider ([#1498](https://github.com/agentscope-ai/CoPaw/pull/1498))
- **MiniMax Provider**: Added MiniMax as a built-in LLM provider with separate International and China endpoints ([#1376](https://github.com/agentscope-ai/CoPaw/pull/1376), [#1735](https://github.com/agentscope-ai/CoPaw/pull/1735))

**CLI & Deployment**

- **`copaw update` Command**: Added `copaw update` and `copaw shutdown` CLI commands. `copaw update` automatically detects the environment and upgrades CoPaw from PyPI ([#1278](https://github.com/agentscope-ai/CoPaw/pull/1278))
- **Docker Compose**: Docker deployment now uses `docker-compose.yml` for easier setup and volume management ([#1320](https://github.com/agentscope-ai/CoPaw/pull/1320))
- **Docker Image**: Included additional channel dependencies in the Docker image ([#1761](https://github.com/agentscope-ai/CoPaw/pull/1761))

**Console & UI**

- **Console Dark Mode**: Added full dark mode support to the console with a theme toggle (light / dark / follow system) covering all pages ([#1566](https://github.com/agentscope-ai/CoPaw/pull/1566), [#1637](https://github.com/agentscope-ai/CoPaw/pull/1637), [#1662](https://github.com/agentscope-ai/CoPaw/pull/1662))
- **Console Chat Streaming**: Agent responses in the console are now streamed via SSE, with support for reconnection and stopping mid-response ([#1571](https://github.com/agentscope-ai/CoPaw/pull/1571), [#1672](https://github.com/agentscope-ai/CoPaw/pull/1672))

**CLI, Deployment & Others**

- **Timezone Configuration**: Added a timezone selector in the console; timezone is used across system prompts, cron scheduling, and heartbeat. Supports auto-detection on multiple platforms ([#1535](https://github.com/agentscope-ai/CoPaw/pull/1535), [#1746](https://github.com/agentscope-ai/CoPaw/pull/1746))
- **OS Information in System Prompt**: The system prompt now includes OS information for more platform-aware responses ([#1660](https://github.com/agentscope-ai/CoPaw/pull/1660))

## 🔄 Changed

**Core & Lifecycle**

- **Graceful Lifecycle Management**: Desktop subprocess, agent reload, and shutdown are now handled gracefully — subprocesses terminate cleanly on close, agents reload with zero downtime, and active tasks are awaited before shutdown ([#1646](https://github.com/agentscope-ai/CoPaw/pull/1646), [#1664](https://github.com/agentscope-ai/CoPaw/pull/1664), [#1714](https://github.com/agentscope-ai/CoPaw/pull/1714))
- **Custom Working Directory**: Replaced hardcoded `~/.copaw` paths throughout the codebase so custom working directories (`COPAW_WORKING_DIR`) work correctly ([#1652](https://github.com/agentscope-ai/CoPaw/pull/1652))

**Providers & Models**

- **Provider / Model Consistency**: The console now re-fetches active models on navigation so the displayed provider and model stay in sync ([#1420](https://github.com/agentscope-ai/CoPaw/pull/1420))
- **Ollama Default Address**: Changed Ollama default address from `localhost` to `127.0.0.1` for more reliable connections ([#1480](https://github.com/agentscope-ai/CoPaw/pull/1480))
- **Provider Request Headers**: Improved provider-specific HTTP header handling with exact URL matching for DashScope ([#1757](https://github.com/agentscope-ai/CoPaw/pull/1757))

**Console, UI & Platform**

- **Console Internationalization**: Improved multi-language support in the console, including synced locale settings and localized document navigation ([#1409](https://github.com/agentscope-ai/CoPaw/pull/1409), [#1686](https://github.com/agentscope-ai/CoPaw/pull/1686), [#1707](https://github.com/agentscope-ai/CoPaw/pull/1707))
- **Workspace Path**: Workspace path is now read-only when editing an existing agent to prevent accidental changes ([#1624](https://github.com/agentscope-ai/CoPaw/pull/1624), [#1764](https://github.com/agentscope-ai/CoPaw/pull/1764))
- **Windows Desktop Startup**: Pre-compiled Python bytecode for faster Windows desktop startup ([#1639](https://github.com/agentscope-ai/CoPaw/pull/1639))
- **QQ Channel Reply Logic**: Improved reply logic with DM support and better handling of blocked URLs ([#1650](https://github.com/agentscope-ai/CoPaw/pull/1650))

## 🐛 Fixed

**Channels**

- **Telegram**: Fixed thread replies, media handling, and error reporting. Polling now auto-reconnects with exponential backoff on network failure ([#1210](https://github.com/agentscope-ai/CoPaw/pull/1210), [#1475](https://github.com/agentscope-ai/CoPaw/pull/1475))
- **Discord**: Fixed messages from different channels being incorrectly merged; normalized Discord IDs for cron dispatch. The debounce fix was also generalized to all channels ([#300](https://github.com/agentscope-ai/CoPaw/pull/300), [#1002](https://github.com/agentscope-ai/CoPaw/pull/1002), [#1583](https://github.com/agentscope-ai/CoPaw/pull/1583))
- **DingTalk**: Fixed incorrect message skipping when sender info is partially missing; skipped empty text blocks in rich text parsing ([#851](https://github.com/agentscope-ai/CoPaw/pull/851), [#1554](https://github.com/agentscope-ai/CoPaw/pull/1554))
- **Feishu**: Fixed card tables exceeding the per-card element limit; added voice message support ([#1627](https://github.com/agentscope-ai/CoPaw/pull/1627), [#1726](https://github.com/agentscope-ai/CoPaw/pull/1726))

**Providers & Models**

- **Ollama / LM Studio**: Fixed context length settings not taking effect; connection and model-fetch errors now show the actual error message ([#1427](https://github.com/agentscope-ai/CoPaw/pull/1427), [#1745](https://github.com/agentscope-ai/CoPaw/pull/1745))
- **Streaming Response**: Fixed a crash when streaming response chunks have no choices ([#1524](https://github.com/agentscope-ai/CoPaw/pull/1524))
- **Reasoning Content**: Fixed reasoning content being lost when the message formatter changes the assistant message count ([#1557](https://github.com/agentscope-ai/CoPaw/pull/1557))
- **Tool Choice**: Fixed `tool_choice` being incorrectly forced to `auto`; it is now passed through as-is ([#1570](https://github.com/agentscope-ai/CoPaw/pull/1570))

**Skills**

- **Cron Jobs**: Fixed weekday name mismatch causing cron jobs to fire on wrong days; added UTC time context to prevent timezone drift; custom cron expressions now survive editing in the UI; invalid cron jobs are gracefully skipped ([#1269](https://github.com/agentscope-ai/CoPaw/pull/1269), [#1432](https://github.com/agentscope-ai/CoPaw/pull/1432), [#1257](https://github.com/agentscope-ai/CoPaw/pull/1257), [#1734](https://github.com/agentscope-ai/CoPaw/pull/1734), [#1768](https://github.com/agentscope-ai/CoPaw/pull/1768))
- **Skills**: Fixed import failures when skill names contain `/`; removed duplicate built-in skill listings; fixed incomplete file imports from bundles; restored skill enable/disable after sync refactor; added cancel option and timeout reminder for slow imports; skill descriptions now display correctly in the console ([#1369](https://github.com/agentscope-ai/CoPaw/pull/1369), [#1396](https://github.com/agentscope-ai/CoPaw/pull/1396), [#1576](https://github.com/agentscope-ai/CoPaw/pull/1576), [#1716](https://github.com/agentscope-ai/CoPaw/pull/1716), [#1720](https://github.com/agentscope-ai/CoPaw/pull/1720), [#1626](https://github.com/agentscope-ai/CoPaw/pull/1626))

**Console, UI & Platform**

- **Memory Compaction**: Fixed a crash when the system prompt is empty during memory compaction ([#1608](https://github.com/agentscope-ai/CoPaw/pull/1608))
- **Console Chat**: Fixed unwanted page redirect on refresh; copy now extracts text content instead of raw JSON; session list refreshes correctly when switching agents ([#1373](https://github.com/agentscope-ai/CoPaw/pull/1373), [#1471](https://github.com/agentscope-ai/CoPaw/pull/1471), [#1662](https://github.com/agentscope-ai/CoPaw/pull/1662))
- **Console UI**: Fixed static resource loading failures, workspace list refresh, workspace path display, and miscellaneous TypeScript errors ([#1402](https://github.com/agentscope-ai/CoPaw/pull/1402), [#1737](https://github.com/agentscope-ai/CoPaw/pull/1737), [#1764](https://github.com/agentscope-ai/CoPaw/pull/1764), [#1769](https://github.com/agentscope-ai/CoPaw/pull/1769))
- **Windows Compatibility**: Fixed cross-disk file moves, suppressed spurious AutoRun stderr in shell commands, and fixed emoji/Unicode logging on GBK consoles ([#1483](https://github.com/agentscope-ai/CoPaw/pull/1483), [#1556](https://github.com/agentscope-ai/CoPaw/pull/1556), [#1601](https://github.com/agentscope-ai/CoPaw/pull/1601), [#1495](https://github.com/agentscope-ai/CoPaw/pull/1495))

## 📚 Documentation

- **Ollama Context Length**: Added a warning about Ollama and LM Studio context length configuration ([#1433](https://github.com/agentscope-ai/CoPaw/pull/1433))
- **Chinese Docs**: Fixed formatting and consistency issues across Chinese documentation ([#1300](https://github.com/agentscope-ai/CoPaw/pull/1300))
- **Docker QuickStart**: Aligned Docker secrets documentation on the QuickStart page ([#1584](https://github.com/agentscope-ai/CoPaw/pull/1584))
- **Cron Skill**: Updated `--channel` options in cron skill docs to list all supported channels ([#1541](https://github.com/agentscope-ai/CoPaw/pull/1541))
- **Channel Allowlist**: Added documentation for channel allowlist configuration, mentions, and ID hints ([#1760](https://github.com/agentscope-ai/CoPaw/pull/1760))
- **Developer Community**: Added developer community group information ([#1678](https://github.com/agentscope-ai/CoPaw/pull/1678))
- **Console**: Updated the release note link in the console UI ([#1622](https://github.com/agentscope-ai/CoPaw/pull/1622))

## New Contributors

- @dipeshbabu made their first contribution in [#851](https://github.com/agentscope-ai/CoPaw/pull/851)
- @sljeff made their first contribution in [#1269](https://github.com/agentscope-ai/CoPaw/pull/1269)
- @octo-patch made their first contribution in [#1376](https://github.com/agentscope-ai/CoPaw/pull/1376)
- @Alexxigang made their first contribution in [#1396](https://github.com/agentscope-ai/CoPaw/pull/1396)
- @howyoungchen made their first contribution in [#1432](https://github.com/agentscope-ai/CoPaw/pull/1432)
- @nphenix made their first contribution in [#1495](https://github.com/agentscope-ai/CoPaw/pull/1495)
- @skyfaker made their first contribution in [#1498](https://github.com/agentscope-ai/CoPaw/pull/1498)
- @hh0592821 made their first contribution in [#1210](https://github.com/agentscope-ai/CoPaw/pull/1210)
- @futuremeng made their first contribution in [#1480](https://github.com/agentscope-ai/CoPaw/pull/1480)
- @toby1123yjh made their first contribution in [#1541](https://github.com/agentscope-ai/CoPaw/pull/1541)
- @hiyuchang made their first contribution in [#1522](https://github.com/agentscope-ai/CoPaw/pull/1522)
- @hanson-hex made their first contribution in [#1300](https://github.com/agentscope-ai/CoPaw/pull/1300)
- @JackyMao1999 made their first contribution in [#1320](https://github.com/agentscope-ai/CoPaw/pull/1320)
- @mvanhorn made their first contribution in [#1556](https://github.com/agentscope-ai/CoPaw/pull/1556)
- @yuanxs21 made their first contribution in [#1584](https://github.com/agentscope-ai/CoPaw/pull/1584)
- @aissac made their first contribution in [#1608](https://github.com/agentscope-ai/CoPaw/pull/1608)
- @lcq225 made their first contribution in [#1601](https://github.com/agentscope-ai/CoPaw/pull/1601)
- @Justin-lu made their first contribution in [#1118](https://github.com/agentscope-ai/CoPaw/pull/1118)
- @rowanchen-com made their first contribution in [#1329](https://github.com/agentscope-ai/CoPaw/pull/1329)
- @pzlav made their first contribution in [#1484](https://github.com/agentscope-ai/CoPaw/pull/1484)
- @mautops made their first contribution in [#1725](https://github.com/agentscope-ai/CoPaw/pull/1725)

**Full Changelog**: https://github.com/agentscope-ai/CoPaw/compare/v0.0.7...v0.1.0
