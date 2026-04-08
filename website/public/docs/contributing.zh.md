# 开源与贡献

CoPaw 已开源，项目仓库托管于 GitHub：

**https://github.com/agentscope-ai/CoPaw**

---

## 🎯 如何参与贡献

感谢你对 CoPaw 的关注，我们热烈欢迎各种贡献！为了保持协作顺畅并维护质量，请遵循以下指南。

### 1. 查看现有计划和 Issues

开始之前：

- **查看 [Open Issues](https://github.com/agentscope-ai/CoPaw/issues)** 和 [路线图](/docs/roadmap)
- **如果相关 Issue 已存在**且开放或未分配：在评论中说明你想要处理它，避免重复工作
- **如果没有相关 Issue**：开一个新 Issue 描述你的提案。维护者会回复并帮助与项目方向对齐

### 2. 提交信息格式

我们遵循 [Conventional Commits](https://www.conventionalcommits.org/) 规范，以保持清晰的历史记录。

**格式：**

```
<type>(<scope>): <subject>
```

**类型：**

- `feat:` 新功能
- `fix:` Bug 修复
- `docs:` 仅文档
- `style:` 代码风格（空格、格式等）
- `refactor:` 既不修复 Bug 也不添加功能的代码更改
- `perf:` 性能改进
- `test:` 添加或更新测试
- `chore:` 构建、工具或维护

**示例：**

```bash
feat(channels): 添加 Telegram 频道支持
fix(skills): 修复 SKILL.md 前置元数据解析
docs(readme): 更新 Docker 快速开始说明
refactor(providers): 简化自定义提供商验证
test(agents): 为 skill 加载添加测试
```

### 3. Pull Request 标题格式

PR 标题应遵循相同的约定：

**格式：** `<type>(<scope>): <description>`

- 使用以下类型之一：`feat`, `fix`, `docs`, `test`, `refactor`, `chore`, `perf`, `style`, `build`, `revert`
- **作用域必须小写**（仅字母、数字、连字符、下划线）
- 保持描述简短且具有描述性

**示例：**

```
feat(models): 为 Azure OpenAI 添加自定义提供商
fix(channels): 处理 Discord 中的空 content_parts
docs(skills): 记录 Skills Hub 导入
```

### 4. 代码与质量

- **必需的本地检查（提交/PR 前必须通过）：**
  ```bash
  pip install -e ".[dev,full]"
  pre-commit install
  pre-commit run --all-files
  pytest
  ```
- **如果 pre-commit 修改了文件：** 提交这些更改，然后重新运行 `pre-commit run --all-files` 直到通过
- **CI 策略：** pre-commit 检查失败的 PR 不能合并
- **前端格式化：** 如果你的更改涉及 `console` 或 `website` 目录，提交前运行格式化工具：
  ```bash
  cd console && npm run format
  cd website && pnpm format
  ```
- **文档：** 当你添加或更改面向用户的行为时更新文档。文档位于 `website/public/docs/` 目录

---

## 💬 获取帮助

- **Discussions：** [GitHub Discussions](https://github.com/agentscope-ai/CoPaw/discussions)
- **Bugs 和功能：** [GitHub Issues](https://github.com/agentscope-ai/CoPaw/issues)
- **社区和开发者群：** 见[社区页面](/docs/community)

---

## 🗺️ 路线图

查看我们的[路线图](/docs/roadmap)，了解标记为 **征集中** 的项目（如新频道、模型提供商、Skills、MCP，或展示/交互优化等）——这些都是很好的切入点！

---

感谢你为 CoPaw 做出贡献。你的工作帮助它成为每个人更好的助手。🐾
