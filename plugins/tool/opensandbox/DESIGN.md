# OpenSandbox Plugin 设计文档

本文档说明 OpenSandbox 接入 QwenPaw 的零核心改动插件 MVP，以及后续可选的少量核心改动方案。当前目录已经包含可加载的 MVP 插件：先提供 `execute_opensandbox_command`，后续可以在同一个 `opensandbox` 插件内继续增加文件同步、沙箱状态检查、session 管理、产物下载等能力。

插件还附带 `opensandbox` skill，用来告诉 Agent 何时使用 OpenSandbox 工具。插件加载时会把该 skill 放入共享 skill pool，并同步到已有 Agent workspace，默认 disabled，由用户按需启用。

## 目标

- 让 Agent 可以在 OpenSandbox 沙箱中执行 shell 命令。
- 尽量减少 QwenPaw 核心代码改动。
- 不把 `opensandbox` SDK 作为所有用户的必选主依赖。
- 保留本地 `execute_shell_command` 的默认行为，除非用户明确启用沙箱。
- 支持 Windows 本地使用 OpenSandbox server 加 Docker/Podman 后端。

## 非目标

- MVP 不做完整项目目录双向同步。
- MVP 不保证多条命令复用同一个沙箱。
- MVP 不实现 Docker/Podman/OpenSandbox server 的自动安装。
- MVP 不默认替换所有 Agent 的 shell 工具。

## 三个方案对比

| 方案 | 改动范围 | 能否保持 `execute_shell_command` 名称 | 依赖影响 | 优点 | 缺点 |
| --- | --- | --- | --- | --- | --- |
| 当前核心 backend 方案 | 修改 `pyproject.toml`、config、context、`react_agent.py`、`shell.py` | 可以 | `opensandbox` 进入主依赖 | 对模型最透明 | 侵入高，核心 shell 变复杂，配置热加载和 `cwd` 语义容易出问题 |
| 零核心改动插件方案 | 只新增插件 | 不可以，新增 `execute_opensandbox_command` | 只在插件安装时安装依赖 | 最安全、最容易回滚 | 需要禁用本地 shell；Coding Mode 文案仍会提到 `execute_shell_command` |
| 少量核心改动插件方案 | OpenSandbox 仍在插件内，核心只加通用扩展点 | 可以 | 只在插件安装时安装依赖 | 兼顾透明性和低侵入 | 需要设计一个通用工具覆盖或 shell backend 扩展点 |

推荐路线：

1. 先做零核心改动插件方案，验证真实使用体验。
2. 如果确认需要“所有 shell 都透明进入沙箱”，再做少量核心改动插件方案。
3. 不建议继续把 OpenSandbox SDK 和生命周期逻辑直接放进核心 `shell.py`。

## 方案一：零核心改动插件

### 插件形态

新增一个 tool 插件：

```text
plugins/tool/opensandbox/
  plugin.json
  requirements.txt
  plugin.py
  skills/
    opensandbox/
      SKILL.md
  tools/
    shell.py
  README.md
```

### 打包 zip 插件

发布给普通用户时，建议打包为 zip 插件。zip 根目录应直接包含 `plugin.json`，不要再套一层 `opensandbox/` 目录，否则插件安装器可能无法在解压后的根目录找到 manifest。

推荐 zip 内容：

```text
plugin.json
requirements.txt
plugin.py
README.md
DESIGN.md
skills/
  opensandbox/
    SKILL.md
tools/
  __init__.py
  shell.py
```

不应包含：

- `__pycache__/`
- `*.pyc`
- `.git/`
- 本地日志、临时文件、虚拟环境目录

在插件目录内执行打包：

```powershell
cd plugins/tool/opensandbox
Compress-Archive `
  -Path plugin.json,requirements.txt,plugin.py,README.md,DESIGN.md,skills,tools `
  -DestinationPath ..\opensandbox-plugin.zip `
  -Force
```

打包后可以检查 zip 根目录：

```powershell
Expand-Archive ..\opensandbox-plugin.zip -DestinationPath $env:TEMP\opensandbox-plugin-check -Force
Get-ChildItem $env:TEMP\opensandbox-plugin-check
```

确认 `plugin.json` 位于解压目录根部即可。

MVP 先注册一个 shell 工具：

```text
execute_opensandbox_command
```

后续可以在同一个 `opensandbox` 插件内继续增加文件同步、沙箱状态检查、session 管理、产物下载等工具。用户在工具设置里启用 `execute_opensandbox_command`，并禁用原来的 `execute_shell_command`。这样 Agent 的可用 shell 工具只剩沙箱工具，普通聊天场景下即可达到“命令进沙箱”的目标。

插件同时提供 `opensandbox` skill，给 Agent 注入决策规则：

- 何时应该用 OpenSandbox：不可信命令、Linux 环境探测、依赖安装实验、一次性 CLI 验证。
- 何时不应该用 OpenSandbox：需要访问宿主项目文件、Windows 路径、本地凭证、GUI、浏览器会话、需要跨命令保留状态。
- 如何说明 MVP 限制：当前没有宿主目录自动同步或挂载。

### 插件 manifest 关键字段

完整配置以 [plugin.json](./plugin.json) 为准，关键结构如下：

```json
{
  "id": "opensandbox",
  "name": "OpenSandbox",
  "version": "0.1.0",
  "type": "tool",
  "description": "Run agent workloads inside OpenSandbox sandboxes",
  "author": "QwenPaw Team",
  "entry": {
    "backend": "plugin.py"
  },
  "dependencies": ["opensandbox>=0.1.9"],
  "min_version": "1.1.6",
  "meta": {
    "tools": [
      {
        "name": "execute_opensandbox_command",
        "description": "Execute shell commands inside an OpenSandbox sandbox",
        "icon": "terminal",
        "requires_config": true,
        "config_fields": [
          {
            "name": "domain",
            "label": "OpenSandbox Domain",
            "type": "text",
            "required": true,
            "default": "127.0.0.1:8080"
          },
          {
            "name": "protocol",
            "label": "Protocol",
            "type": "select",
            "required": false,
            "default": "http",
            "options": ["http", "https"]
          },
          {
            "name": "api_key_env",
            "label": "API Key Environment Variable",
            "type": "text",
            "required": false,
            "default": "OPEN_SANDBOX_API_KEY"
          },
          {
            "name": "api_key",
            "label": "API Key",
            "type": "password",
            "required": false
          },
          {
            "name": "image",
            "label": "Sandbox Image",
            "type": "text",
            "required": false,
            "default": "opensandbox/code-interpreter:v1.0.2"
          },
          {
            "name": "entrypoint_json",
            "label": "Entrypoint JSON",
            "type": "textarea",
            "required": false,
            "default": "[\"/opt/opensandbox/code-interpreter.sh\"]"
          },
          {
            "name": "env_json",
            "label": "Environment JSON",
            "type": "textarea",
            "required": false,
            "default": "{\"PYTHON_VERSION\":\"3.11\"}"
          },
          {
            "name": "resource_json",
            "label": "Resource JSON",
            "type": "textarea",
            "required": false,
            "default": "{\"cpu\":\"500m\",\"memory\":\"512Mi\"}"
          },
          {
            "name": "use_server_proxy",
            "label": "Use Server Proxy",
            "type": "boolean",
            "required": false,
            "default": false
          },
          {
            "name": "ready_timeout_seconds",
            "label": "Ready Timeout Seconds",
            "type": "number",
            "required": false,
            "default": 120,
            "min": 1,
            "max": 600
          },
          {
            "name": "sandbox_timeout_seconds",
            "label": "Sandbox Timeout Seconds",
            "type": "number",
            "required": false,
            "default": 300,
            "min": 60,
            "max": 86400
          },
          {
            "name": "command_working_directory",
            "label": "Command Working Directory",
            "type": "text",
            "required": false,
            "default": "/workspace"
          }
        ]
      }
    ]
  }
}
```

`requirements.txt`：

```text
opensandbox>=0.1.9
```

### 工具接口

建议工具函数签名：

```python
async def execute_opensandbox_command(
    command: str,
    cwd: str = "/workspace",
    timeout: float = 60.0,
) -> ToolResponse:
    ...
```

行为：

- 从 `qwenpaw.plugins.get_tool_config("execute_opensandbox_command")` 读取配置。
- 使用 `opensandbox.config.ConnectionConfig` 连接本地 OpenSandbox server。
- MVP 每次工具调用创建一个 sandbox。
- 执行命令后返回 stdout、stderr、exit code。
- finally 中调用 `sandbox.kill()` 和 `sandbox.close()`。
- 响应文本中显式带上 `sandbox_id`，便于用户确认不是本地 Windows 执行。

### 用户操作流程

1. 安装插件。
2. 打开工具设置，配置 `execute_opensandbox_command`。
3. 启用 `execute_opensandbox_command`。
4. 禁用 `execute_shell_command`。
5. 要求 Agent 执行：

```text
执行一条 shell 命令，查看操作系统版本。
```

预期返回 Linux 容器环境，而不是 Windows。

### 零核心方案优点

- 不改 QwenPaw 核心代码。
- 不把 `opensandbox` 放进主项目依赖。
- 插件卸载后不会影响本地 shell。
- 配置 UI、密码 mask、插件依赖安装都可以复用现有机制。
- 适合先做 MVP 和用户验证。

### 零核心方案限制

- 工具名不是 `execute_shell_command`，模型需要选择 `execute_opensandbox_command`。
- 如果 Coding Mode 的系统提示仍硬编码 `execute_shell_command`，模型可能被提示词误导。
- 禁用本地 shell 后，部分旧提示或旧工作流可能需要调整。
- 每条命令新建沙箱，性能和状态连续性一般。
- 沙箱内 `/workspace` 不等同于宿主项目目录，MVP 需要明确告诉用户。

### 零核心方案适合的 MVP 验收标准

- 插件安装后，工具列表出现 `execute_opensandbox_command`。
- 用户能在 UI 中配置 domain、api_key、image、timeout。
- 启用沙箱工具并禁用本地 shell 后，Agent 可以执行简单命令。
- `uname -a` 或 `cat /etc/os-release` 返回 Linux 容器信息。
- 命令失败时能返回 stderr 和 exit code。
- OpenSandbox server 未启动或 API key 错误时，错误信息可读。

## 方案二：少量核心改动插件

这个方案仍然把 OpenSandbox 实现放在插件里，核心只新增通用扩展点，不出现 OpenSandbox 专用类、专用配置或 SDK import。

目标是让用户继续使用 `execute_shell_command`，但实际执行由插件接管。

### 推荐扩展点：工具覆盖机制

核心新增一个通用机制：

```python
api.register_tool_override(
    target_tool_name="execute_shell_command",
    tool_func=execute_opensandbox_command,
    plugin_id="opensandbox",
)
```

或者在现有 `register_tool` 上加参数：

```python
api.register_tool(
    tool_name="execute_shell_command",
    tool_func=execute_opensandbox_command,
    description="Execute shell commands inside OpenSandbox",
    enabled=False,
    override_existing=True,
)
```

核心改动只涉及插件系统和工具注册：

- `src/qwenpaw/plugins/api.py`
  - 增加 `register_tool_override()` 或 `override_existing` 参数。
- `src/qwenpaw/plugins/registry.py`
  - 保存 override 关系和对应 callable。
- `src/qwenpaw/agents/react_agent.py`
  - `_create_toolkit()` 构造 `tool_functions` 后，应用显式启用的 override。
- 可选：`src/qwenpaw/app/routers/tools.py`
  - 在工具详情中显示当前工具由哪个插件接管。

不需要改：

- `src/qwenpaw/agents/tools/shell.py`
- `src/qwenpaw/config/config.py` 的 OpenSandbox 专用模型
- `src/qwenpaw/config/context.py` 的 OpenSandbox 专用 context
- 主 `pyproject.toml` 的 `opensandbox` 依赖

### 显式启用规则

为了安全，override 必须是显式 opt-in：

- 安装插件不会自动替换 shell。
- 用户进入工具设置，选择启用 OpenSandbox override。
- 或插件写入一个独立配置项：

```json
{
  "tools": {
    "builtin_tools": {
      "execute_shell_command": {
        "enabled": true,
        "config": {
          "provider": "plugin:opensandbox"
        }
      }
    }
  }
}
```

核心在 `_create_toolkit()` 中看到 `provider=plugin:opensandbox` 后，才将 `execute_shell_command` 映射到插件函数。

### 少量核心方案优点

- 用户和模型仍然只看到 `execute_shell_command`。
- OpenSandbox 代码仍在插件内，核心不依赖 OpenSandbox SDK。
- 后续 E2B、microsandbox、Podman sandbox 都能复用同一扩展点。
- 卸载插件后可以恢复本地 shell。
- 比当前核心 backend 方案更容易维护和测试。

### 少量核心方案风险

- 工具覆盖属于高权限能力，必须有清晰 UI 和日志。
- 如果插件 bug 导致 shell 工具不可用，需要能安全回退本地 shell。
- 需要定义多个插件同时覆盖同一工具时的冲突规则。
- 需要保证 Tool Guard、审批流、async execution 等行为仍然一致。

### 少量核心方案验收标准

- 不启用 override 时，`execute_shell_command` 仍执行本地命令。
- 启用 OpenSandbox override 后，同名工具进入沙箱。
- 工具列表能看出 `execute_shell_command` 当前由 OpenSandbox 插件接管。
- 插件禁用或卸载后，自动恢复本地实现。
- Tool Guard 对 `execute_shell_command` 的策略仍然生效。
- 插件依赖仍只来自插件 `requirements.txt`。

## 推荐实施顺序

### 第一步：整理当前实验代码

- 撤回主 `pyproject.toml` 中的 `opensandbox>=0.1.9`。
- 撤回主 `pyproject.toml` 中的阿里 uv 默认镜像源。
- 撤回核心 `OpenSandboxShellConfig`、context、`react_agent.py` 注入和 `shell.py` SDK 逻辑。
- 保留已经验证过的 OpenSandbox 执行逻辑，迁移到插件工具文件。

### 第二步：实现零核心插件 MVP

- 添加真实 `plugin.json`。
- 添加 `requirements.txt`。
- 添加 `plugin.py` 注册插件。
- 添加 `tools/shell.py` 实现 `execute_opensandbox_command`。
- 添加单元测试，mock OpenSandbox SDK。
- 手动验证 Windows 上连接 `127.0.0.1:8080` 的 OpenSandbox server。

### 第三步：使用体验评估

重点观察：

- Agent 是否稳定选择 `execute_opensandbox_command`。
- 禁用本地 `execute_shell_command` 后是否影响 Coding Mode。
- 用户是否能从工具输出判断命令运行在沙箱。
- 每条命令新建 sandbox 的性能是否可接受。

### 第四步：决定是否做少量核心扩展点

如果零核心方案体验足够好，就不做核心改动。

如果用户明确需要“所有 shell 命令透明进沙箱”，再实现工具 override 机制。该机制必须是通用能力，不能写成 OpenSandbox 专用能力。

## 后续可增强能力

- session 级 sandbox 复用，避免每条命令冷启动。
- 将宿主项目目录打包上传到 `/workspace`。
- 命令结束后下载指定产物。
- 在工具输出中显示 sandbox id、image、cwd、duration。
- 增加 `/api/opensandbox/status` 插件 HTTP route，检查 server、镜像和 API key。
- 支持 E2B、Podman、WSLv2 backend 复用同一插件接口。

## 当前建议

先做零核心改动插件 MVP。

理由：

- 它能最快验证真实 Agent 体验。
- 它不会继续扩大核心 `shell.py` 的复杂度。
- 它不会把 OpenSandbox 依赖强加给所有 QwenPaw 用户。
- 它失败时很好回滚，删除插件即可。

如果零核心 MVP 证明“模型经常错用本地 shell”或“用户强烈需要同名透明替换”，再进入少量核心改动方案。
