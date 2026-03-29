# 快速开始

本节介绍多种方式安装 CoPaw：

| 安装方式       | 适用场景                 | 优势                         | 前置要求         |
| -------------- | ------------------------ | ---------------------------- | ---------------- |
| **脚本安装**   | 不想要手动配置环境的用户 | 零配置，自动管理 Python 环境 | 无               |
| **pip 安装**   | 熟悉 Python 的开发者     | 灵活控制环境，便于开发调试   | Python 3.10~3.13 |
| **桌面应用**   | 不熟悉命令行的用户       | 双击即用，图形化界面         | 无               |
| **魔搭创空间** | 无本地环境或快速体验     | 一键部署，云端运行，无需安装 | 魔搭账号         |
| **Docker**     | 容器化部署或生产环境     | 环境隔离，易于迁移           | Docker           |
| **阿里云 ECS** | 云上稳定运行             | 一键部署，稳定可靠           | 阿里云账号       |

> 📖 阅读前请先了解 [项目介绍](./intro)，完成安装与启动后可查看 [控制台](./console)。

> 💡 **安装并启动后的关键步骤**：
>
> 1. 在浏览器访问 [控制台](./console)（`http://127.0.0.1:8088/`）
> 2. **配置模型**（必需）：设置 → 模型 → 配置 API Key 或下载本地模型
> 3. 开始对话测试
> 4. （可选）配置频道以在钉钉、飞书、QQ 等 app 里对话，详见 [频道配置](./channels)

---

## 方式一：脚本安装

无需预装 Python — 安装脚本通过 [uv](https://docs.astral.sh/uv/) 自动管理一切。

### 步骤一：安装

**macOS / Linux：**

```bash
curl -fsSL https://copaw.agentscope.io/install.sh | bash
```

然后打开新终端（或执行 `source ~/.zshrc` / `source ~/.bashrc`）。

**Windows (CMD):**

```cmd
curl -fsSL https://copaw.agentscope.io/install.bat -o install.bat && install.bat
```

**Windows（PowerShell）：**

```powershell
irm https://copaw.agentscope.io/install.ps1 | iex
```

然后打开新终端（安装脚本会自动将 CoPaw 加入 PATH）。

> **⚠️ Windows 企业版 LTSC 用户特别提示**
>
> 如果您使用的是 Windows LTSC 或受严格安全策略管控的企业环境，PowerShell 可能运行在 **受限语言模式** 下，可能会遇到以下问题：
>
> 1. **如果你使用的是 CMD（.bat）：脚本执行成功但无法写入`Path`**
>
>    脚本已完成文件安装，由于 **受限语言模式** ，脚本无法自动写入环境变量，此时只需手动配置：
>
>    - **找到安装目录**：
>      - 检查 `uv` 是否可用：在 CMD 中输入 `uv --version` ，如果显示版本号，则**只需配置 CoPaw 路径**；如果提示 `'uv' 不是内部或外部命令，也不是可运行的程序或批处理文件。`，则需同时配置两者。
>      - uv路径（任选其一，取决于安装位置，若`uv`不可用则填）：通常在`%USERPROFILE%\.local\bin`、`%USERPROFILE%\AppData\Local\uv`或 Python 安装目录下的 `Scripts` 文件夹
>      - CoPaw路径：通常在 `%USERPROFILE%\.copaw\bin` 。
>    - **手动添加到系统的 Path 环境变量**：
>      - 按 `Win + R`，输入 `sysdm.cpl` 并回车，打开“系统属性”。
>      - 点击 “高级” -> “环境变量”。
>      - 在 “系统变量” 中找到并选中 `Path`，点击 “编辑”。
>      - 点击 “新建”，依次填入上述两个目录路径，点击确定保存。
>
> 2. **如果你使用的是 PowerShell（.ps1）：脚本运行中断**
>
> 由于 **受限语言模式** ，脚本可能无法自动下载`uv`。
>
> - **手动安装uv**：参考 [GitHub Release](https://github.com/astral-sh/uv/releases)下载并将`uv.exe`放至`%USERPROFILE%\.local\bin`或`%USERPROFILE%\AppData\Local\uv`；或者确保已安装 Python ，然后运行`python -m pip install -U uv`
> - **配置`uv`环境变量**：将`uv`所在目录和 `%USERPROFILE%\.copaw\bin` 添加到系统的 `Path` 变量中。
> - **重新运行**：打开新终端，再次执行安装脚本以完成 `CoPaw` 安装。
> - **配置`CoPaw`环境变量**：将 `%USERPROFILE%\.copaw\bin` 添加到系统的 `Path` 变量中。

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

## 方式三：桌面应用

如果你不习惯使用命令行，可以下载并使用 CoPaw 的桌面应用版本，无需手动配置 Python 环境或执行命令。

### 特点

- ✅ **零配置**：下载后双击即可运行，无需安装 Python 或配置环境变量
- ✅ **跨平台**：支持 Windows 10+ 和 macOS 14+ (推荐 Apple Silicon)
- ✅ **可视化**：自动打开浏览器界面，无需手动输入地址

### 下载与使用

1. **下载安装包**
   前往 [GitHub Releases](https://github.com/agentscope-ai/CoPaw/releases) 下载对应系统的版本：

   - Windows: `CoPaw-Setup-<version>.exe`
   - macOS: `CoPaw-<version>-macOS.zip`

2. **安装并启动**

   - **Windows**: 双击 `.exe` 文件按向导安装，完成后双击桌面快捷方式启动
   - **macOS**: 解压 `.zip` 得到 `CoPaw.app`，首次需右键选择"打开"以绕过系统安全限制

3. **首次启动提示**
   首次启动可能需要 10-60 秒（取决于系统配置），应用需要初始化 Python 环境和加载依赖，请耐心等待浏览器窗口自动打开。

### 完整使用指南

桌面应用涉及系统权限、安全提示、调试模式等细节，请查看 **[桌面应用完整指南](./desktop)** 了解：

- Windows 两种启动模式（普通版 vs Debug 版）
- macOS 如何解除系统安全限制（3种方法）
- 常见问题与解决方案
- 日志查看与问题报告

---

## 方式四：魔搭创空间一键配置（无需安装）

若不想在本地安装 Python，可通过魔搭创空间将 CoPaw 部署到云端运行：

1. 先前往 [魔搭](https://modelscope.cn/register?back=%2Fhome) 注册并登录；
2. 打开 [CoPaw 创空间](https://modelscope.cn/studios/fork?target=AgentScope/CoPaw)，一键配置即可使用。

**重要**：使用创空间请将空间设为 **非公开**，否则你的 CoPaw 可能被他人操纵。

---

## 方式五：Docker

镜像在 **Docker Hub**（`agentscope/copaw`）。镜像 tag：`latest`（稳定版）；`pre`（PyPI 预发布版）。国内用户也可选用阿里云 ACR：`agentscope-registry.ap-southeast-1.cr.aliyuncs.com/agentscope/copaw`（tag 相同）。

拉取并运行：

```bash
docker pull agentscope/copaw:latest
docker run -p 127.0.0.1:8088:8088 \
  -v copaw-data:/app/working \
  -v copaw-secrets:/app/working.secret \
  agentscope/copaw:latest
```

然后在浏览器打开 **http://127.0.0.1:8088/** 进入控制台。配置、记忆与 Skills 保存在 `copaw-data` 卷中；模型配置与 API Key 保存在 `copaw-secrets` 卷中。传入 API Key 可在 `docker run` 时加 `-e DASHSCOPE_API_KEY=xxx` 或 `--env-file .env`。

---

## 方式六：部署到阿里云 ECS

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

### 必要步骤

#### ✅ 1. 配置模型（必需）

CoPaw 需要大语言模型才能工作。你可以选择以下任一方式：

**选项 A：使用云端模型（需要 API Key）**

1. 在控制台进入 **设置 → 模型**
2. 选择一个提供商（如 DashScope、ModelScope 等）
3. 点击 **设置** 按钮，输入你的 **API Key**
4. 点击 **保存**
5. 在顶部 **LLM 配置** 中选择该提供商和具体模型
6. 点击 **保存**

详见 [模型 - 配置云提供商](./models#配置云提供商)。

**选项 B：使用本地模型（无需 API Key，完全离线）**

1. 安装本地模型后端依赖：

   ```bash
   # llama.cpp（跨平台）
   pip install 'copaw[llamacpp]'

   # MLX（Apple Silicon）
   pip install 'copaw[mlx]'

   # Ollama（需单独安装 Ollama 服务）
   pip install 'copaw[ollama]'
   ```

2. 下载模型：

   - **控制台方式**：设置 → 模型 → 选择本地提供商 → 模型 → 下载模型
   - **命令行方式**：
     ```bash
     copaw models download Qwen/Qwen3-4B-GGUF
     copaw models  # 选择已下载的模型
     ```

3. 在控制台选择本地提供商和模型

详见 [模型 - 本地提供商](./models#本地提供商llamacpp--mlx)。

#### 🎯 2. 在控制台测试对话

模型配置完成后，在控制台的 **聊天** 页面发送消息测试功能，确认 CoPaw 可以正常回复。

---

### 可选扩展

配置模型并测试成功后，可以根据需要进行以下扩展：

#### 📱 接入消息频道

在钉钉、飞书、QQ、Discord、iMessage 等 app 里与 CoPaw 对话：

1. 在控制台进入 **控制 → 频道**
2. 选择要接入的频道
3. 按照 [频道配置](./channels) 文档获取凭据并填写
4. 保存后即可在对应 app 中发消息给 CoPaw

#### 🔧 启用和扩展技能

赋予 CoPaw 更多能力（PDF 处理、Office 文档、新闻摘要等）：

- 在控制台进入 **智能体 → 技能池** 或 **智能体 → 技能**
- 导入内置技能、从 Skill Hub 导入、或创建自定义技能
- 详见 [Skills](./skills)

#### 🔌 接入 MCP 工具

通过 MCP（Model Context Protocol）扩展外部工具能力：

- 在控制台进入 **智能体 → MCP**
- 创建 MCP 客户端，连接外部工具服务器
- 详见 [MCP](./mcp)

#### ⏰ 设置定时任务与心跳

让 CoPaw 自动执行任务：

- **定时任务**：在控制台 **控制 → 定时任务** 中创建，或使用 [CLI](./cli) 的 `copaw cron` 命令
- **心跳**：配置定时自检或摘要，详见 [心跳](./heartbeat)

#### 👥 创建多智能体

创建多个专用助手，各司其职或互相协作：

- 在控制台 **设置 → 智能体管理** 中创建新智能体
- 每个智能体拥有独立的配置、记忆、技能和对话历史
- 启用协作技能让智能体间可以互相通信
- 详见 [多智能体](./multi-agent)

#### 📂 调整工作目录

如需更改配置文件或工作目录的位置，详见 [配置与工作目录](./config)。
