# OpenSandbox in Windows

Windows 环境下，OpenSandbox 插件仍只执行 Linux sandbox 内命令，不用于执行 Windows PowerShell、CMD、`.bat`、`.ps1`、Windows PATH、本机进程或 GUI 任务。

## 业务场景

| 场景 | 推荐后端 | 适用条件 | 设计取舍 |
| --- | --- | --- | --- |
| 本地快速验证 OpenSandbox | Docker Desktop / Docker Engine | Windows 上 Docker 可正常使用，sandbox workload 可通过本机 Docker 运行 | 配置最短，`opensandbox-server` 和 QwenPaw 都在 Windows 侧访问 `127.0.0.1:8080` |
| Kubernetes runtime 调试 | WSL2 + k3s | 需要调试 OpenSandbox controller、namespace、Pod、containerd、镜像导入或 Kubernetes 网络 | 更接近 Kubernetes 部署形态，但需要处理 WSL2、k3s、kubeconfig 和 server proxy |
| 远程 Agent 访问本机 OpenSandbox | Docker 或 WSL2 + k3s | OpenSandbox server 需要被其他机器访问 | MCP client 的 `--domain` 必须改为可访问的主机 IP 或域名 |
| 临时 Web/API 预览 | Docker 或 WSL2 + k3s | Agent 在 sandbox 内启动服务后通过 endpoint 访问 | 推荐通过 `sandbox_get_endpoint` 暴露 URL，避免直接依赖 Pod IP、ClusterIP 或宿主端口细节 |

默认优先选择 Docker Desktop / Docker Engine。只有在 Docker 不可用、需要 Kubernetes runtime，或需要复现 Kubernetes 侧问题时，才选择 WSL2 + k3s。

## 架构技术设计

### Docker 路线

```text
Windows / QwenPaw or QwenClaw
  -> opensandbox MCP client
  -> http://127.0.0.1:8080
Windows / opensandbox-server
  -> Docker Desktop or Docker Engine
  -> OpenSandbox sandbox workloads
  -> execd data-plane
```

关键设计：

- `opensandbox-server` 运行在 Windows 上。
- QwenPaw 的 `opensandbox` MCP client 通过 `127.0.0.1:8080` 访问 server。
- Docker runtime 负责创建 Linux sandbox workload。
- `execd_image` 由 server 注入，用于 command/file/endpoint 等 data-plane 操作。

最小 runtime 配置：

```toml
[server]
host = "127.0.0.1"
port = 8080
api_key = "<your-api-key>"

[runtime]
type = "docker"
execd_image = "opensandbox/execd:v1.0.16"
```

### WSL2 + k3s 路线

```text
Windows / QwenPaw or QwenClaw
  -> opensandbox MCP client
  -> http://127.0.0.1:8080
WSL2 Ubuntu / opensandbox-server
  -> ~/.kube/config
k3s / containerd
  -> OpenSandbox sandbox workloads
  -> execd data-plane
```

关键设计：

- k3s 运行在 WSL2 Ubuntu 中，并使用自带 containerd。
- `opensandbox-server` 建议运行在同一个 WSL2 发行版中，方便访问 k3s kubeconfig。
- Windows 侧 QwenPaw 通过 `127.0.0.1:8080` 访问 WSL2 中的 `opensandbox-server`。
- Pod IP / ClusterIP 通常不能从 Windows 侧直接访问，因此推荐启用 server proxy。

最小 runtime 配置：

```toml
[server]
host = "0.0.0.0"
port = 8080
api_key = "<your-api-key>"

[runtime]
type = "kubernetes"
execd_image = "opensandbox/execd:v1.0.16"

[runtime.kubernetes]
kubeconfig_path = "/home/<wsl-user>/.kube/config"
namespace = "opensandbox"
```

#### Windows 侧保活 WSL2

如果 `opensandbox-server` 和 k3s 都运行在 WSL2 中，Windows 侧没有其它进程连接
WSL 时，WSL 发行版可能会自动退出。可以在 Windows PowerShell 中启动一个隐藏
窗口的 WSL 保活进程，避免调试期间 WSL 被回收。把 `Ubuntu-26.04` 替换成实际
发行版名称：

```powershell
Start-Process -WindowStyle Hidden -FilePath wsl.exe -ArgumentList @(
  "-d", "Ubuntu-26.04",
  "--exec", "/usr/bin/sleep", "infinity"
)
```

不再需要保活时，可以关闭对应 WSL 发行版：

```powershell
wsl.exe --terminate Ubuntu-26.04
```

也可以用下面命令查看发行版名称：

```powershell
wsl.exe --list --verbose
```

### MCP Client 配置

Windows 侧 QwenPaw / QwenClaw 只需要连接 `opensandbox-server`：

```text
key: opensandbox
name: OpenSandbox MCP
transport: stdio
enabled: false
command: 自动计算为当前 QwenPaw Python 解释器
args: [
  "<plugin_dir>\\opensandbox_mcp_launcher.py",
  "--domain",
  "127.0.0.1:8080",
  "--protocol",
  "http",
  "--use-server-proxy"
]
cwd: 自动计算为插件安装目录
env:
  OPEN_SANDBOX_API_KEY=<your-api-key 或留空>
```

`command`、launcher 路径和 `cwd` 由插件安装/加载时自动生成。通常只需要启用 MCP client，并按实际 server 地址修改 `--domain`、`--protocol`、`OPEN_SANDBOX_API_KEY`、`--use-server-proxy` 或 `--no-use-server-proxy`。

如果 OpenSandbox server 开放给远程 Agent 访问，`--domain` 不应继续使用 `127.0.0.1:8080`，需要改成远程 Agent 可访问的 IP 或域名。

### Server Proxy 策略

`use_server_proxy` 决定命令、文件和 endpoint 访问是否通过 `opensandbox-server` 代理到 sandbox 内部 execd。

- Docker 路线：如果端口映射地址可从 Windows 直连，可以使用 `false`；默认保留 `true` 更稳妥。
- WSL2 + k3s 路线：推荐使用 `true`，避免 Windows 侧直连 Pod IP / ClusterIP。
- 远程 Agent：推荐使用 `true`，由 server 统一代理 sandbox data-plane。

### 镜像边界

两个镜像语义必须分开：

- `execd_image = "opensandbox/execd:v1.0.16"`：写在 `.sandbox.toml` 的 `[runtime]` 中，由 `opensandbox-server` 注入 sandbox，负责 command/file/endpoint。
- `sandbox_create.image = "opensandbox/code-interpreter:v1.0.2"`：Agent 创建 workload sandbox 时使用的运行环境镜像。

当前插件只允许 Agent 创建：

```text
opensandbox/code-interpreter:v1.0.2
```

其他 `sandbox_create.image` 会被 MCP launcher 拒绝：

```text
not support image, pls use "opensandbox/code-interpreter:v1.0.2" instead.
```

### 运行边界

- 插件和 MCP client 不负责安装 Docker、WSL2、k3s、Helm 或 OpenSandbox controller。
- OpenSandbox server、runtime、镜像和 Kubernetes controller 需要在插件启用前准备好。
- Windows 宿主路径不会自动挂载到 sandbox。
- 小型文本可以由 Agent 通过 `file_write` 写入 sandbox；目录同步、二进制传输和产物回传需要后续 host sync / artifact bridge。
- sandbox 内 `/workspace` 不等同于 Windows 宿主项目目录。
