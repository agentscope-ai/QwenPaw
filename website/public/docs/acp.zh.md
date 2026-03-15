# ACP (Agent Client Protocol)

**ACP（智能体客户端协议）** 允许 CoPaw 连接到外部编码智能体（如 OpenCode、Qwen-code、Gemini CLI）并使用它们的能力来增强 CoPaw 的功能。

---

## 什么是 ACP？

ACP 是一种用于连接外部智能体的协议，与 MCP（模型上下文协议）相比：

| 特性 | MCP | ACP |
|------|-----|-----|
| 连接目标 | 外部工具服务器 | 外部编码智能体 |
| 典型用途 | 文件系统访问、API 调用 | 代码生成、项目分析 |
| 交互模式 | 工具调用 | 对话式交互 |
| 示例 | filesystem、brave-search | OpenCode、Qwen-code |

---

## 前置要求

如果使用 `npx` 运行 ACP harnesses，请确保已安装：

- **Node.js** 18 或更高版本（[下载地址](https://nodejs.org/)）

检查 Node.js 版本：

```bash
node --version
```

---

## 配置说明

### 配置文件位置

ACP 配置存储在 `~/.copaw/config.json` 中：

```json
{
  "acp": {
    "enabled": true,
    "require_approval": false,
    "save_dir": "~/.copaw/acp_sessions",
    "harnesses": {
      "opencode": {
        "enabled": true,
        "command": "npx",
        "args": ["-y", "opencode-ai@latest", "acp"],
        "env": {}
      },
      "qwen": {
        "enabled": true,
        "command": "npx",
        "args": ["-y", "@qwen-code/qwen-code@latest", "--acp"],
        "env": {}
      }
    }
  }
}
```

### 配置项说明

| 配置项 | 类型 | 默认值 | 说明 |
|--------|------|--------|------|
| `enabled` | boolean | `false` | ACP 功能全局开关 |
| `require_approval` | boolean | `false` | 执行前是否需要用户批准 |
| `save_dir` | string | `"~/.copaw/acp_sessions"` | 会话状态保存目录 |
| `harnesses` | object | - | Harness 配置对象 |

### Harness 配置

每个 harness 支持以下配置：

| 配置项 | 类型 | 默认值 | 说明 |
|--------|------|--------|------|
| `enabled` | boolean | `false` | 是否启用该 harness |
| `command` | string | `""` | 启动命令 |
| `args` | string[] | `[]` | 命令参数 |
| `env` | object | `{}` | 环境变量 |

---

## 支持的 Harness

### OpenCode

OpenCode 是一个 AI 编码助手，支持多种编程语言和框架。

```json
{
  "opencode": {
    "enabled": true,
    "command": "npx",
    "args": ["-y", "opencode-ai@latest", "acp"]
  }
}
```

### Qwen-code

通义灵码的 ACP 支持，需要配置 API 密钥。

```json
{
  "qwen": {
    "enabled": true,
    "command": "npx",
    "args": ["-y", "@qwen-code/qwen-code@latest", "--acp"],
    "env": {
      "QWEN_CODE_API_KEY": "your-api-key"
    }
  }
}
```

### Gemini CLI

Google Gemini CLI 的实验性 ACP 支持。

```json
{
  "gemini": {
    "enabled": false,
    "command": "npx",
    "args": ["-y", "@google/gemini-cli@latest", "--experimental-acp"]
  }
}
```

---

## 使用示例

### 通过 `/acp` 命令触发

在聊天中输入以下命令触发 ACP：

```
/acp opencode 分析当前项目的代码结构
```

```
/acp qwen 解释这个函数的作用
```

### 通过自然语言触发

CoPaw 会自动识别需要 ACP 的场景：

```
帮我用 opencode 重构这段代码
```

```
让 qwen 分析一下这个 bug
```

### Session 复用

ACP 支持会话复用，保持上下文连贯：

```
/acp opencode 在当前 session 中继续分析
```

```
/acp opencode 使用之前的 session 继续工作
```

---

## 在控制台中配置 ACP

1. 打开控制台，进入 **智能体 → ACP**
2. 在"全局设置"中启用 ACP 功能
3. 配置需要的 Harness（启用、设置命令参数、环境变量）
4. 点击保存

---

## 常见问题

### Q: ACP 和 MCP 有什么区别？

A: MCP 用于连接外部工具服务器（如文件系统、搜索引擎），而 ACP 用于连接外部编码智能体（如 OpenCode、Qwen-code）。MCP 提供工具能力，ACP 提供智能体协作能力。

### Q: 如何添加自定义 Harness？

A: 在控制台的 ACP 配置页面点击"添加 Harness"，填写标识名、启动命令、参数和环境变量即可。

### Q: ACP 会话保存在哪里？

A: 默认保存在 `~/.copaw/acp_sessions` 目录下，可以在配置中修改 `save_dir` 来更改保存位置。

### Q: 为什么需要用户批准？

A: 当 `require_approval` 设置为 `true` 时，ACP 在执行可能修改文件或执行命令的操作前会请求用户确认，增加安全性。
