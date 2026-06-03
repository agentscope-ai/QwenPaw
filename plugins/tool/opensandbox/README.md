# OpenSandbox 插件

OpenSandbox 插件让 QwenPaw Agent 可以在 OpenSandbox 沙箱中执行命令。当前 MVP 提供一个工具：

```text
execute_opensandbox_command
```

这个插件采用零核心改动方案：OpenSandbox SDK 依赖写在插件自己的 `requirements.txt` 中，不放进 QwenPaw 主项目的 `pyproject.toml`。

## 前置条件

本插件只负责把 QwenPaw 的工具调用转发到 OpenSandbox。OpenSandbox server、容器运行时和镜像需要先在本机准备好。

官方文档：

- OpenSandbox GitHub: https://github.com/alibaba/OpenSandbox
- OpenSandbox 文档: https://open-sandbox.ai/
- OpenSandbox 中文文档: https://open-sandbox.ai/zh/
- OpenSandbox server README: https://github.com/alibaba/OpenSandbox/blob/main/server/README.md
- Docker Desktop Windows 安装文档: https://docs.docker.com/desktop/setup/install/windows-install/
- uv 安装文档: https://docs.astral.sh/uv/getting-started/installation/

### 1. 安装容器运行时

OpenSandbox 本地 Docker runtime 需要可用的 Docker 环境。Windows 推荐使用 Docker Desktop，并启用 WSL2 backend。

Docker Desktop 安装后，在 PowerShell 验证：

```powershell
docker version
docker run --rm hello-world
```

如果你使用 Podman Desktop，需要确保 OpenSandbox server 所在进程可以通过 Docker-compatible API 访问 Podman，例如正确配置 `DOCKER_HOST`。当前 README 的默认路径按 Docker Desktop 编写，Podman 属于可选替代方案。

### 2. 安装 uv

OpenSandbox 官方示例使用 `uvx opensandbox-server` 启动 server。Windows 可用下面任一方式安装 `uv`：

```powershell
winget install --id=astral-sh.uv -e
```

或使用官方安装脚本：

```powershell
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

验证：

```powershell
uv --version
uvx --version
```

### 3. 确认 opensandbox-server 可用

使用 `uvx` 时不需要提前把 `opensandbox-server` 安装到 QwenPaw 环境里，`uvx` 会按需下载并运行：

```powershell
uvx opensandbox-server --help
```

如果你希望把 server 安装到当前 Python 环境，也可以执行：

```powershell
uv pip install opensandbox-server
opensandbox-server --help
```

注意：`opensandbox-server` 是本地沙箱控制面服务；本插件里的 `opensandbox>=0.1.9` 是 QwenPaw 调用 server 的 Python SDK，两者都需要，但安装位置可以不同。

### 4. 初始化 OpenSandbox server 配置

生成 Docker runtime 示例配置：

```powershell
uvx opensandbox-server init-config "$env:USERPROFILE\.sandbox.toml" --example docker
```

编辑 `C:\Users\<你的用户名>\.sandbox.toml`，至少确认这些字段：

```toml
[server]
host = "127.0.0.1"
port = 8080
max_sandbox_timeout_seconds = 86400
api_key = "your-api-key"
```

本地开发建议设置非空 `api_key`。后续 QwenPaw 插件配置里的 `api_key` 或 `OPEN_SANDBOX_API_KEY` 必须和这里一致。

### 5. 启动 OpenSandbox server

在单独的 PowerShell 窗口启动：

```powershell
uvx opensandbox-server
```

正常启动后应看到类似：

```text
Uvicorn running on http://127.0.0.1:8080
```

健康检查：

```powershell
curl.exe http://127.0.0.1:8080/health
```

如果配置了 `api_key`，根路径 `/` 返回 `401` 是正常的，说明鉴权已经开启。后续 SDK/插件会使用 API key 访问。

### 6. 预拉取 Code Interpreter 镜像

插件默认使用：

```text
opensandbox/code-interpreter:v1.0.2
```

建议先手动拉取，避免 Agent 第一次执行命令时等待镜像下载：

```powershell
docker pull opensandbox/code-interpreter:v1.0.2
```

如果你换成其他镜像，需要同步修改插件工具配置里的 `image`、`entrypoint_json` 和相关环境变量。

## 安装插件

### 方式一：在界面安装 zip 插件

如果你拿到的是 `opensandbox-plugin.zip`，可以直接在 QwenPaw 界面安装：

```text
左侧菜单栏 -> 插件管理 -> 安装插件 -> 选择 opensandbox-plugin.zip
```

安装完成后，继续按本文档完成工具配置、启用 skill、启用工具，并新开会话。

### 方式二：命令行安装本地目录

在 QwenPaw 项目根目录执行：

```powershell
qwenpaw plugin install plugins/tool/opensandbox
```

如果之前已经安装过同名插件，更新本地插件代码后请使用：

```powershell
qwenpaw plugin install plugins/tool/opensandbox --force
```

插件加载时会读取：

```text
plugins/tool/opensandbox/requirements.txt
```

并安装：

```text
opensandbox>=0.1.9
```

如果自动安装依赖失败，可以在 QwenPaw 当前 Python 环境中手动安装：

```powershell
uv pip install "opensandbox>=0.1.9"
```

## 配置工具

安装后，在 QwenPaw 的工具设置中找到：

```text
execute_opensandbox_command
```

建议配置：

```text
domain: 127.0.0.1:8080
protocol: http
api_key_env: OPEN_SANDBOX_API_KEY
api_key: 留空，或填写你的 OpenSandbox API key
image: opensandbox/code-interpreter:v1.0.2
## 下述为可选
use_server_proxy: false
ready_timeout_seconds: 120
sandbox_timeout_seconds: 300
command_working_directory: /workspace
```

如果使用环境变量保存 API key，请确保 QwenPaw 后端进程能读到：

```powershell
$env:OPEN_SANDBOX_API_KEY = "your-api-key"
```

注意：只在启动 OpenSandbox server 的终端设置环境变量是不够的，QwenPaw 进程也需要能读取这个变量。

## 启用 Skill

插件会附带一个 `opensandbox` skill，用来告诉 Agent 什么时候应该使用 OpenSandbox 能力。

插件加载后，这个 skill 会被复制到 skill pool，并同步到已有 Agent workspace，默认是 disabled。插件安装完成后，需要在界面上激活技能：

```text
工作区 -> 技能 -> 搜索 opensandbox -> 启用 -> 新开会话
```

新开会话后，Agent 才会在上下文中获得 `opensandbox` skill 的使用规则。你需要启用的技能名称是：

```text
opensandbox
```

启用后，Agent 会获得这些决策规则：

- 遇到不可信脚本、一次性依赖安装实验、Linux 环境验证时，优先使用 `execute_opensandbox_command`。
- 用户明确要求“使用沙箱”“不要在本机执行”“run in OpenSandbox”时，使用 OpenSandbox。
- 需要访问宿主机项目文件、Windows 路径、本地凭证、浏览器会话或 GUI 时，不默认使用 OpenSandbox。
- 当前 MVP 没有宿主目录自动挂载或同步，所以涉及项目源码的 build/test/edit 任务不应直接放进 sandbox。

## 启用工具

启用 skill 只会让 Agent 知道什么时候应该使用 OpenSandbox；真正执行命令还需要启用工具。

在 QwenPaw 界面中：

```text
菜单栏 -> 工作区 -> 工具 -> Ctrl+F 搜索 execute_opensandbox_command -> 启用
```

然后在工具设置里：

1. 启用 `execute_opensandbox_command`
2. 禁用本地 `execute_shell_command`
3. 保存配置并让 Agent reload，必要时重启 QwenPaw

启用后建议新开会话。这样 Agent 可用的 shell 执行工具就会变成 OpenSandbox 工具。

## 验证命令

让 Agent 执行：

```text
使用沙箱执行命令：echo Hello from OpenSandbox && pwd && cat /etc/os-release
```

预期结果应该包含：

```text
OpenSandbox sandbox: <sandbox-id>
Exit code: 0
Hello from OpenSandbox
/workspace
```

并且 `/etc/os-release` 应该显示 Linux 容器系统信息，而不是 Windows。

## 当前限制

- MVP 每次工具调用都会创建一个新的 sandbox，命令之间不保留状态。
- 宿主机 Windows 路径不会自动挂载到 sandbox。
- `cwd` 如果是 Windows 路径，会被忽略并回退到 `/workspace`。
- 当前工具名不是 `execute_shell_command`，而是 `execute_opensandbox_command`。
- 如果需要透明替换内置 shell 工具，请参考 [DESIGN.md](./DESIGN.md) 中的“少量核心改动插件方案”。

## 常见问题

### 仍然在 Windows 上执行命令

检查本地 `execute_shell_command` 是否已经禁用。零核心方案不会覆盖内置 shell 工具，需要手动禁用本地 shell，并启用 `execute_opensandbox_command`。

### 提示 API key 未配置

确认以下二选一：

- 在工具配置中填写 `api_key`
- 或设置 `OPEN_SANDBOX_API_KEY`，并确保 QwenPaw 后端进程能读取

### Sandbox ready 超时

可以尝试：

- 确认 OpenSandbox server 正在运行
- 确认 Docker/Podman 后端可用
- 将 `ready_timeout_seconds` 调大到 `120` 或更高
- 本地 Windows Docker Desktop 场景下，优先使用 `use_server_proxy=false`

### `python` 命令不存在

不同镜像里 Python 命令名可能不同。先用更简单的命令验证：

```text
echo Hello from OpenSandbox && pwd
```

再尝试：

```text
python3 --version
```
