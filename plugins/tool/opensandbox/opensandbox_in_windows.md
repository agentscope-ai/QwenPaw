# OpenSandbox in Windows

本文档说明如何在 Windows 环境下准备本地 `opensandbox-server`。根据本机环境，可以选择 Docker Desktop / Docker Engine 路线，或者选择 WSL2 + k3s 路线。

## 方法选择

- 如果 Windows 上可以正常使用 Docker Desktop 或 Docker Engine，优先使用“方法一：Docker Desktop”。配置最短，适合本地快速验证。
- 如果 Windows 环境无法使用 Docker，或希望用 Kubernetes runtime 调试 OpenSandbox controller、namespace、Pod、镜像导入等问题，使用“方法二：WSL2 + k3s”。

方法一推荐拓扑：

```text
Windows / QwenPaw or QwenClaw
  -> http://127.0.0.1:8080
Windows / opensandbox-server
  -> Docker Desktop or Docker Engine
  -> OpenSandbox sandbox workloads
```

方法二推荐拓扑：

```text
Windows / QwenPaw or QwenClaw
  -> http://127.0.0.1:8080
WSL2 Ubuntu / opensandbox-server
  -> ~/.kube/config
k3s / containerd
  -> OpenSandbox sandbox workloads
```

关键点：

- Docker 路线中，`opensandbox-server` 运行在 Windows 上，插件配置通常使用 `use_server_proxy=false`。
- WSL2 + k3s 路线中，k3s 自带 containerd，不依赖 Docker；`opensandbox-server` 建议运行在同一个 WSL2 发行版中，方便访问 k3s kubeconfig。
- Windows 后端调用 WSL2/k3s 内部 Pod 时，插件配置建议使用 `use_server_proxy=true`。
- 下文示例中的 `<windows-user>`、`<wsl-user>`、`<your-api-key>` 都需要替换为你的实际值。

## 方法一：Docker Desktop / Docker Engine

### 1. 安装并验证 Docker

Windows 推荐使用 Docker Desktop，并启用 WSL2 backend。安装完成后，在 PowerShell 验证：

```powershell
docker version
docker run --rm hello-world
```

如果你使用 Podman Desktop，需要确保 `opensandbox-server` 所在进程可以通过 Docker-compatible API 访问 Podman，例如正确配置 `DOCKER_HOST`。下面默认按 Docker Desktop 编写，Podman 属于可选替代方案。

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

注意：`opensandbox-server` 是本地沙箱控制面服务；OpenSandbox 插件里的 `opensandbox>=0.1.9` 是 QwenPaw 调用 server 的 Python SDK。两者都需要，但安装位置可以不同。

### 4. 初始化 Docker runtime 配置

生成 Docker runtime 示例配置：

```powershell
uvx opensandbox-server init-config "$env:USERPROFILE\.sandbox.toml" --example docker
```

编辑 `C:\Users\<windows-user>\.sandbox.toml`，至少确认这些字段：

```toml
[server]
host = "127.0.0.1"
port = 8080
max_sandbox_timeout_seconds = 86400
api_key = "<your-api-key>"
```

本地开发建议设置非空 `api_key`。后续 QwenPaw/QwenClaw 插件配置里的 `api_key` 或 `OPEN_SANDBOX_API_KEY` 必须和这里一致。如果你的 `opensandbox-server` 没有配置 `api_key`，插件里的 `api_key` 和 `OPEN_SANDBOX_API_KEY` 可以保持为空。

### 5. 启动 opensandbox-server

在单独的 PowerShell 窗口启动：

```powershell
uvx opensandbox-server --config "$env:USERPROFILE\.sandbox.toml"
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

### 7. Docker 路线下的插件配置

在 `execute_opensandbox_command` 工具配置中建议使用：

```text
domain: 127.0.0.1:8080
protocol: http
api_key_env: OPEN_SANDBOX_API_KEY
api_key: 留空，或填写 <your-api-key>
image: opensandbox/code-interpreter:v1.0.2
use_server_proxy: false
request_timeout_seconds: 60
ready_timeout_seconds: 120
sandbox_timeout_seconds: 300
command_working_directory: /workspace
```

如果使用环境变量保存 API key，请确保 QwenPaw/QwenClaw 后端进程能读到：

```powershell
$env:OPEN_SANDBOX_API_KEY = "<your-api-key>"
```

最小验证命令：

```text
echo ok && pwd && date
```

## 方法二：WSL2 + k3s

## 1. 准备 WSL2 Ubuntu

在管理员 PowerShell 中确认 WSL 可用，并设置默认使用 WSL2：

```powershell
wsl --status
wsl --set-default-version 2
```

如果网络正常，推荐安装稳定的 Ubuntu 24.04 LTS：

```powershell
wsl --install --web-download -d Ubuntu-24.04
```

如果在线安装很慢，也可以手动下载 Ubuntu WSL 镜像。例如 Ubuntu 26.04 WSL 镜像：

```text
https://releases.ubuntu.com/26.04/ubuntu-26.04-wsl-amd64.wsl
```

用浏览器、下载器或代理下载到 Windows 后，再执行：

```powershell
wsl --install `
  --from-file "$env:USERPROFILE\Downloads\ubuntu-26.04-wsl-amd64.wsl" `
  --name Ubuntu-26.04
```

进入发行版：

```powershell
wsl -d Ubuntu-26.04
```

进入 Ubuntu 后先确认包管理器可用：

```bash
command -v apt-get
command -v dpkg
cat /etc/os-release
```

如果只有 `apt` 缺失但 `apt-get` 存在，后续全部使用 `apt-get` 即可。如果 `apt-get` 和 `dpkg` 都不存在，说明当前镜像不是常规 Ubuntu WSL rootfs，不建议继续用于 k3s；请换 Ubuntu 24.04 LTS 或其他完整 Ubuntu WSL 镜像。

可选：给 WSL2 预留资源。在 Windows 的 `%UserProfile%\.wslconfig` 中写入：

```ini
[wsl2]
memory=8GB
processors=4
localhostForwarding=true
```

修改后重启 WSL：

```powershell
wsl --shutdown
```

## 2. 启用 systemd

k3s 和 `opensandbox-server` 后台服务都依赖 systemd。进入 WSL2 Ubuntu 后执行：

```bash
sudo tee /etc/wsl.conf >/dev/null <<'EOF'
[boot]
systemd=true
EOF
```

回到 PowerShell 重启 WSL：

```powershell
wsl --shutdown
wsl -d Ubuntu-26.04
```

验证：

```bash
systemctl status
```

## 3. 配置 apt 国内镜像源

如果 `apt-get update` 很慢，可以切换到国内镜像。下面示例会自动读取当前 Ubuntu 代号，例如 24.04 是 `noble`，26.04 是 `resolute`。

```bash
CODENAME="$(. /etc/os-release && echo "${UBUNTU_CODENAME:-$VERSION_CODENAME}")"
MIRROR="https://mirrors.tuna.tsinghua.edu.cn/ubuntu/"

sudo cp /etc/apt/sources.list.d/ubuntu.sources \
  /etc/apt/sources.list.d/ubuntu.sources.bak

sudo tee /etc/apt/sources.list.d/ubuntu.sources >/dev/null <<EOF
Types: deb
URIs: ${MIRROR}
Suites: ${CODENAME} ${CODENAME}-updates ${CODENAME}-backports
Components: main restricted universe multiverse
Signed-By: /usr/share/keyrings/ubuntu-archive-keyring.gpg

Types: deb
URIs: ${MIRROR}
Suites: ${CODENAME}-security
Components: main restricted universe multiverse
Signed-By: /usr/share/keyrings/ubuntu-archive-keyring.gpg
EOF

sudo apt-get clean
sudo apt-get update
```

其他常见镜像：

```text
https://mirrors.ustc.edu.cn/ubuntu/
https://mirrors.aliyun.com/ubuntu/
https://mirrors.cloud.tencent.com/ubuntu/
```

如果镜像尚未同步当前 Ubuntu 版本，恢复官方源：

```bash
sudo cp /etc/apt/sources.list.d/ubuntu.sources.bak \
  /etc/apt/sources.list.d/ubuntu.sources
sudo apt-get update
```

安装基础工具和 uv：

```bash
sudo apt-get install -y curl ca-certificates iptables iproute2 jq

curl -LsSf https://astral.sh/uv/install.sh | sh
source "$HOME/.local/bin/env"
uvx --version
```

建议后续所有 k3s、kubectl、OpenSandbox 命令都在 Linux 文件系统下执行，例如 `~/opensandbox-work`，不要把运行目录放在 `/mnt/c/...`。

## 4. 安装单节点 k3s

方式 A：在线安装。

```bash
curl -sfL https://get.k3s.io | INSTALL_K3S_EXEC="server \
  --node-name qwenpaw-wsl-k3s \
  --write-kubeconfig-mode=644" sh -
```

方式 B：手动下载后安装。适合 `https://get.k3s.io` 或 GitHub 下载很慢的环境。

在 Windows 侧从 k3s Releases 下载同一版本的文件：

```text
https://github.com/k3s-io/k3s/releases
```

建议下载：

```text
k3s
k3s-airgap-images-amd64.tar.zst
sha256sum-amd64.txt
install.sh
```

其中 `install.sh` 可以从这里保存：

```text
https://get.k3s.io
```

或：

```text
https://raw.githubusercontent.com/k3s-io/k3s/master/install.sh
```

假设文件放在 Windows 的 `Downloads` 目录，在 WSL2 中执行：

```bash
export K3S_VERSION="v1.33.1+k3s1"
export WIN_DOWNLOADS="/mnt/c/Users/<windows-user>/Downloads"

sudo install -m 755 "$WIN_DOWNLOADS/k3s" /usr/local/bin/k3s
k3s --version

mkdir -p ~/k3s-install
cp "$WIN_DOWNLOADS/install.sh" ~/k3s-install/install.sh
chmod +x ~/k3s-install/install.sh
```

可选：校验二进制：

```bash
cd "$WIN_DOWNLOADS"
grep " k3s$" sha256sum-amd64.txt | sha256sum -c -
```

可选：预加载 k3s air-gap 镜像，避免启动时继续拉基础镜像：

```bash
sudo mkdir -p /var/lib/rancher/k3s/agent/images
sudo cp "$WIN_DOWNLOADS/k3s-airgap-images-amd64.tar.zst" \
  /var/lib/rancher/k3s/agent/images/
```

用本地二进制安装 k3s：

```bash
cd ~/k3s-install
sudo INSTALL_K3S_SKIP_DOWNLOAD=true \
  INSTALL_K3S_VERSION="$K3S_VERSION" \
  INSTALL_K3S_EXEC="server \
    --node-name qwenpaw-wsl-k3s \
    --write-kubeconfig-mode=644" \
  ./install.sh
```

等待服务启动：

```bash
sudo systemctl status k3s --no-pager
kubectl get nodes -o wide
kubectl get pods -A
```

如果不需要 k3s 自带的 Traefik 或 ServiceLB，安装时可追加：

```text
--disable=traefik --disable=servicelb
```

## 5. 准备 kubeconfig

k3s 默认 kubeconfig 在：

```text
/etc/rancher/k3s/k3s.yaml
```

复制到当前用户目录：

```bash
mkdir -p ~/.kube
sudo cp /etc/rancher/k3s/k3s.yaml ~/.kube/config
sudo chown "$USER:$USER" ~/.kube/config
chmod 600 ~/.kube/config
echo 'export KUBECONFIG=$HOME/.kube/config' >> ~/.bashrc
export KUBECONFIG="$HOME/.kube/config"
kubectl get nodes
```

## 6. 配置 k3s 镜像拉取

k3s 使用 containerd，不走 Docker daemon。镜像源要写在：

```text
/etc/rancher/k3s/registries.yaml
```

示例：

```bash
sudo mkdir -p /etc/rancher/k3s
sudo tee /etc/rancher/k3s/registries.yaml >/dev/null <<'EOF'
mirrors:
  docker.io:
    endpoint:
      - "https://<your-dockerhub-mirror>"
EOF

sudo systemctl restart k3s
```

手动导入 Docker 镜像 tar 包：

```bash
sudo k3s ctr images import /path/to/image.tar
sudo k3s crictl images
```

如果 tar 包在 Windows 下载目录：

```bash
sudo k3s ctr images import /mnt/c/Users/<windows-user>/Downloads/image.tar
```

预拉取 OpenSandbox 镜像：

```bash
sudo k3s crictl pull opensandbox/code-interpreter:v1.0.2
sudo k3s crictl pull opensandbox/execd:0.2.0
```

验证 k3s 可运行 Pod：

```bash
kubectl run k3s-smoke \
  --image=busybox:1.36 \
  --restart=Never \
  --command -- sh -c 'echo ok from k3s && nslookup kubernetes.default.svc && sleep 5'

kubectl logs pod/k3s-smoke
kubectl delete pod/k3s-smoke
```

## 7. 安装 OpenSandbox Controller

如果还没有 Helm，先安装：

```bash
curl -fsSL -o get_helm.sh https://raw.githubusercontent.com/helm/helm/main/scripts/get-helm-3
chmod 700 get_helm.sh
./get_helm.sh
helm version
```

安装 OpenSandbox Kubernetes controller。当前示例使用 `0.2.0`：

```bash
helm install opensandbox-controller \
  https://github.com/alibaba/OpenSandbox/releases/download/helm/opensandbox-controller/0.2.0/opensandbox-controller-0.2.0.tgz \
  --namespace opensandbox-system \
  --create-namespace

kubectl get pods -n opensandbox-system
```

创建 sandbox workload 的命名空间：

```bash
kubectl create namespace opensandbox --dry-run=client -o yaml | kubectl apply -f -
kubectl get namespace opensandbox
```

controller 安装在 `opensandbox-system`，实际 sandbox 默认创建在 `opensandbox`。

## 8. 配置并启动 opensandbox-server

生成 Kubernetes runtime 示例配置：

```bash
uvx opensandbox-server init-config ~/.sandbox.toml --example k8s
```

编辑 `~/.sandbox.toml`，至少确认：

```toml
[server]
host = "0.0.0.0"
port = 8080
api_key = "<your-api-key>"

[runtime]
type = "kubernetes"
execd_image = "opensandbox/execd:0.2.0"

[kubernetes]
kubeconfig = "/home/<wsl-user>/.kube/config"
namespace = "opensandbox"
batchsandbox_template_file = "/home/<wsl-user>/batchsandbox-template.yaml"
```

如果示例配置字段名与上面略有差异，以 `uvx opensandbox-server init-config --example k8s` 生成的字段为准。重点是 kubeconfig、namespace、workload provider、BatchSandbox template file 都要正确。

下载 BatchSandbox 模板文件：

```bash
curl -L -o ~/batchsandbox-template.yaml \
  https://raw.githubusercontent.com/alibaba/OpenSandbox/main/server/example.batchsandbox-template.yaml

test -f ~/batchsandbox-template.yaml
```

启动 server：

```bash
uvx opensandbox-server --config ~/.sandbox.toml
```

验证：

```bash
curl http://127.0.0.1:8080/health
```

Windows PowerShell 侧也要能访问：

```powershell
curl.exe http://127.0.0.1:8080/health
```

## 9. 后台运行 opensandbox-server

确认 `uvx` 路径：

```bash
command -v uvx
```

创建 systemd 服务。把 `<wsl-user>` 替换为你的 WSL 用户名，并把 `ExecStart` 改成实际 `uvx` 路径：

```bash
sudo tee /etc/systemd/system/opensandbox-server.service >/dev/null <<'EOF'
[Unit]
Description=OpenSandbox Server
After=network-online.target k3s.service
Wants=network-online.target
Requires=k3s.service

[Service]
Type=simple
User=<wsl-user>
WorkingDirectory=/home/<wsl-user>
Environment=HOME=/home/<wsl-user>
Environment=PATH=/home/<wsl-user>/.local/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
ExecStart=/home/<wsl-user>/.local/bin/uvx opensandbox-server --config /home/<wsl-user>/.sandbox.toml
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF
```

启动并设置自启：

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now opensandbox-server
systemctl status opensandbox-server --no-pager
```

查看日志：

```bash
journalctl -u opensandbox-server -n 200 --no-pager
journalctl -u opensandbox-server -f
```

关闭 WSL 终端不会停止 systemd 服务；但执行下面命令会停止整个 WSL：

```powershell
wsl --shutdown
wsl --terminate Ubuntu-26.04
```

如果希望 Windows 登录后自动拉起 WSL，可以创建计划任务，命令使用：

```powershell
wsl.exe -d Ubuntu-26.04 --exec /bin/true
```

## 10. QwenPaw/QwenClaw 插件配置

在 `execute_opensandbox_command` 工具配置中建议使用：

```text
domain: 127.0.0.1:8080
protocol: http
api_key_env: OPEN_SANDBOX_API_KEY
api_key: 留空，或填写 <your-api-key>
image: opensandbox/code-interpreter:v1.0.2
use_server_proxy: true
request_timeout_seconds: 60
ready_timeout_seconds: 180
sandbox_timeout_seconds: 300
command_working_directory: /workspace
```

`use_server_proxy=true` 很重要。Windows 进程通常不能直接访问 WSL2 k3s 的 Pod IP 或 ClusterIP，通过 OpenSandbox server 代理访问更稳。

如果使用环境变量保存 API key，需要确保 QwenPaw/QwenClaw 后端进程也能读到：

```powershell
$env:OPEN_SANDBOX_API_KEY = "<your-api-key>"
```

验证命令建议从最小命令开始：

```text
echo ok && pwd && date
```

## 11. 导出和导入调试好的 WSL

在原 Windows 机器 PowerShell 中执行：

```powershell
wsl -l -v
wsl --terminate Ubuntu-26.04
wsl --export Ubuntu-26.04 D:\backup\Ubuntu-26.04-opensandbox.tar
```

把 tar 文件复制到新机器后导入：

```powershell
wsl --set-default-version 2
mkdir D:\WSL\Ubuntu-26.04
wsl --import Ubuntu-26.04 D:\WSL\Ubuntu-26.04 D:\backup\Ubuntu-26.04-opensandbox.tar --version 2
wsl -d Ubuntu-26.04
```

导入后检查：

```bash
systemctl status k3s --no-pager
systemctl status opensandbox-server --no-pager
kubectl get nodes
kubectl get pods -A
curl http://127.0.0.1:8080/health
```

如果新机器用户名不同，需要检查这些位置是否仍包含旧路径：

```bash
grep -R "/home/" ~/.sandbox.toml /etc/systemd/system/opensandbox-server.service
```

修改后执行：

```bash
sudo systemctl daemon-reload
sudo systemctl restart opensandbox-server
```

## 12. 常见问题

### 没有 apt 或 apt-get

```bash
command -v apt
command -v apt-get
command -v dpkg
cat /etc/os-release
```

如果 `apt-get` 存在，只是 `apt` 不存在，继续使用 `apt-get`。如果 `apt-get` 和 `dpkg` 都不存在，请换完整 Ubuntu WSL 镜像。

### systemctl 无法使用

确认 `/etc/wsl.conf`：

```ini
[boot]
systemd=true
```

然后在 PowerShell 执行：

```powershell
wsl --shutdown
```

重新进入 Ubuntu 后再检查 `systemctl status`。

### kubectl 权限错误

```bash
mkdir -p ~/.kube
sudo cp /etc/rancher/k3s/k3s.yaml ~/.kube/config
sudo chown "$USER:$USER" ~/.kube/config
chmod 600 ~/.kube/config
export KUBECONFIG="$HOME/.kube/config"
```

### FailedCreatePodSandBox 拉取 pause 镜像失败

如果看到：

```text
failed to get sandbox image "rancher/mirrored-pause:3.6"
```

先配置 registry mirror，或离线导入 pause 镜像：

```bash
sudo k3s ctr images import /path/to/rancher-mirrored-pause-3.6.tar
sudo k3s crictl images | grep mirrored-pause
sudo systemctl restart k3s
```

如果有 `k3s-airgap-images-amd64.tar.zst`：

```bash
sudo mkdir -p /var/lib/rancher/k3s/agent/images
sudo cp /path/to/k3s-airgap-images-amd64.tar.zst \
  /var/lib/rancher/k3s/agent/images/
sudo systemctl restart k3s
```

### OpenSandbox controller Pod ErrImagePull

查看缺哪个镜像：

```bash
kubectl describe pod -n opensandbox-system <pod-name>
```

导入缺失镜像后删除 Pod，让 Deployment 自动重建：

```bash
kubectl delete pod -n opensandbox-system <pod-name>
kubectl get pods -n opensandbox-system -w
```

### BatchSandbox template file not found

如果启动 `opensandbox-server` 时报：

```text
BatchSandbox template file not found
```

下载模板文件并确保 `~/.sandbox.toml` 中的 `batchsandbox_template_file` 指向它：

```bash
curl -L -o ~/batchsandbox-template.yaml \
  https://raw.githubusercontent.com/alibaba/OpenSandbox/main/server/example.batchsandbox-template.yaml
```

### namespaces "opensandbox" not found

创建 namespace：

```bash
kubectl create namespace opensandbox --dry-run=client -o yaml | kubectl apply -f -
kubectl get namespace opensandbox
```

如果改成其他 namespace，需要同步修改 `~/.sandbox.toml` 并重启 `opensandbox-server`。

### Sandbox Pod Running 但命令不返回

优先确认插件配置：

```text
use_server_proxy: true
```

然后检查日志：

```bash
journalctl -u opensandbox-server -n 200 --no-pager
kubectl logs -n opensandbox-system deploy/opensandbox-controller-manager --tail=200
kubectl get pods -n opensandbox -o wide
kubectl logs -n opensandbox <sandbox-pod-name> --all-containers --tail=200
```

进入 sandbox Pod 看命令是否还在运行：

```bash
kubectl exec -n opensandbox -it <sandbox-pod-name> -- sh
ps -ef
```

清理卡住的 Pod：

```bash
kubectl delete pod -n opensandbox <sandbox-pod-name>
```

### 重置本地 k3s

确认不需要保留集群数据后执行：

```bash
sudo /usr/local/bin/k3s-uninstall.sh
```

## 参考资料

- Ubuntu WSL image: https://releases.ubuntu.com/
- Microsoft WSL install: https://learn.microsoft.com/en-us/windows/wsl/install
- Microsoft WSL systemd: https://learn.microsoft.com/en-us/windows/wsl/systemd
- Docker Desktop Windows install: https://docs.docker.com/desktop/setup/install/windows-install/
- K3s Quick-Start Guide: https://docs.k3s.io/quick-start
- K3s Environment Variables: https://docs.k3s.io/reference/env-variables
- K3s Air-Gap Install: https://docs.k3s.io/installation/airgap
- K3s Private Registry Configuration: https://docs.k3s.io/installation/private-registry
- K3s Releases: https://github.com/k3s-io/k3s/releases
- Helm Installing Helm: https://helm.sh/docs/v3/intro/install/
- uv installation: https://docs.astral.sh/uv/getting-started/installation/
- OpenSandbox server README: https://github.com/alibaba/OpenSandbox/blob/main/server/README.md
- OpenSandbox Kubernetes README: https://github.com/alibaba/OpenSandbox/blob/main/kubernetes/README.md
