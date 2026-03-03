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
docker run -p 8088:8088 -v copaw-data:/app/working agentscope/copaw:latest
```

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
docker run -p 8088:8088 -v copaw-data:/app/working agentscope/copaw:latest
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

在控制台进入 **设置 → 模型** 中进行配置，详情请见文档 [控制台 → 模型](https://copaw.agentscope.io/docs/console#%E6%A8%A1%E5%9E%8B)：

- 云端模型：填写提供商 API Key（如 ModelScope、DashScope 或自定义提供商），再选择活跃模型。
- 本地模型：支持 `llama.cpp`、`MLX` 和 Ollama。下载后可在同页选择活跃模型。

命令行也可使用 `copaw models` 系列命令完成配置、下载和切换，详情请见文档 [CLI → 模型与环境变量 → copaw models](https://copaw.agentscope.io/docs/cli#copaw-models)。

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
