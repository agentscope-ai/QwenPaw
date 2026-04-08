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

- **本地必跑门禁（push/提 PR 前必须通过）：**
  ```bash
  pip install -e ".[dev,full]"
  pre-commit install
  pre-commit run --all-files
  pytest
  ```
- **如果 pre-commit 自动修改了文件：** 先提交这些修改，再重复执行
  `pre-commit run --all-files`，直到无修改且通过。
- **CI 策略：** pre-commit 检查失败的 PR 视为未就绪（not merge-ready）。
- **前端代码格式化：** 如果你的修改涉及到 `console` 或 `website` 目录，请在提交前运行格式化：
  ```bash
  cd console && npm run format
  cd website && npm run format
  ```
- **文档：** 当你添加或更改面向用户的行为时，更新文档和 README。文档位于 `website/public/docs/` 下。

---

## 贡献类型

CoPaw 设计为**可扩展的**：你可以添加模型、频道、Skills 等。以下是我们关心的主要贡献领域。

---

### 添加新模型 / 模型提供商

CoPaw 支持多种提供商：包括云提供商（如 DashScope、ModelScope）以及本地提供商（如 Ollama、LM Studio），但我们也欢迎新的模型供应商以丰富用户选择。

贡献的模型提供商具有以下特征：

1. （强制）原生兼容 OpenAI `chat.completions` API 或 Anthropic `messages` API，如不满足该条件，请先创建 issue 讨论，直接添加一个不兼容的提供商会大幅增加维护成本。
2. （推荐）支持 `/model/list` 端点以自动获取模型列表，虽然不强制，但这会大大提升用户体验。

确定满足上述条件后，可以在 `src/copaw/providers/provider_manager.py` 中创建新的 Provider 实例并在 `ProviderManager` 类中注册，使其成为 CoPaw 内置的提供商。

如果想要将新的提供商作为内置提供商贡献，请在 PR 中提供以下内容：

1. （强制）内置至少一个通过测试的模型，确保模型列表不为空，并且在 PR 中提供连接测试以及使用该模型的聊天实例截图。
2. （强制）在模型文档（`website/public/docs/models.*.md`）的提供商列表中增加该提供商，并且如果该提供商的配置与其他提供商有明显区别，应该单独开一节详细说明。
3. （推荐）为内置的模型提前设置能力标签（例如是否支持图片、视频），这能够减少用户手动验证模型能力的开销。

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

#### 编写有效的 Skill Description

为了让 model 能够准确识别并调用你的 skill，`description` 字段必须**清晰、具体且包含触发词**。请遵循以下最佳实践：

**✅ 推荐格式：**
```yaml
---
name: example_skill
description: "Use this skill whenever user wants to [主要功能]. Trigger especially when user mentions: [触发词列表]. Also use when [其他场景]."

# 详细说明
...
```

**✅ 最佳实践：**
1. **明确触发时机**：使用 "Use this skill whenever user wants to..." 或 "Trigger when user asks for..."
2. **列出触发关键词**：在 description 中明确列出触发词，例如：
   - "Trigger especially when user mentions: \"call\", \"dial\", \"phone\", \"microsip\""
   - "Also trigger for desktop automation tasks like opening apps, controlling windows"
3. **具体描述功能范围**：说明技能做什么，不要含糊
   - ✅ 好的："Make phone calls via MicroSIP or similar desktop apps"
   - ❌ 不好："Control desktop"
4. **提供使用示例**：如果技能有特定用法，在 SKILL.md 主体部分说明

**❌ 常见问题：**
- 描述过于抽象（如"控制桌面"、"处理文件"）
- 没有列出触发关键词，导致 model 无法识别
- 缺少使用场景说明

**📝 示例对比：**

| 技能 | 描述（不好） | 描述（好） |
|------|---------------|-------------|
| Desktop Control | "控制桌面应用" | "Use this skill whenever user wants to control desktop applications or make phone calls. Trigger especially when user mentions: \"call\" (呼叫), \"dial\" (拨打), \"phone\" (电话), \"microsip\", or requests to use specific desktop apps." |
| File Reader | "读取文件" | "Use this skill when user asks to read or summarize local text-based files. PDFs, Office documents, and images are out of scope." |

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
- 在 issue 中首先讨论大型或涉及敏感的更改。
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
