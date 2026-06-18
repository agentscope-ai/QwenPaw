# OpenSandbox Plugin 设计文档

## 业务场景

OpenSandbox 用于把高风险、环境敏感或依赖不确定的研发作业放到隔离的 Linux sandbox 中执行。它不是 Windows 宿主命令执行工具，不用于 PowerShell、CMD、`.bat`、`.ps1`、Windows PATH、Windows 进程或 GUI 检查。

| QwenPaw 作业场景 | 典型触发 | 沙箱内动作 | 主要收益 | 当前状态 |
| --- | --- | --- | --- | --- |
| 不可信脚本首次运行 | 社区脚本、供应商脚本、Agent 生成脚本、日志清理脚本 | 写入 `/workspace` 后执行最小命令，观察 stdout/stderr/exit code | 避免脚本首次运行直接触碰宿主文件、凭证和网络会话 | 适合 |
| Linux 环境与依赖验证 | `/etc/os-release`、shell 兼容性、`pip install`、构建工具探测 | 创建 Linux sandbox，安装或检查依赖，返回诊断 | 避免污染 Windows 或本地 Python 环境 | 适合 |
| 危险命令预演 | 删除、迁移、批量重命名、压缩解压、日志轮转 | 复制小型样本，在 sandbox 路径执行 | 将破坏面限制在临时文件系统 | 适合 |
| 临时 Web/API 预览 | FastAPI、文档站、Notebook、可视化服务 | 启动服务，使用 `sandbox_get_endpoint` 获取 URL | 不把本机端口、cookie 和内网凭证暴露给未知代码 | 部分适合 |
| 小型夹具测试 | 单文件脚本、小 fixture、配置片段 | 用 `file_write` 复制必要文本，运行测试命令 | 避免整仓、`.env`、`.git` 和依赖缓存进入沙箱 | 适合 |
| 大型项目 build/test | 整仓、`node_modules`、`.venv`、二进制数据 | 需要 host sync / artifact bridge | 需要上传审批、过滤和产物回传 | 待支持 |

默认优先使用 OpenSandbox 的情况：

- 用户明确提到 sandbox、沙箱、隔离执行、危险命令或不可信代码。
- 脚本会删除、迁移、批量重写、清理日志、解压归档或安装依赖。
- 用户要验证 Linux 环境、shell 兼容性、包管理器或构建工具。
- 需要启动临时 Web/API/Notebook/文档服务，且不希望暴露宿主机服务。

默认不使用 OpenSandbox 的情况：

- 任务需要直接访问宿主项目目录、Windows 路径、本地 `.venv`、`.git`、构建缓存或浏览器会话。
- 用户要查看 Windows 本机版本、PATH、进程、PowerShell/CMD 行为或 GUI。
- 输入是整仓、大型二进制、`node_modules`、私钥、`.env` 或大量日志。
- 需要把产物直接保存回宿主文件系统。

## 架构技术设计

### 总体链路

```text
QwenPaw Agent
  -> opensandbox skill
  -> opensandbox MCP client
  -> opensandbox-plugin / opensandbox_mcp_launcher.py
  -> official opensandbox_mcp server in stdio process
  -> opensandbox-server
  -> Docker / Kubernetes / WSL2+k3s runtime
  -> sandbox workload + execd data-plane
```

### 核心组件职责

| 组件 | 职责 |
| --- | --- |
| `opensandbox` skill | 定义触发场景、使用边界、默认 workflow 和安全注意事项 |
| `OpenSandbox MCP` client | 以 stdio 方式接入插件托管的 MCP launcher，默认 disabled |
| `opensandbox_mcp_launcher.py` | 启动官方 `opensandbox_mcp.server.create_server()`，补充 server proxy 与 image guard |
| official `opensandbox-mcp` | 暴露 sandbox 生命周期、命令、文件、endpoint、metrics 等 MCP tools |
| `opensandbox-server` | 管理 sandbox control plane，连接 Docker/Kubernetes 等 runtime |
| workload sandbox + execd | 在隔离 Linux 环境中执行命令、读写文件、暴露 endpoint |

插件加载时负责：

- 同步 `skills/opensandbox/SKILL.md` 到 skill pool 和已有 Agent workspace，默认 disabled。
- 给已有 Agent 注入 disabled 的 `OpenSandbox MCP` client。
- 刷新由插件托管的 MCP client 本地启动字段，包括 `command`、`args[0]` 和 `cwd`。

### MCP Client 配置

插件默认注入的 MCP client：

```text
key: opensandbox
name: OpenSandbox MCP
transport: stdio
enabled: false
command: 自动计算为当前 QwenPaw Python 解释器
args: [
  "<plugin_dir>/opensandbox_mcp_launcher.py",
  "--domain",
  "127.0.0.1:8080",
  "--protocol",
  "http",
  "--use-server-proxy",
  "--audit-enabled",
  "--security-center-url",
  "http://127.0.0.1:8091",
  "--audit-agent-id",
  "<agent-id>",
  "--audit-timeout-seconds",
  "2",
  "--sandbox-default-timeout-seconds",
  "300",
  "--sandbox-idle-timeout-seconds",
  "30"
]
cwd: 自动计算为插件安装目录
env:
  OPEN_SANDBOX_API_KEY=
```

`command`、`args[0]`、`cwd` 和 `--audit-agent-id` 是插件维护的本地启动字段。插件会根据当前 Python 解释器、插件安装目录和 Agent 配置刷新它们，同时保留用户修改过的 domain、protocol、API key、server proxy、Security Center URL、审计开关和审计超时配置。除 `OPEN_SANDBOX_API_KEY` 外，插件默认把连接配置放在 `args` 中，避免被 MCP 配置 API 匿名化显示。

用户不应把 `<auto: current QwenPaw Python>`、`<auto: plugin_dir>` 或 `<plugin_dir>` 当作字面量写入配置。手动排障恢复时必须填真实路径；正常情况下由插件自动生成。

### Launcher 设计

`opensandbox_mcp_launcher.py` 的职责：

- 构造 `ConnectionConfig(api_key, domain, protocol, request_timeout, use_server_proxy)`。
- 支持 `OPEN_SANDBOX_USE_SERVER_PROXY`、`--use-server-proxy` 和 `--no-use-server-proxy`。
- 在 `Sandbox.create` 前检查 `sandbox_create.image`。
- 给 `sandbox_create.image` schema 标注推荐默认值 `docker.io/library/python:3.10-alpine` 和兼容镜像 enum。
- 在 FastMCP `_tool_manager.call_tool` 边界记录全部官方 OpenSandbox 工具调用。
- 对参数进行工具级脱敏和限长后，使用 `requests` 上报到 Security Center。
- 调用 `opensandbox_mcp.server.create_server()` 并以 stdio 运行。

### MCP 调用审计

```text
OpenSandbox MCP call
  -> FastMCP tool manager audit wrapper
  -> official OpenSandbox tool
  -> sanitized Security Event
  -> requests.post
  -> http://127.0.0.1:8091/security-center/v1/events
```

OpenSandbox 审计使用独立的 `opensandbox/opensandbox/1.0` Security Event 契约。列表字段直接展示工具名、执行结果、Agent ID 和 sandbox ID，完整脱敏参数摘要可在 Security Event 详情中查看。

没有异常的成功调用统一使用 `DEBUG`，表示普通审计历史而非安全风险。工具异常以及 `command_run` 非零退出使用 `HIGH`。事件参数摘要不包含完整文件内容、环境变量值、stdout、stderr 或完整工具返回值；敏感字段统一脱敏。

审计上报通过 `asyncio.to_thread` 执行同步 `requests.post`。当前版本没有 outbox、重试和重复补报处理。HTTP 上报异常只记录到 stderr，不改变官方 OpenSandbox 工具的成功结果或原始异常。

### MCP Tools

当前工具来自 OpenSandbox MCP server：

- Sandbox 生命周期：`sandbox_create`、`sandbox_connect`、`sandbox_get_info`、`sandbox_list`、`sandbox_renew`、`sandbox_healthcheck`、`sandbox_get_metrics`、`sandbox_get_endpoint`、`sandbox_kill`。
- 命令执行：`command_run`、`command_interrupt`。
- 文件系统：`file_write`、`file_read`、`file_search`、`file_replace_contents`、`file_move`、`file_delete`、`file_create_directories`、`file_delete_directories`。

所有工具都围绕 `sandbox_id` 工作。Agent 应先 `sandbox_create` 或 `sandbox_connect`，再执行命令、读写文件、获取 endpoint 或清理 sandbox。

### Runtime 配置边界

MCP client 只配置如何连接 `opensandbox-server`。sandbox runtime 配置位于 `opensandbox-server` 的 `.sandbox.toml`。

Docker runtime 示例：

```toml
[runtime]
type = "docker"
execd_image = "docker.io/opensandbox/execd:v1.0.16"
```

Kubernetes / WSL2+k3s runtime 示例：

```toml
[runtime]
type = "kubernetes"
execd_image = "docker.io/opensandbox/execd:v1.0.16"
```

两个配置字段语义必须分开：

- `execd_image = "docker.io/opensandbox/execd:v1.0.16"`：OpenSandbox server 注入 sandbox 的 data-plane 镜像，负责 command/file/endpoint 等操作。
- `sandbox_create.image = "docker.io/library/python:3.10-alpine"`：Agent 创建 workload sandbox 时使用的推荐运行环境镜像；未显式传入 `image` 时，插件 launcher 会默认注入该镜像。为兼容上一版配置，仍允许显式传入 `docker.io/library/python:3.10-slim` 和 `docker.io/opensandbox/execd:v1.0.16`。

当前插件对 `sandbox_create.image` 做白名单硬拦截，并在未传入 `image` 时默认使用：

```text
docker.io/library/python:3.10-alpine
```

兼容允许显式传入：

```text
docker.io/library/python:3.10-slim
docker.io/opensandbox/execd:v1.0.16
```

白名单错误文案：

```text
not support image, pls use "docker.io/library/python:3.10-alpine" instead.
```

### Agent 工作流

默认工具链：

```text
sandbox_create
file_create_directories / file_write
command_run
sandbox_get_endpoint 或 file_read
sandbox_kill
```

默认 workload profile：

```text
image: docker.io/library/python:3.10-alpine
env: {}
resource: {"cpu": "500m", "memory": "512Mi"}
timeout_seconds: 300
ready_timeout_seconds: 120
```

### 安全与能力边界

- OpenSandbox 是运行时隔离层，前置工具策略、文件访问和用户审批仍由 QwenPaw/QwenClaw 提供。
- 插件侧负责 MCP client 注入、server proxy、workload image 白名单和 skill 边界。
- sandbox 内 `/workspace` 不等同于宿主项目目录。
- 小型文本可以经 `file_write` 重建；目录同步、二进制传输和产物回传需要 host sync / artifact bridge。
- `sandbox_id` 需要 Agent 在本次作业中显式保存和复用。
- E2B/BYOC 是未来 provider 方向，不是当前插件能力。
