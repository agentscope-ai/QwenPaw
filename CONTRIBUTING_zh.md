# 为 CoPaw 贡献代码

## 欢迎！🐾

感谢你对 CoPaw 的关注！CoPaw 是一个开源的**个人 AI 助手**，可以在你自己的环境中运行——无论是你的机器还是云端。它可以连接钉钉、飞书、QQ、Discord、iMessage 等聊天应用，支持定时任务和心跳机制，并通过 **Skills** 扩展其能力。我们热烈欢迎能让 CoPaw 对所有人更有用的贡献：无论是添加新的频道、新的模型提供商、Skill，改进文档，还是修复 bug。

**快速链接：** [GitHub](https://github.com/agentscope-ai/CoPaw) · [文档](https://copaw.agentscope.io/) · [许可证：Apache 2.0](LICENSE)

---

## 如何贡献

为了保持协作顺畅并维护质量，请遵循以下指南。

### 1. 检查现有计划和问题

在开始之前：

- **检查 [Open Issues](https://github.com/agentscope-ai/CoPaw/issues)** 以及任何 [Projects](https://github.com/agentscope-ai/CoPaw/projects) 或路线图标签。
- **如果存在相关 issue** 且处于开放或未分配状态：发表评论表示你想要处理它，以避免重复工作。
- **如果不存在相关 issue**：创建一个新 issue 描述你的提案。维护者会回复并帮助与项目方向对齐。

### 2. 提交信息格式

我们遵循 [Conventional Commits](https://www.conventionalcommits.org/) 规范，以保持清晰的历史记录和工具支持。

**格式：**
```
<type>(<scope>): <subject>
```

**类型：**
- `feat:` 新功能
- `fix:` Bug 修复
- `docs:` 仅文档更改
- `style:` 代码风格（空格、格式等）
- `refactor:` 既不修复 bug 也不添加功能的代码更改
- `perf:` 性能改进
- `test:` 添加或更新测试
- `chore:` 构建、工具或维护

**示例：**
```bash
feat(channels): add Telegram channel stub
fix(skills): correct SKILL.md front matter parsing
docs(readme): update quick start for Docker
refactor(providers): simplify custom provider validation
test(agents): add tests for skill loading
```

### 3. Pull Request 标题格式

PR 标题应遵循相同的约定：

**格式：** ` <type>(<scope>): <description> `

- 使用以下之一：`feat`、`fix`、`docs`、`test`、`refactor`、`chore`、`perf`、`style`、`build`、`revert`。
- **scope 必须小写**（仅字母、数字、连字符、下划线）。
- 保持描述简短且描述性强。

**示例：**
```
feat(models): add custom provider for Azure OpenAI
fix(channels): handle empty content_parts in Discord
docs(skills): document Skills Hub import
```

### 4. 代码和质量

- **Pre-commit：** 安装并运行 pre-commit 以保持一致的风格和检查：
  ```bash
  pip install -e ".[dev]"
  pre-commit install
  pre-commit run --all-files
  ```
- **测试：** 提交前运行测试：
  ```bash
  pytest
  ```
- **文档：** 当你添加或更改面向用户的行为时，更新文档和 README。文档位于 `website/public/docs/` 下。

---

## 贡献类型

CoPaw 设计为**可扩展的**：你可以添加模型、频道、Skills 等。以下是我们关心的主要贡献领域。

---

### 添加新模型 / 模型提供商

CoPaw 支持**多种模型后端**：云 API（如 DashScope、ModelScope）、**Ollama** 和本地后端（**llama.cpp**、**MLX**）。你可以通过两种方式贡献：

#### A. 自定义提供商（用户配置）

用户可以通过 Console 或 `providers.json` 添加**自定义提供商**：任何 OpenAI 兼容的 API（如 vLLM、SGLang、私有端点）都可以通过唯一 ID、base URL、API key 和可选的模型列表进行配置。标准 OpenAI 兼容 API 无需代码更改。

#### B. 新的内置提供商或新的 ChatModel（代码贡献）

如果你想添加**新的内置提供商**或**不兼容 OpenAI 的新 API 协议**：

1. **提供商定义**（在 `src/copaw/providers/registry.py` 或等效位置）：
   - 添加一个 `ProviderDefinition`，包含 `id`、`name`、`default_base_url`、`api_key_prefix`，以及可选的 `models` 和 `chat_model`。
   - 对于本地/自托管后端，根据需要设置 `is_local`。

2. **聊天模型类**（如果 API 不兼容 OpenAI）：
   - 实现一个继承自 `agentscope.model.ChatModelBase` 的类（或适用时使用 CoPaw 的本地/远程包装器）。
   - 如果 agent 同时使用流式和非流式，则都要支持；如果使用了 tools API，则遵守 `tool_choice` 和 tools。
   - 在注册表的聊天模型映射中注册该类，以便运行时可以按名称解析它（参见 `src/copaw/providers/registry.py` 中的 `_CHAT_MODEL_MAP`）。

3. **文档：** 在文档中记录新的提供商或模型（例如在"模型"或"提供商"部分下），并提及任何环境变量或配置键。

添加全新的 API（新消息格式、token 计数、tools）是较大的更改；我们建议先创建 issue 讨论范围和设计。

---

### 添加新频道

频道是 CoPaw 与**钉钉、飞书、QQ、Discord、iMessage** 等通信的方式。你可以添加新频道，以便 CoPaw 可以与你喜欢的 IM 或机器人平台配合使用。

- **协议：** 所有频道使用统一的进程内契约：**原生 payload → `content_parts`**（如 `TextContent`、`ImageContent`、`FileContent`）。agent 接收带有这些内容部分的 `AgentRequest`；回复通过频道的发送路径返回。
- **实现：** 实现 **`BaseChannel` 的子类**（在 `src/copaw/app/channels/base.py` 中）：
  - 将类属性 `channel` 设置为唯一的频道键（如 `"telegram"`）。
  - 实现生命周期和消息处理（如 receive → `content_parts` → `process` → send response）。
  - 如果频道是长期运行的（默认），使用 manager 的队列和消费者循环。
- **发现：** 内置频道在 `src/copaw/app/channels/registry.py` 中注册。**自定义频道**从工作目录加载：放置一个模块（如 `custom_channels/telegram.py` 或包 `custom_channels/telegram/`），定义一个带有 `channel` 属性的 `BaseChannel` 子类。
- **CLI：** 用户使用以下命令安装/添加频道：
  - `copaw channels install <key>` — 创建模板或从 `--path` / `--url` 复制
  - `copaw channels add <key>` — 安装并添加到配置
  - `copaw channels remove <key>` — 从 `custom_channels/` 中删除自定义频道
  - `copaw channels config` — 交互式配置

如果你贡献**新的内置频道**，将其添加到注册表，如有需要，添加配置器以使其出现在 Console 和 CLI 中。在 `website/public/docs/channels.*.md` 中记录新频道（身份验证、webhooks 等）。

---

### 添加基础 Skills

**Skills** 定义了 CoPaw 可以做什么：cron、文件读取、PDF/Office、新闻、浏览器等。我们欢迎**广泛有用的**基础 skills（生产力、文档、通信、自动化），适合大多数用户。

- **结构：** 每个 skill 是一个**目录**，包含：
  - **`SKILL.md`** — agent 的 Markdown 指令。使用 YAML front matter 至少包含 `name` 和 `description`；可选的 `metadata`（如用于 Console）。
  - **`references/`**（可选）— agent 可以使用的参考文档。
  - **`scripts/`**（可选）— skill 使用的脚本或工具。
- **位置：** 内置 skills 位于 `src/copaw/agents/skills/<skill_name>/` 下。应用程序将内置和用户的 **customized_skills**（来自工作目录）合并到 **active_skills** 中；除了在目录中放置有效的 `SKILL.md` 外，不需要额外的注册。
- **内容：** 编写清晰的、面向任务的指令。描述**何时**应该使用该 skill 以及**如何**使用（步骤、命令、文件格式）。如果针对**基础**仓库，避免过于小众或个人的工作流程；这些作为自定义或社区 Skills 非常好。
- **Skills Hub：** CoPaw 支持从社区 hub（如 ClawHub）导入 skills。如果你希望你的 skill 可以通过 hub 安装，请遵循相同的 `SKILL.md` + `references/`/`scripts/` 布局和 hub 的打包格式。

仓库内基础 skills 的示例：**cron**、**file_reader**、**news**、**pdf**、**docx**、**pptx**、**xlsx**、**browser_visible**。贡献新的基础 skill 通常意味着：在 `agents/skills/` 下添加目录，在文档中添加简短条目（如 `website/public/docs/skills.*.md` 中的 Skills 表），并确保它正确同步到工作目录。

---

### 平台支持（Windows、Linux、macOS 等）

CoPaw 旨在在 **Windows**、**Linux** 和 **macOS** 上运行。欢迎改进特定平台支持的贡献。

- **兼容性修复：** 路径处理、行尾、shell 命令或在不同操作系统上行为不同的依赖项。例如：内存/向量栈的 Windows 兼容性，或在 Linux 和 macOS 上都能工作的安装脚本。
- **安装和运行：** 一行安装（`install.sh`）、`pip` 安装，以及 `copaw init` / `copaw app` 应该在每个支持的平台上工作（或有清晰的文档说明）。对给定操作系统上的安装或启动的修复很有价值。
- **平台特定功能：** 可选集成（如仅在支持时通知）是可以的，只要它们不会破坏其他平台。在适当的地方使用运行时检查或可选依赖项。
- **文档：** 在文档或 README 中记录任何平台特定的步骤、已知限制或推荐设置（如 Windows 上的 WSL、Apple Silicon vs x86）。

如果你添加或更改平台支持，请在受影响的操作系统上进行测试，并在 PR 描述中提及。对于较大或模糊的平台工作，建议先创建 issue。

---

### 其他贡献

- **MCP（模型上下文协议）：** CoPaw 支持运行时 **MCP 工具**发现和热插拔。贡献新的 MCP 服务器或工具（或关于如何附加它们的文档）可以帮助用户扩展 agent 而无需更改核心代码。
- **文档：** 对 [文档](https://copaw.agentscope.io/)（位于 `website/public/docs/` 下）和 README 的修复和改进始终受欢迎。
- **Bug 修复和重构：** 小的修复、更清晰的错误消息以及保持行为相同的重构都很有价值。对于较大的重构，最好先创建 issue，以便我们可以就方法达成一致。
- **示例和工作流程：** 教程或示例工作流程（如"每日摘要到钉钉"、"本地模型 + cron"）可以记录或从仓库/文档链接。
- **任何其他有用的东西！**

---

## 应该做和不应该做

### ✅ 应该做

- 从小的、集中的更改开始。
- 在 issue 中首先讨论大型或设计敏感的更改。
- 在适用的地方编写或更新测试。
- 为面向用户的更改更新文档。
- 使用常规提交消息和 PR 标题。
- 保持尊重和建设性（我们遵循友好的行为准则）。

### ❌ 不应该做

- 不要在没有事先讨论的情况下打开非常大的 PR。
- 不要忽略 CI 或 pre-commit 失败。
- 不要在一个 PR 中混合不相关的更改。
- 不要在没有充分理由和清晰迁移说明的情况下破坏现有 API。
- 不要在没有在 issue 中讨论的情况下向核心安装添加重型或可选依赖项。

---

## 获取帮助

- **讨论：** [GitHub Discussions](https://github.com/agentscope-ai/CoPaw/discussions)
- **Bug 和功能：** [GitHub Issues](https://github.com/agentscope-ai/CoPaw/issues)
- **社区：** 钉钉群（见 [README](README_zh.md)）和 [Discord](https://discord.gg/eYMpfnkG8h)

感谢你为 CoPaw 贡献代码。你的工作帮助它成为每个人更好的助手。🐾
