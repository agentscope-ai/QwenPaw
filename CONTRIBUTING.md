# Contributing to QwenPaw

## Welcome! 🐾

Thank you for your interest in contributing to QwenPaw! QwenPaw is an open-source **personal AI assistant** that runs in your own environment—on your machine or in the cloud. It connects to DingTalk, Feishu, QQ, Discord, iMessage, and other chat apps, supports scheduled tasks and heartbeat, and extends its capabilities through **Skills**. We warmly welcome contributions that help make QwenPaw more useful for everyone: whether you add a new channel, a new model provider, a Skill, improve docs, or fix bugs.

**Quick links:** [GitHub](https://github.com/agentscope-ai/QwenPaw) · [Docs](https://qwenpaw.agentscope.io/) · [License: Apache 2.0](LICENSE)

---

## How to Contribute

To keep collaboration smooth and maintain quality, please follow these guidelines.

### 1. Check Existing Plans and Issues

Before starting:

- **Check [Open Issues](https://github.com/agentscope-ai/QwenPaw/issues)** and any [Projects](https://github.com/agentscope-ai/QwenPaw/projects) or roadmap labels.
- **If a related issue exists** and is open or unassigned: comment to say you want to work on it to avoid duplicate effort.
- **If no related issue exists**: open a new issue describing your proposal. The maintainers will respond and can help align with the project direction.

### 2. Commit Message Format

We follow the [Conventional Commits](https://www.conventionalcommits.org/) specification for clear history and tooling.

**Format:**
```
<type>(<scope>): <subject>
```

**Types:**
- `feat:` New feature
- `fix:` Bug fix
- `docs:` Documentation only
- `style:` Code style (whitespace, formatting, etc.)
- `refactor:` Code change that neither fixes a bug nor adds a feature
- `perf:` Performance improvement
- `test:` Adding or updating tests
- `chore:` Build, tooling, or maintenance

**Examples:**
```bash
feat(channels): add Telegram channel stub
fix(skills): correct SKILL.md front matter parsing
docs(readme): update quick start for Docker
refactor(providers): simplify custom provider validation
test(agents): add tests for skill loading
```

### 3. Pull Request Title Format

PR titles should follow the same convention:

**Format:** ` <type>(<scope>): <description> `

- Use one of: `feat`, `fix`, `docs`, `test`, `refactor`, `chore`, `perf`, `style`, `build`, `revert`.
- **Scope must be lowercase** (letters, numbers, hyphens, underscores only).
- Keep the description short and descriptive.

**Examples:**
```
feat(models): add custom provider for Azure OpenAI
fix(channels): handle empty content_parts in Discord
docs(skills): document Skills Hub import
```

### 4. Code and Quality

- **Required local gate (must pass before push/PR):**
  ```bash
  pip install -e ".[dev,full]"
  pre-commit install
  pre-commit run --all-files
  pytest
  ```
- **If pre-commit modifies files:** Commit those changes, then rerun
  `pre-commit run --all-files` until it passes cleanly.
- **CI policy:** Pull requests with failing pre-commit checks are not merge-ready.
- **Frontend formatting:** If your changes involve the `console` or `website` directories, run the formatter before committing:
  ```bash
  cd console && npm run format
  cd website && npm run format
  ```
- **Documentation:** Update docs and README when you add or change user-facing behavior. The docs live under `website/public/docs/`.

---

## Types of Contributions

QwenPaw is designed to be **extensible**: you can add models, channels, Skills, and more. Below are the main contribution areas we care about.

---

### Adding New Models / Model Providers

QwenPaw supports multiple providers, including cloud providers (such as DashScope, ModelScope, OpenAI, Anthropic, and Venice.ai) and local providers (such as Ollama, LM Studio). We also welcome new model providers to enrich user choices.

Contributed model providers should have the following characteristics:

1. (Required) Natively compatible with the OpenAI `chat.completions` API or Anthropic `messages` API. If this condition is not met, please create an issue for discussion first. Directly adding an incompatible provider will significantly increase maintenance costs.
2. (Recommended) Support the `/model/list` endpoint to automatically obtain the model list. Although not mandatory, this will greatly enhance the user experience.

If the above conditions are met, you can create a new Provider instance in `src/qwenpaw/providers/provider_manager.py` and register it in the `ProviderManager` class to make it a built-in provider in QwenPaw.

If you wish to submit a Pull Request, please ensure that the following conditions are met.

1. (Required) Include at least one tested model to ensure the model list is not empty, and provide a connection test and a screenshot of a chat session using this model in the PR.
2. (Required) Add the provider to the provider list in the model documentation (website/public/docs/models.*.md). If the provider's configuration is significantly different from others, a separate section should be added for detailed explanation.
3. (Recommended) Pre-set capability tags for the built-in model (such as whether it supports images or videos). This can reduce the user's effort in manually verifying model capabilities.

---

### Adding New Channels

Channels are how QwenPaw talks to **DingTalk, Feishu, QQ, Discord, iMessage**, etc. You can add a new channel so QwenPaw can work with your favorite IM or bot platform.

- **Protocol:** All channels use a unified in-process contract: **native payload → `content_parts`** (e.g. `TextContent`, `ImageContent`, `FileContent`). The agent receives `AgentRequest` with these content parts; replies are sent back via the channel’s send path.
- **Implementation:** Implement a **subclass of `BaseChannel`** (in `src/qwenpaw/app/channels/base.py`):
  - Set the class attribute `channel` to a unique channel key (e.g. `"telegram"`).
  - Implement the lifecycle and message handling (e.g. receive → `content_parts` → `process` → send response).
  - Use the manager’s queue and consumer loop if the channel is long-lived (default).
- **Discovery:** Built-in channels are registered in `src/qwenpaw/app/channels/registry.py`. **Custom channels** are loaded from the working directory: place a module (e.g. `custom_channels/telegram.py` or a package `custom_channels/telegram/`) that defines a `BaseChannel` subclass with a `channel` attribute.
- **CLI:** Users install/add channels with:
  - `qwenpaw channels install <key>` — create a template or copy from `--path` / `--url`
  - `qwenpaw channels add <key>` — install and add to config
  - `qwenpaw channels remove <key>` — remove custom channel from `custom_channels/`
  - `qwenpaw channels config` — interactive config

If you contribute a **new built-in channel**, add it to the registry and, if needed, a configurator so it appears in the Console and CLI. Document the new channel (auth, webhooks, etc.) in `website/public/docs/channels.*.md`.

---

### Adding Base Skills

**Skills** define what QwenPaw can do: cron, file reading, PDF/Office, news, browser, etc. We welcome **broadly useful** base skills (productivity, documents, communication, automation) that fit the majority of users.

- **Structure:** Each skill is a **directory** containing:
  - **`SKILL.md`** — Markdown instructions for the agent. Use YAML front matter for at least `name` and `description`; optional `metadata` (e.g. for Console).
  - **`references/`** (optional) — Reference documents the agent can use.
  - **`scripts/`** (optional) — Scripts or tools the skill uses.
- **Location:** Built-in skills live under `src/qwenpaw/agents/skills/<skill_name>/`. The app merges built-in and user **customized_skills** from the working dir into **active_skills**; no extra registration is needed beyond placing a valid `SKILL.md` in a directory.
- **Content:** Write clear, task-oriented instructions. Describe **when** the skill should be used and **how** (steps, commands, file formats). Avoid overly niche or personal workflows if targeting the **base** repository; those are great as custom or community Skills.
- **Skills Hub:** QwenPaw supports importing skills from a community hub (e.g. ClawHub). If you want your skill to be installable via hub, follow the same `SKILL.md` + `references/`/`scripts/` layout and the hub’s packaging format.

Examples of in-repo base skills: **cron**, **file_reader**, **news**, **pdf**, **docx**, **pptx**, **xlsx**, **browser_visible**. Contributing a new base skill usually means: add the directory under `agents/skills/`, add a short entry in the docs (e.g. Skills table in `website/public/docs/skills.*.md`), and ensure it syncs correctly to the working directory.

#### Writing Effective Skill Descriptions

To help the model accurately recognize and invoke your skill, the `description` field in your SKILL.md front matter must be **clear, specific, and include trigger keywords**. Follow these best practices:

**✅ Recommended format:**
```yaml
---
name: example_skill
description: "Use this skill whenever user wants to [main functionality]. Trigger especially when user mentions: [trigger keywords]. Also use when [other scenarios]."

# Detailed instructions below
...
```

**✅ Best practices:**
1. **Clearly state when to trigger**: Use phrases like "Use this skill whenever user wants to..." or "Trigger when user asks for..."
2. **List trigger keywords explicitly**: Make it easy for the model to recognize, for example:
   - "Trigger especially when user mentions: \"call\", \"dial\", \"phone\", \"microsip\""
   - "Also trigger for desktop automation tasks like opening apps, controlling windows"
3. **Be specific about the skill's scope**: Say exactly what it does, avoid vague terms
   - ✅ Good: "Make phone calls via MicroSIP or similar desktop apps"
   - ❌ Not ideal: "Control desktop"
4. **Provide usage examples**: If the skill has specific usage patterns, explain them in the body of SKILL.md

**❌ Common pitfalls:**
- Overly abstract descriptions (like "control desktop", "process files")
- Missing trigger keywords, making it hard for the model to identify use cases
- Lack of usage scenario context

**📝 Examples comparison:**

| Skill | Description (Not ideal) | Description (Better) |
|-------|-------------------------|----------------------|
| Desktop Control | "Control desktop applications" | "Use this skill whenever user wants to control desktop applications or make phone calls. Trigger especially when user mentions: \"call\", \"dial\", \"phone\", \"microsip\", or requests to use specific desktop apps." |
| File Reader | "Read files" | "Use this skill when user asks to read or summarize local text-based files. PDFs, Office documents, images are out of scope." |

---

### Platform support (Windows, Linux, macOS, etc.)

QwenPaw aims to run on **Windows**, **Linux**, and **macOS**. Contributions that improve support on a specific platform are welcome.

- **Compatibility fixes:** Path handling, line endings, shell commands, or dependencies that behave differently per OS. For example: Windows compatibility for the memory/vector stack, or install scripts that work on both Linux and macOS.
- **Install and run:** One-line install (`install.sh`), `pip` install, and `qwenpaw init` / `qwenpaw app` should work (or be clearly documented) on each supported platform. Fixes to install or startup on a given OS are valuable.
- **Platform-specific features:** Optional integrations (e.g. notifying only when supported) are fine as long as they don’t break other platforms. Use runtime checks or optional dependencies where appropriate.
- **Documentation:** Document any platform-specific steps, known limitations, or recommended setups (e.g. WSL on Windows, Apple Silicon vs x86) in the docs or README.

If you add or change platform support, please test on the affected OS and mention it in the PR description. Opening an issue first is recommended for larger or ambiguous platform work.

---

### Other Contributions

- **MCP (Model Context Protocol):** QwenPaw supports runtime **MCP tool** discovery and hot-plug. Contributing new MCP servers or tools (or docs on how to attach them) helps users extend the agent without changing core code.
- **Documentation:** Fixes and improvements to [the docs](https://qwenpaw.agentscope.io/) (under `website/public/docs/`) and README are always welcome.
- **Bug fixes and refactors:** Small fixes, clearer error messages, and refactors that keep behavior the same are valuable. Prefer opening an issue for larger refactors so we can align on approach.
- **Examples and workflows:** Tutorials or example workflows (e.g. “daily digest to DingTalk”, “local model + cron”) can be documented or linked from the repo/docs.
- **Any other useful things!**
---

## Do's and Don'ts

### ✅ DO

- Start with small, focused changes.
- Discuss large or design-sensitive changes in an issue first.
- Write or update tests where applicable.
- Update documentation for user-facing changes.
- Use conventional commit messages and PR titles.
- Be respectful and constructive (we follow a welcoming Code of Conduct).

### ❌ DON'T

- Don’t open very large PRs without prior discussion.
- Don’t ignore CI or pre-commit failures.
- Don’t mix unrelated changes in one PR.
- Don’t break existing APIs without a good reason and clear migration notes.
- Don’t add heavy or optional dependencies to the core install without discussing in an issue.

---

## Getting Help

- **Discussions:** [GitHub Discussions](https://github.com/agentscope-ai/QwenPaw/discussions)
- **Bugs and features:** [GitHub Issues](https://github.com/agentscope-ai/QwenPaw/issues)
- **Community:** DingTalk group (see [README](README.md)) and [Discord](https://discord.gg/eYMpfnkG8h)

Thank you for contributing to QwenPaw. Your work helps make it a better assistant for everyone. 🐾
