# 快速开始

本节介绍五种方式运行 CoPAW：

- **方式一 — 一键安装（推荐）**：无需手动配置 Python，一行命令自动完成安装。
- **方式二 — pip 安装**：适合自行管理 Python 环境的用户。
- **方式三 — 魔搭创空间**：一键配置，部署到创空间云端运行，无需本地安装。
- **方式四 — Docker**：使用官方镜像（Docker Hub；国内可选 ACR），镜像 tag 含 `latest`（稳定版）与 `pre`（PyPI 预发布版）。
- **方式五 — 阿里云 ECS**：在阿里云上一键部署 CoPaw，无需本地安装。

> 📖 阅读前请先了解 [项目介绍](./intro)，完成安装与启动后可查看 [控制台](./console)。

> 💡 **安装并启动后**：在配置频道之前，可先打开 [控制台](./console)（浏览器访问 `http://127.0.0.1:8088/`）与 CoPAW 对话、配置 Agent；要在钉钉、飞书、QQ 等 app 里对话时，再前往 [频道配置](./channels) 接入频道。

---

## 方式一：一键安装（推荐）

无需预装 Python — 安装脚本通过 [uv](https://docs.astral.sh/uv/) 自动管理一切。

### 步骤一：安装

**macOS / Linux：**

```bash
curl -fsSL https://copaw.agentscope.io/install.sh | bash
```

然后打开新终端（或执行 `source ~/.zshrc` / `source ~/.bashrc`）。

**Windows（PowerShell）：**

```powershell
irm https://copaw.agentscope.io/install.ps1 | iex
```

然后打开新终端（安装脚本会自动将 CoPaw 加入 PATH）。

也可以指定选项：

**macOS / Linux：**

```bash
# 安装指定版本
curl -fsSL ... | bash -s -- --version 0.0.2

# 从源码安装（开发/测试用）
curl -fsSL ... | bash -s -- --from-source

# 安装本地模型支持（详见本地模型文档）
bash install.sh --extras llamacpp    # llama.cpp（跨平台）
bash install.sh --extras mlx         # MLX（Apple Silicon）
bash install.sh --extras ollama      # Ollama（跨平台，需 Ollama 服务运行）
```

**Windows（PowerShell）：**

```powershell
# 安装指定版本
.\install.ps1 -Version 0.0.2

# 从源码安装（开发/测试用）
.\install.ps1 -FromSource

# 安装本地模型支持（详见本地模型文档）
.\install.ps1 -Extras llamacpp      # llama.cpp（跨平台）
.\install.ps1 -Extras mlx           # MLX
.\install.ps1 -Extras ollama        # Ollama
```

升级只需重新运行安装命令。卸载请运行 `copaw uninstall`。

### 步骤二：初始化

在工作目录（默认 `~/.copaw`）下生成 `config.json` 与 `HEARTBEAT.md`。两种方式：

- **快速用默认配置**（不交互，适合先跑起来再改配置）：
  ```bash
  copaw init --defaults
  ```
- **交互式初始化**（按提示填写心跳间隔、投递目标、活跃时段，并可顺带配置频道与 Skills）：
  ```bash
  copaw init
  ```
  详见 [CLI - 快速上手](./cli#快速上手)。

若已有配置想覆盖，可使用 `copaw init --force`（会提示确认）。
初始化后若尚未启用频道，接入钉钉、飞书、QQ 等需在 [频道配置](./channels) 中按文档填写。

### 步骤三：启动服务

```bash
copaw app
```

服务默认监听 `127.0.0.1:8088`。若已配置频道，CoPaw 会在对应 app 内回复；若尚未配置，也可先完成本节再前往频道配置。

---

## 方式二：pip 安装

如果你更习惯自行管理 Python 环境（需 Python >= 3.10, < 3.14）：

```bash
pip install copaw
```

可选：先创建并激活虚拟环境再安装（`python -m venv .venv`，Linux/macOS 下
`source .venv/bin/activate`，Windows 下 `.venv\Scripts\Activate.ps1`）。安装后会提供 `copaw` 命令。

然后按上方 [步骤二：初始化](#步骤二初始化) 和 [步骤三：启动服务](#步骤三启动服务) 操作。

---

## 方式三：魔搭创空间一键配置（无需安装）

若不想在本地安装 Python，可通过魔搭创空间将 CoPaw 部署到云端运行：

1. 先前往 [魔搭](https://modelscope.cn/register?back=%2Fhome) 注册并登录；
2. 打开 [CoPaw 创空间](https://modelscope.cn/studios/fork?target=AgentScope/CoPaw)，一键配置即可使用。

**重要**：使用创空间请将空间设为 **非公开**，否则你的 CoPaw 可能被他人操纵。

---

## 方式四：Docker

镜像在 **Docker Hub**（`agentscope/copaw`）。镜像 tag：`latest`（稳定版）；`pre`（PyPI 预发布版）。国内用户也可选用阿里云 ACR：`agentscope-registry.ap-southeast-1.cr.aliyuncs.com/agentscope/copaw`（tag 相同）。

拉取并运行：

```bash
docker pull agentscope/copaw:latest
docker run -p 8088:8088 -v copaw-data:/app/working agentscope/copaw:latest
```

然后在浏览器打开 **http://127.0.0.1:8088/** 进入控制台。配置、记忆与 Skills 保存在 `copaw-data` 卷中。传入 API Key 可在 `docker run` 时加 `-e DASHSCOPE_API_KEY=xxx` 或 `--env-file .env`。

---

## 方式五：部署到阿里云 ECS

若希望将 CoPaw 部署在阿里云上，可使用阿里云 ECS 一键部署：

1. 打开 [CoPaw 阿里云 ECS 部署链接](https://computenest.console.aliyun.com/service/instance/create/cn-hangzhou?type=user&ServiceId=service-1ed84201799f40879884)，按页面提示填写部署参数；
2. 参数配置完成后确认费用并创建实例，部署完成后即可获取访问地址并使用服务。

详细步骤与说明请参考 [阿里云开发者社区：CoPaw 3 分钟部署你的 AI 助理](https://developer.aliyun.com/article/1713682)。

---

## 验证安装（可选）

服务启动后,可通过 HTTP 调用 Agent 接口以确认环境正常。接口为 **POST** `/api/agent/process`,请求体为 JSON,支持 SSE 流式响应。单轮请求示例:

```bash
curl -N -X POST "http://localhost:8088/api/agent/process" \
  -H "Content-Type: application/json" \
  -d '{"input":[{"role":"user","content":[{"type":"text","text":"你好"}]}],"session_id":"session123"}'
```

同一 `session_id` 可进行多轮对话。

---

## 接下来做什么？

- **想和 CoPAW 对话** → 去 [频道配置](./channels) 接一个频道（推荐先接钉钉或飞书），按文档申请应用、填 config，保存后即可在对应 app 里发消息试。
- **想定时自动跑一套「自检/摘要」** → 看 [心跳](./heartbeat)，编辑 HEARTBEAT.md 并在 config 里设间隔和 target。
- **想用更多命令** → [CLI](./cli)（交互式 init、定时任务、清空工作目录）、[Skills](./skills)。
- **想改工作目录或配置文件路径** → [配置与工作目录](./config)。
