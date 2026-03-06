# FAQ 常见问题

本页汇总了社区里的常见问题，点击问题可展开查看答案。

---

### CoPaw 与 OpenClaw 的功能对比

请查看 [对比](/docs/comparison) 页面了解详细的功能对比。

### CoPaw如何安装

CoPaw 支持多种安装方式，详情请见文档 [快速开始](https://copaw.agentscope.io/docs/quickstart)：

1. 一键安装，帮你搞定 Python 环境

```
# macOS / Linux:
curl -fsSL https://copaw.agentscope.io/install.sh | bash
# Windows（PowerShell）:
irm https://copaw.agentscope.io/install.ps1 | iex
# 关注文档更新，请先采用pip方式完成一键安装
```

2. pip 安装

Python环境要求版本号 >= 3.10，<3.14

```
pip install copaw
```

3. Docker 安装

如果你已经安装好了Docker，执行以下两条命令后，即可在浏览器打开 http://127.0.0.1:8088/ 进入控制台。

```
docker pull agentscope/copaw:latest
docker run -p 127.0.0.1:8088:8088 -v copaw-data:/app/working agentscope/copaw:latest
```

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

### CoPaw如何更新

要更新 CoPaw 到最新版本，可根据你的安装方式选择对应方法：

1. 如果你使用的是一键安装脚本，直接重新运行安装命令即可自动升级。

2. 如果你是通过 pip 安装，在终端中执行以下命令升级：

```
pip install --upgrade copaw
```

3. 如果你是从源码安装，进入项目目录并拉取最新代码后重新安装：

```
cd CoPaw
git pull origin main
pip install -e .
```

4. 如果你使用的是 Docker，拉取最新镜像并重启容器：

```
docker pull agentscope/copaw:latest
docker run -p 127.0.0.1:8088:8088 -v copaw-data:/app/working agentscope/copaw:latest
```

升级后重启服务 copaw app。

### CoPaw服务如何启动及初始化

推荐使用默认配置快速初始化：

```bash
copaw init --defaults
```

启动服务命令：

```bash
copaw app
```

控制台默认地址为 `http://127.0.0.1:8088/`，使用默认配置快速初始化后，可以进入控制台快捷自定义相关内容。详情请见[快速开始](https://copaw.agentscope.io/docs/quickstart)。

### 开源地址

CoPaw 已开源，官方仓库地址：
`https://github.com/agentscope-ai/CoPaw`

### 最新版本升级内容如何查看

具体版本变更可在 CoPaw GitHub 仓库 [Releases](https://github.com/agentscope-ai/CoPaw/releases) 中查看。

### 如何配置模型

在控制台进入 **设置 → 模型** 中进行配置，详情请见文档 [模型](https://copaw.agentscope.io/docs/models)：

- 云端模型：填写提供商 API Key（如 ModelScope、DashScope 或自定义提供商），再选择活跃模型。
- 本地模型：支持 `llama.cpp`、`MLX` 和 Ollama。下载后可在同页选择活跃模型。

命令行也可使用 `copaw models` 系列命令完成配置、下载和切换，详情请见文档 [CLI → 模型与环境变量 → copaw models](https://copaw.agentscope.io/docs/cli#copaw-models)。

### 定时任务错误排查

在控制台进入 **控制 → 定时任务** ，在这里可以创建和管理定时任务。

![cron](https://img.alicdn.com/imgextra/i4/O1CN01hNk4od1uuTwGRT2sk_!!6000000006097-2-tps-3802-1968.png)

最方便的定时任务创建方式是，在你想要获取定时任务返回结果的频道，与CoPaw对话，让CoPaw帮你创建一个定时任务。例如，可以直接与CoPaw对话：“帮我创建一个定时任务，每隔五分钟提醒我喝水。”之后可以在控制台中看到状态为已启用的定时任务。

如果定时任务没有正常启动，可以按照以下几个步骤排查：

1. 首先确认 CoPaw 服务是在正常运行中的。

2. 定时任务的 **启用状态** 是否为 **已启动**。

   ![enable](https://img.alicdn.com/imgextra/i1/O1CN01gVVf081o6ClZVBrhD_!!6000000005175-2-tps-3020-754.png)

3. 定时任务的 **DispatchChannel** 是否被正确地设置为了想要获取返回结果的频道，如 console、dingtalk、feishu、discord、imessage 等。

   ![channel](https://img.alicdn.com/imgextra/i4/O1CN01xUaLG61lVRkO7ZfY4_!!6000000004824-2-tps-3020-754.png)

4. **DispatchTargetUserID** 和 **DispatchTargetSessionID** 的值是否设置正确。

   ![id](https://img.alicdn.com/imgextra/i1/O1CN014e0BHN1CFPKDS7Kd7_!!6000000000051-2-tps-3020-754.png)

   核查方式为，在控制台进入 **控制 → 会话**，找到刚刚创建定时任务的会话。如果想要定时任务返回到这个会话中，需要核查 **UserID** 和 **SessionID** 是否与定时任务的 **DispatchTargetUserID** 和 **DispatchTargetSessionID** 相同。

   ![id](https://img.alicdn.com/imgextra/i3/O1CN01ZmgYTC1wiEZx7rOjK_!!6000000006341-2-tps-3020-928.png)

5. 如果觉得定时任务的触发间隔时间不对，需要确认一下定时任务的 **执行时间（Cron）**是否正确。

   ![cron](https://img.alicdn.com/imgextra/i1/O1CN01WpN8l51kKANPSlK8r_!!6000000004664-2-tps-3020-762.png)

6. 排查结束后，如果想确认一下定时任务是否创建成功，且能成功触发，可以点击 **立即执行**，若成功创建，则可在对应频道收到回复。或者也可以直接与 CoPaw 对话：“帮我触发一下刚刚创建的提醒喝水定时任务”。

   ![exec](https://img.alicdn.com/imgextra/i4/O1CN017tycJh1ZPhO5XMuAu_!!6000000003187-2-tps-3020-762.png)

### 如何管理Skill

进入控制台 **智能体 → 技能**，可以启用/禁用技能、创建自定义技能、以及从 Skills Hub 中导入技能。详情请见文档 [Skills](https://copaw.agentscope.io/docs/skills)。

### 如何配置MCP

进入控制台 **智能体 → MCP**，进行 MCP 客户端的启用/禁用/删除/创建，详情请见文档 [MCP](https://copaw.agentscope.io/docs/mcp)。

### 常见报错

1. 报错样式：You didn't provide an API key

报错详情：

Error: Unknown agent error: AuthenticationError: Error code: 401 - {'error': {'message': "You didn't provide an API key. You need to provide your API key in an Authorization header using Bearer auth (i.e. Authorization: Bearer YOUR_KEY). ", 'type': 'invalid_request_error', 'param': None, 'code': None}, 'request_id': 'xxx'}

原因1：没有配置模型 API key，需要获取 API key后，在**控制台 → 设置 → 模型**中配置。

原因2：配置了 key 但仍报错，通常是配置项填写错误（如 `base_url`、`api key` 或模型名）。

CoPaw 支持百炼 Coding Plan 获取的 API key。如果仍报错，请重点检查：

- `base_url` 是否填写正确；
- API key 是否粘贴完整（无多余空格）；
- 模型名称是否与平台一致（注意大小写）。

正确获取方式可参考：
https://help.aliyun.com/zh/model-studio/coding-plan-quickstart#2531c37fd64f9

---

### 报错如何获取修复帮助

为了加快修复与排查，共建良好社区生态，建议遇到报错时，首选在 CoPaw 的 GitHub 仓库中提 [issue](https://github.com/agentscope-ai/CoPaw/issues)，请附上完整报错信息，并上传错误详情文件。

控制台报错里通常会给出错误文件路径，例如在以下报错中：

Error: Unknown agent error: AuthenticationError: Error code: 401 - {'error': {'message': "You didn't provide an API key. You need to provide your API key in an Authorization header using Bearer auth (i.e. Authorization: Bearer YOUR_KEY). ", 'type': 'invalid_request_error', 'param': None, 'code': None}, 'request_id': 'xxx'}(Details: /var/folders/.../copaw_query_error_qzbx1mv1.json)

请将后面的`/var/folders/.../copaw_query_error_qzbx1mv1.json`文件一并上传，同时提供你当前的模型提供商、模型名和 CoPaw 的具体版本。
