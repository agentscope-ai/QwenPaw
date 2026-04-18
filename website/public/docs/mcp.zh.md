# MCP 与内置工具

QwenPaw 通过 **MCP（模型上下文协议）** 连接外部服务，并提供一组 **内置工具**，让智能体能够访问文件系统、执行命令、浏览网页等。

---

## 概念说明

QwenPaw 为智能体提供两类工具：

1. **内置工具**：开箱即用，由 QwenPaw 核心提供，如文件操作、命令执行、浏览器自动化等

   - 在"智能体 → 工具"页面管理
   - 可以单独启用/禁用

2. **MCP 工具**：通过 MCP 协议连接外部服务，扩展更多能力
   - 在"智能体 → MCP"页面配置客户端
   - MCP 客户端会向智能体注册新的工具

两者可以同时使用，互不冲突。

---

## MCP

**MCP（模型上下文协议，Model Context Protocol）** 允许 QwenPaw 连接到外部 MCP 服务器，扩展智能体访问文件系统、数据库、API 等外部资源的能力。

### 前置要求

使用本地 MCP 服务器需要：

- **Node.js** 18+ （[下载](https://nodejs.org/)）

```bash
node --version  # 检查版本
```

> 远程 MCP 服务器无需本地依赖。

---

### 添加 MCP 客户端

1. 打开控制台，进入 **智能体 → MCP**
2. 点击 **+ 创建** 按钮
3. 粘贴 MCP 客户端的 JSON 配置
4. 点击 **创建** 完成导入

![MCP](https://img.alicdn.com/imgextra/i1/O1CN01HrYuzS24mpUDOgB6m_!!6000000007434-2-tps-3822-2070.png)

---

### 配置格式

QwenPaw 支持三种 JSON 格式，选择其一即可：

#### 格式 1：标准 mcpServers 格式（**推荐**）

```json
{
  "mcpServers": {
    "filesystem": {
      "command": "npx",
      "args": [
        "-y",
        "@modelcontextprotocol/server-filesystem",
        "/path/to/folder"
      ],
      "env": {
        "API_KEY": "your-api-key"
      }
    }
  }
}
```

#### 格式 2：直接键值对格式

省略 `mcpServers` 包装：

```json
{
  "filesystem": {
    "command": "npx",
    "args": ["-y", "@modelcontextprotocol/server-filesystem", "/path/to/folder"]
  }
}
```

#### 格式 3：单个客户端格式

```json
{
  "key": "filesystem",
  "name": "文件系统访问",
  "command": "npx",
  "args": ["-y", "@modelcontextprotocol/server-filesystem", "/path/to/folder"]
}
```

> 支持一次导入多个客户端。

---

### 配置示例

#### 文件系统访问

```json
{
  "mcpServers": {
    "filesystem": {
      "command": "npx",
      "args": [
        "-y",
        "@modelcontextprotocol/server-filesystem",
        "/Users/username/Documents"
      ]
    }
  }
}
```

#### 网络搜索（Tavily）

Tavily 是一个专为 AI 优化的网络搜索服务，可让智能体进行实时网页搜索。

```json
{
  "mcpServers": {
    "tavily": {
      "command": "npx",
      "args": ["-y", "tavily-mcp@latest"],
      "env": {
        "TAVILY_API_KEY": "tvly-xxxxxxxxxxxxx"
      }
    }
  }
}
```

> **内置支持**：系统启动时会自动创建名为 `tavily_search` 的客户端。如果环境变量中已设置 `TAVILY_API_KEY`，该客户端会自动启用。你也可以直接修改tavily mcp的配置。

#### 远程 MCP 服务

```json
{
  "mcpServers": {
    "remote-api": {
      "transport": "streamable_http",
      "url": "https://api.example.com/mcp",
      "headers": {
        "Authorization": "Bearer your-token"
      }
    }
  }
}
```

---

### 高级选项

#### 传输类型

MCP 支持三种传输协议，通常自动识别：

- **stdio** — 本地命令行工具，需要 `command` 字段
- **streamable_http** — 远程 HTTP 服务，需要 `url` 字段
- **sse** — Server-Sent Events，需要 `url` 和 `transport: "sse"`

#### 配置项说明

- `command` — 启动命令（stdio 必填）
- `args` — 命令参数
- `env` — 环境变量（如 API 密钥）
- `cwd` — 工作目录
- `url` — 远程服务地址（HTTP/SSE 必填）
- `headers` — 请求头（用于认证）
- `transport` — 传输类型（通常可自动识别）

#### 配置验证规则

- **stdio 传输**：`command` 字段为必填项，不能为空
- **streamable_http / sse 传输**：`url` 字段为必填项，不能为空
- 如果配置不符合要求，创建客户端时会返回错误

---

### 配置字段说明

无论使用哪种格式，每个 MCP 客户端都支持以下字段：

| 字段          | 类型     | 默认值    | 说明                                                               |
| ------------- | -------- | --------- | ------------------------------------------------------------------ |
| `name`        | string   | -         | 客户端名称（必填）                                                 |
| `description` | string   | `""`      | 客户端描述                                                         |
| `enabled`     | bool     | `true`    | 是否启用该客户端                                                   |
| `transport`   | string   | `"stdio"` | 传输方式：`"stdio"`（标准输入输出）/ `"streamable_http"` / `"sse"` |
| `url`         | string   | `""`      | 远程 MCP 服务器地址（用于 HTTP/SSE 传输）                          |
| `headers`     | object   | `{}`      | HTTP 请求头（用于 HTTP/SSE 传输）                                  |
| `command`     | string   | `""`      | 启动命令（用于 stdio 传输，如 `"npx"`、`"python"`）                |
| `args`        | string[] | `[]`      | 命令参数（用于 stdio 传输）                                        |
| `env`         | object   | `{}`      | 客户端运行时环境变量                                               |
| `cwd`         | string   | `""`      | 工作目录（用于 stdio 传输）                                        |

> **提示：** `transport` 通常会根据配置自动识别（有 `command` → stdio，有 `url` → http/sse），无需手动指定。

---

## 内置工具

QwenPaw 提供了一组开箱即用的内置工具，智能体可以直接调用这些工具完成各种任务。

---

### 工具管理

![tool](https://img.alicdn.com/imgextra/i1/O1CN018oZy751gxmArrsFbC_!!6000000004209-2-tps-3822-2070.png)

#### 启用和禁用工具

1. 打开控制台，进入 **智能体 → 工具**
2. 查看所有内置工具及其状态（每个工具显示为独立卡片）
3. 使用卡片右下角的开关按钮单独启用或禁用工具
4. 使用页面顶部的**全部启用**或**全部禁用**按钮进行批量操作

**启用工具的影响：**

- **已启用**：工具会加载到智能体上下文中，智能体可以在对话中调用
- **已禁用**：工具不会出现在智能体的可用工具列表中，无法被调用

> 建议只启用实际需要的工具，以减少上下文占用，加快响应速度。配置变更自动热加载，无需重启服务。

> **多智能体支持**：每个智能体都有独立的工具配置。在控制台顶部的智能体切换器中切换智能体后，看到的是该智能体的专属工具配置。详见[多智能体](./multi-agent)。

---

### 内置工具列表

| 类型         | 工具名称                  | 功能说明                                            |
| ------------ | ------------------------- | --------------------------------------------------- |
| 文件操作     | `read_file`               | 读取文件内容，支持按行范围读取                      |
| 文件操作     | `write_file`              | 创建或覆盖文件                                      |
| 文件操作     | `edit_file`               | 使用查找替换修改文件内容（替换所有匹配项）          |
| 文件操作     | `append_file`             | 追加内容到文件末尾                                  |
| 文件搜索     | `grep_search`             | 按内容搜索文件，支持正则表达式和上下文              |
| 文件搜索     | `glob_search`             | 按文件名模式查找文件                                |
| 命令执行     | `execute_shell_command`   | 执行 Shell 命令，支持异步执行                       |
| 智能体委托   | `delegate_external_agent` | 通过 ACP 将任务委托给外部智能体 runner              |
| 浏览器自动化 | `browser_use`             | 浏览器自动化，支持 30+ 种操作（导航、交互、截图等） |
| 截图         | `desktop_screenshot`      | 捕获桌面或窗口截图                                  |
| 图像分析     | `view_image`              | 加载图片到上下文供模型分析                          |
| 文件传输     | `send_file_to_user`       | 发送文件给用户，自动识别文件类型                    |
| 记忆搜索     | `memory_search`           | 在 MEMORY.md 中语义搜索过往信息                     |
| 时间         | `get_current_time`        | 获取当前时间和时区                                  |
| 时间         | `set_user_timezone`       | 设置用户时区偏好                                    |
| 统计         | `get_token_usage`         | 查询 LLM Token 使用量统计                           |

### 工具详细说明

**文件操作**

- `read_file`：读取文件内容
  - 支持 `start_line` 和 `end_line` 参数读取指定行范围
  - 大文件会自动截断（默认 50KB），并提示使用 `start_line` 继续读取
  - 截断时会显示文件总行数和下一次读取的起始行号
- `edit_file`：全文查找替换所有匹配项，适合精确修改
- `append_file`：追加内容到文件末尾
  - 不会覆盖原有内容
  - 适合：追加日志、累积数据、添加记录
  - 如果文件不存在会自动创建

**文件搜索**

- `grep_search`：按内容搜索文件
  - `pattern`：搜索字符串或正则表达式
  - `path`：搜索路径（文件或目录），默认为工作目录
  - `is_regex`：是否将 pattern 视为正则表达式（默认 False）
  - `case_sensitive`：是否区分大小写（默认 True）
  - `context_lines`：显示匹配行前后的上下文行数（默认 0，最大 5）
  - `include_pattern`：按文件名筛选，如 "\*.py"
- `glob_search`：支持递归模式如 `**/*.json`

**命令执行**

- `execute_shell_command`：执行 Shell 命令
  - 跨平台支持（Windows 使用 cmd.exe，Linux/macOS 使用 bash）
  - `command`：要执行的命令
  - `timeout`：超时时间（秒），默认 60 秒
  - `cwd`：工作目录（可选，默认为工作目录）
  - 支持异步执行模式（见下方说明）

**智能体委托（ACP）**

**使用方式：**

- 使用前，请先准备好需要接入的外部智能体 runner，例如 `claude_code`、`codex`、`qwen_code`、`opencode`
- 确保对应 runner 已完成登录或 API Key 配置，并且可以在终端中正常启动和使用
- 在 **智能体 → 工具** 页面开启 `delegate_external_agent` 工具
- 在对话中直接提出需求，例如：
  - “请使用外部智能体 claude code 帮我分析一下工作目录的结构”
  - “请和外部智能体 claude code 对话，让它把自我介绍写入一个 md 文件中”
- QwenPaw 会在合适的时候调用 `delegate_external_agent`，与外部智能体建立连续对话，并将中间进度和结果回传到当前会话中
- 建立连接后，可以继续通过 `delegate_external_agent` 与该外部智能体多轮对话
- 当前每个 runner 在同一个聊天中只支持一个活动会话；如果要开启新对话，需先关闭当前会话

- `delegate_external_agent`：通过 ACP（Agent Client Protocol）与外部智能体 runner 建立会话，并将任务委托给外部智能体执行
  - 适用场景：把代码分析、文件编辑、命令执行等工作转交给外部 coding agent
  - 默认支持的 runner：`qwen_code`、`claude_code`、`codex`、`opencode`
  - 默认 **禁用**，需要在 **智能体 → 工具** 页面单独启用
  - `action`：支持 `start`、`message`、`respond`、`close`
    - `start`：启动一个新的外部智能体会话；当 `message` 为空时，会默认发送 `hi`
    - `message`：向当前聊天绑定的外部智能体会话继续发送消息
    - `respond`：响应外部智能体发起的权限请求；`message` 必须传入当前待处理权限请求中的**精确 option id**
    - `close`：关闭当前聊天绑定的外部智能体会话
  - `runner`：runner 名称，例如 `qwen_code`、`claude_code`、`codex`、`opencode`
  - `message`：发送给外部智能体的消息；在 `respond` 模式下用于传递选中的权限选项 id
  - `cwd`：外部智能体执行时使用的工作目录；默认使用当前工作区
  - 工具会以流式方式返回中间进度，包括文本输出、工具调用更新、权限请求以及最终结果

**权限与安全说明：**

- 当外部智能体请求权限时，当前会话会挂起，等待显式响应
- 对权限请求的响应是**严格匹配**的：只能从当前请求提供的选项中选择一个，并传入其精确 id
- 某些危险命令模式会被硬拦截
- 文件路径访问会尽可能限制在配置的工作目录内

**异步执行：**

`execute_shell_command` 工具支持异步执行模式：

- **同步执行（默认）**：智能体等待命令完成后继续
  - 适合：快速命令（ls、cat）、需要立即获取输出的命令
- **异步执行**：命令在后台运行，智能体立即继续处理
  - 适合：长时间运行的命令（编译、测试、下载）、不阻塞对话流程的任务

启用异步执行后，智能体会自动获得以下工具：

- `list_background_tasks` - 查看所有正在运行的任务及其状态
- `get_task_output` - 获取任务的输出结果（标准输出和标准错误）
- `cancel_task` - 取消正在运行的任务

在 `execute_shell_command` 工具卡片中可配置该选项（目前仅此工具支持异步执行）。

**浏览器自动化**

- `browser_use`：支持 30+ 种操作
  - **基础导航**：start, stop, open, navigate, navigate_back, close
  - **页面交互**：click, type, hover, drag, select_option
  - **页面分析**：snapshot, screenshot, console_messages, network_requests
  - **表单操作**：fill_form, file_upload, press_key
  - **JavaScript 执行**：eval, evaluate, run_code
  - **高级功能**：cookies_get, cookies_set, cookies_clear, tabs, wait_for, pdf, resize, handle_dialog, install, connect_cdp, list_cdp_targets, clear_browser_cache
- 使用 `action` 参数指定操作类型
- 默认为无头模式（headless），使用 `headed=True` 启动可见浏览器窗口
- 支持多标签页（使用不同的 `page_id`）

**CDP 模式（高级功能）：**
浏览器工具支持通过 Chrome DevTools Protocol (CDP) 连接到已运行的 Chrome 浏览器：

- **启动时暴露 CDP 端口**：使用 `action="start"` 并设置 `cdp_port`（如 9222），Chrome 会以 `--remote-debugging-port` 模式启动
- **连接到外部浏览器**：使用 `action="connect_cdp"` 和 `cdp_url`（如 `http://localhost:9222`）连接到已运行的 Chrome
- **发现 CDP 端点**：使用 `action="list_cdp_targets"` 扫描本地端口范围（默认 9000-10000），查找可用的 CDP 连接

**CDP 模式适用场景：**

- 连接到用户手动打开的 Chrome 浏览器（保持登录状态、书签、插件等）
- 与外部调试工具配合使用
- 在已有浏览器会话中执行自动化操作

**截图和图像**

- `desktop_screenshot`：捕获桌面或窗口截图
  - `path`：保存路径（可选，默认保存到工作目录）
  - `capture_window`：仅 macOS 支持，为 True 时可点击选择窗口截图
- `view_image`：加载图片后，模型可进行视觉分析
  - **注意**：该工具的输出不会显示在用户界面中，它只将图片加载到模型的上下文中

**记忆搜索**

- `memory_search`：语义搜索记忆文件，找到相关的过往对话和决策
  - **前置要求**：
    - 在**智能体 → 运行配置**中启用"记忆管理"功能
    - 如果未配置，工具调用会返回错误提示
  - `query`：语义搜索查询
  - `max_results`：最多返回结果数（默认 5）
  - `min_score`：最低相似度阈值（默认 0.1）
  - 搜索范围：当前智能体工作区根目录下的 MEMORY.md 和 memory/\*.md 文件

**时间工具**

- `get_current_time`：获取当前时间，格式为 `YYYY-MM-DD HH:MM:SS 时区 (星期)`
- `set_user_timezone`：设置用户时区偏好
  - `timezone_name`：IANA 时区名称，如 "Asia/Shanghai"、"America/New_York"、"UTC"

**统计工具**

- `get_token_usage`：查询 LLM Token 使用量统计
  - `days`：查询过去 N 天（默认 30）
  - `model_name`：按模型名称筛选（可选）
  - `provider_id`：按提供商筛选（可选）

---

### 工具配置参考

内置工具的配置存储在 `agent.json` 的 `tools.builtins` 字段中。

**配置示例：**

```json
{
  "tools": {
    "builtin_tools": {
      "execute_shell_command": {
        "name": "execute_shell_command",
        "enabled": true,
        "display_to_user": true,
        "async_execution": false
      },
      "read_file": {
        "name": "read_file",
        "enabled": true,
        "display_to_user": true,
        "async_execution": false
      }
    }
  }
}
```

**每个工具的配置字段：**

| 字段              | 类型   | 默认值  | 说明                                                                                                                              |
| ----------------- | ------ | ------- | --------------------------------------------------------------------------------------------------------------------------------- |
| `name`            | string | -       | 工具函数名                                                                                                                        |
| `enabled`         | bool   | `true`  | 是否启用该工具                                                                                                                    |
| `display_to_user` | bool   | `true`  | 工具输出是否显示给用户。设为 `false` 时，工具的输出仅供智能体内部使用，不会在频道消息中展示（如 `view_image` 工具默认为 `false`） |
| `async_execution` | bool   | `false` | 是否异步执行该工具（目前仅 `execute_shell_command` 支持）                                                                         |

> **提示：** 通常通过控制台（智能体 → 工具）管理工具配置，无需手动编辑 `agent.json`。
