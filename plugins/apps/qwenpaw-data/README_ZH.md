# QwenPaw-Data

**企业级自进化、图驱动的 Agentic BI**

源码：[QwenPaw-Data](https://github.com/agentscope-ai/QwenPaw-Data)

[English README](./README.md)

QwenPaw-Data 是一个原生 QwenPaw 应用。其前端挂载在 `/apps/qwenpaw-data`，后端注册在 `/api/qwenpaw-data`，context service 由后端私有管理。

## QwenPaw-Data 是什么？

[QwenPaw-Data](https://github.com/agentscope-ai/QwenPaw-Data) 将自主、图驱动的数据分析能力引入 QwenPaw 工作区，让用户可以用自然语言提出业务问题，并获得可追溯、富含工件、由真实企业数据支撑的答案。

## 界面截图

<p align="center">
  <img src="https://raw.githubusercontent.com/agentscope-ai/QwenPaw/main/plugins/apps/qwenpaw-data/assets/screenshots/cm-graph.png" alt="元数据图谱可视化" width="900" />
  <br/>
  <em>元数据图谱：语义模型、维度、指标与血缘关系</em>
</p>

<p align="center">
  <img src="https://raw.githubusercontent.com/agentscope-ai/QwenPaw/main/plugins/apps/qwenpaw-data/assets/screenshots/analysis-result.png" alt="端到端分析结果" width="900" />
  <br/>
  <em>端到端分析：自然语言提问 → 受控 SQL → 可追溯答案</em>
</p>

## 核心理念

企业数据分析是开放式、充满歧义且持续演进的。一个可用的数据智能体必须在每次任务中回答三个问题：

- **用什么事实**：业务概念、指标、维度、表、血缘和历史上下文。
- **如何分析**：可复用的分析方法论，而不是每次请求都临时推理。
- **如何运行**：可控的长周期、以工件为中心的 workflow 运行时。

QwenPaw-Data 通过三层协作架构实现这一目标：

| 层 | 角色 | 管理内容 |
| --- | --- | --- |
| **DataBridge** | 证据接地 | 元数据图、知识图谱、语义配置、数据源和任务轨迹。 |
| **Skill-Hub** | 方法编排 | 从粗粒度路由到原子 SQL、可视化、报告生成等可复用分析技能。 |
| **Host** | 执行控制 | DAG 规划、工具调用、工件注册和故障恢复。 |

## 端到端示例

一个典型的请求，例如 *"查看 product X 的 MAU"*，会经历以下阶段：

1. **规划（Plan）**。Host 咨询 Skill-Hub 对请求进行路由，并将其分解为 DAG：识别指标、获取数据、计算 MAU、汇总结论。
2. **接地（Ground）**。DataBridge 通过语义层解析 "MAU" 和 "product X"，将其映射到 `dws_gaap_di` 表及相应过滤条件。
3. **执行（Execute）**。Host 对已注册数据源执行受控 SQL，并将结果注册为工件。
4. **报告（Report）**。最终答案结合方法论、来源链接和覆盖说明，统一呈现在聊天面板中。
5. **进化（Evolve）**。轨迹、反馈和已确认的定义回流到 DataBridge 和 Skill-Hub，为下一次类似问题积累可复用经验。

## 运行时形态

```text
Embedded QwenPaw-Data Console
  -> /api/qwenpaw-data/engine/* -> analysis engine
  -> /api/qwenpaw-data/config  -> DataBridge model and Neo4j settings
  -> linked Context console
     -> /api/qwenpaw-data/context/* -> DataBridge context service
```

PawApp 后端代理服务请求并注入服务 token。托管服务使用动态回环端口，外部服务使用配置的地址。QwenPaw-Data 显式启用 PawApp 标准能力；未选择加入的现有 PawApp 不会获得额外的 chat、storage、toast 或 notify 路由。

## 快速开始（推荐：PyPI）

无需 `QwenPaw-Data` 源码工作区，最快的运行方式是将运行时包从 PyPI 安装到与 QwenPaw 相同的 Python 环境中。

```bash
pip install "qwenpaw[qwenpaw-data]"
```

如果你想锁定兼容版本，也可以使用便捷脚本：

```bash
./plugins/apps/qwenpaw-data/scripts/setup-pypi.sh
```

然后启动 QwenPaw 并启用 QwenPaw-Data app。PawApp 生命周期会自动检测 PyPI 包，并在动态回环端口上启动托管 Context 服务和分析引擎。

```bash
qwenpaw app
```

> 该路径推荐给只需要 QwenPaw-Data app、已有自己的 Neo4j / PostgreSQL 基础设施，或想在没有 demo 数据的情况下试用 app 的用户。

### PyPI + docker-compose 演示数据

如果你还需要 bundled GAAP 演示数据（Neo4j 图 + PostgreSQL 数据源），先启动基础设施容器，再以 external context mode 运行 QwenPaw：

```bash
cd plugins/apps/qwenpaw-data
cp .env.example .env
docker compose up -d neo4j postgres context seed

# 在另一个终端
QWENPAW_DATA_CONTEXT_MODE=external \
QWENPAW_DATA_CONTEXT_URL=http://127.0.0.1:8765 \
QWENPAW_DATA_CONTEXT_TOKEN=qwenpaw-data-demo-token \
qwenpaw app
```

这是**推荐的一键演示路径**：无需在 Docker 内编译 QwenPaw，即可获得完整播种的图和数据源。

## 本地包开发环境

源码工作区默认位于 `~/dev/QwenPaw-Data`。其隔离的 `.venv` 中包含 `qwenpaw-data-context`、`qwenpaw-data-host-core`、`qwenpaw-data-cli` 和 `qwenpaw-data-skills` 的可编辑安装，因此它们的依赖版本不会影响 QwenPaw 环境。

```bash
./scripts/setup-dev.sh
cd ui && npm install && npm run build
```

UI 以浏览器原生 ES module 形式交付。其 Vite 配置在构建时替换 `process.env.NODE_ENV`，因此打包后的依赖不会把 Node 专属的 `process` 全局变量泄漏到 QwenPaw Console 中。

完整 Data console 以经过审核的 vendor snapshot 形式存放在 `ui/public/data-console/`。常规构建、CI 和用户均无需访问 QwenPaw-Data-Cloud；只有获得授权的维护者或 coding agent 才通过 `scripts/update-data-console.sh` 刷新 snapshot，并审核、发布所产生的 diff。Context console 则由 `scripts/sync-context-ui.sh` 从公开的 QwenPaw-Data 源码单独构建。

`setup-dev.sh` 会同步 QwenPaw-Data 工作区并在本 app 下创建被忽略的 development links。如需使用其他 checkout，请设置 `QWENPAW_DATA_SOURCE_DIR`。运行时仅当另一个进程管理器拥有该服务时，才使用 `QWENPAW_DATA_CONTEXT_MODE=external` 并配置 `QWENPAW_DATA_CONTEXT_URL` 和 `QWENPAW_DATA_CONTEXT_TOKEN`。

如需一步完成构建、暂存并安装到本地 QwenPaw 实例，运行 `./scripts/dev.sh`。`QWENPAW_BIN` 和 `QWENPAW_WORKING_DIR` 用于选择目标实例。安装程序默认指向 `127.0.0.1:8089`；需要时可通过 `QWENPAW_HOST` 和 `QWENPAW_PORT` 覆盖。

## Docker compose 一键演示

如果你希望在没有本地 `QwenPaw-Data` 源码工作区的情况下，一键启动 Neo4j + PostgreSQL + 已播种 GAAP 数据，可以使用以下 stack。该 stack 使用 PyPI 上的 `qwenpaw-data-context` 和 `qwenpaw-data-cli` 包。

```bash
cd plugins/apps/qwenpaw-data
cp .env.example .env
docker compose up -d
```

这会启动：

- `neo4j` —— 图存储（端口 7687 / 7474）
- `postgres` —— GAAP 演示数据源（端口 55432）
- `context` —— external context service（端口 8765）
- `seed` —— 注入 bundled demo SQL、导入语义 workbook 并 weave 到 Neo4j
- `qwenpaw` *(可选)* —— 从仓库根目录构建完整 QwenPaw 镜像

如果 `qwenpaw` 服务构建太慢或失败（例如 ACR 基础镜像不可用），可以只启动基础设施并在本地运行 QwenPaw：

```bash
docker compose up -d neo4j postgres context seed
# 在另一个终端，从 QwenPaw 仓库根目录运行
QWENPAW_DATA_CONTEXT_MODE=external QWENPAW_DATA_CONTEXT_URL=http://127.0.0.1:8765 QWENPAW_DATA_CONTEXT_TOKEN=qwenpaw-data-demo-token qwenpaw app
```

如需手动重新运行 seed 容器（例如在清空 Postgres 卷后）：

```bash
./scripts/init-demo.sh
```

## 配置

0.3 运行时集成使用内嵌的 **Data Console**。设置菜单提供两个配置页面，独立的 **数据语义配置中心（Data Bridge）** 入口打开 Context 控制台的数据源页面。请使用这些入口，替代旧版 PawApp 的 **Configure** 操作说明。

| 配置内容 | 配置入口 |
| --- | --- |
| 分析智能体的模型服务商、凭证和激活模型 | Data Console 的 **设置 → 智能体配置（Agent Configuration）** |
| DataBridge 语义服务的 LLM、Embedding 模型和 Neo4j 图存储 | Data Console 的 **设置 → 数据底座配置（DataBridge Configuration）** |
| PostgreSQL、MySQL 等 SQL 数据源 | **数据语义配置中心 → 数据源**，进入关联的 Context 控制台 |

数据底座配置提供 **测试连接**、**保存** 和 **保存并重启 Context 服务**。这里的 LLM 用于语义织网和文档摄取；分析对话的模型在智能体配置中单独选择。

在数据源页面登记 SQL 连接信息、测试连接，并在发起分析时选择已登记的数据源。DataBridge 通过 `/api/semantic-config/datasource` 管理这些凭证，将其保存在语义配置注册表（`semantic_config.db`）中。保存 Neo4j 或模型设置不会创建 SQL 数据源，也不会将 SQL 凭证写入 `.env`。

### 配置存储与运行时文件

保存 **数据底座配置** 时，应用在 QwenPaw 工作目录下写入以下文件（默认目录为 `~/.qwenpaw/apps/qwenpaw-data/`）：

- `config.json` —— PawApp 的 DataBridge 模型与 Neo4j 设置、宿主模型复用标记，以及 Context 服务选中的数据源 ID。SQL 凭证保存在 DataBridge 注册表中。
- `.env` —— 为托管 Context 服务生成的 Neo4j 与模型变量（`NEO4J_*`、`OPENAI_*`、`LLM_MODEL`、`EMBED_*`）。
- `models.json` —— Context 服务的 LLM 与 Embedding 设置。

这些文件不包含 Data Console 的全部设置：智能体配置通过分析引擎 API 保存引擎自身的模型偏好。每次启动托管 Context 服务时，PawApp 都会从 `config.json` 重新生成 `.env` 和 `models.json`。模型变更也会推送给运行中的 Context 服务；托管模式下修改 Neo4j 后，使用 **保存并重启 Context 服务** 生效。外部服务由部署维护者负责重启。

DataBridge 启用 **复用 QwenPaw 已配置的模型** 后，保存配置或启动托管 Context 服务会从宿主当前可用的激活模型刷新快照。Embedding 复用共享宿主服务商的地址和凭证，但保留所选的 Embedding 模型与维度。这与智能体配置中的分析模型选择分别管理。

### 环境默认值与覆盖规则

首次初始化时，PawApp 从环境变量填充空缺的 DataBridge 字段，也可以从 QwenPaw 获取兼容的默认模型。保存配置后，`config.json` 是生成运行时文件和托管子进程环境的权威来源：Shell 或 QwenPaw 环境变量不会覆盖已保存值；清空受管字段后，下次启动不再带入旧值。保存配置、复用宿主模型及启动两个托管服务均不修改 QwenPaw 主进程环境。环境默认值只在首次初始化时导入，不会补回已清空的凭证。

托管子进程只继承基础操作系统变量，以及各服务在 [`backend/main.py`](backend/main.py) 中明确声明的变量。两个服务均声明了网络代理和证书配置；Context 另接收声明过的存储、数据管道和 Embedding 参数，Engine 另接收声明过的运行参数和 Docker 配置。其他全局变量不再自动透传，新增集成需明确声明所需变量；QwenPaw 全局环境变量管理本身保持原有行为。

请通过 **数据底座配置** 修改已保存值；直接编辑应用生成的 `.env` 会在下次保存或启动托管服务时被覆盖。外部 Context 服务的启动环境由该部署管理。两种模式下，SQL 数据源凭证都通过数据源注册表管理。

### 配置验证（TC-DATA-04）

验证 0.3 集成时，请使用当前配置契约：

1. 保存 DataBridge 模型与 Neo4j 设置，检查 `config.json`、`.env` 中已填写的 Neo4j/模型变量，以及 `models.json` 中的 LLM/Embedding 设置。`.env` 不应被要求包含 SQL 数据源变量。
2. 启用宿主模型复用，切换到另一个兼容的宿主激活模型，然后保存配置或重启托管 Context 服务。确认模型快照刷新，且已保存的设置在重启后仍然存在。
3. 在数据源页面登记并测试 SQL 数据源。确认 Context 服务重启后注册信息仍然存在，再在 Data Console 中选择该数据源，对测试数据库执行一次只读查询。
4. 在智能体配置中单独验证分析模型选择。

旧用例中“保存 Neo4j/LLM 配置后，`.env` 同时生成 SQL 数据源变量”的预期不适用于当前配置契约。

## 运行时健康检查与本地服务

- 在 QwenPaw 的 **Settings → Models** 中激活一个语言模型，以便 QwenPaw-Data 在首次运行时自动填充默认模型。之后可以在 **数据底座配置** 中覆盖；分析智能体的激活模型在 **智能体配置** 中选择。
- QwenPaw-Data 通过 PawApp 依赖契约声明 Context API、Graph Store 和已发现数据源。Data sources 页面会显示就绪状态、能力影响、修复建议和可用的实际操作。
- 本 app 不会调用 Docker 或供应 Graph Store / 数据源基础设施。这些资源是外部依赖，仅接受只读的就绪检查。本地生命周期和诊断属于 `qwenpaw-data-cli` 包；生产生命周期由部署的服务所有者负责。

缺失的 host 配置会通过 PawApp SDK 以结构化的 service-unavailable 错误上报。QwenPaw-Data 将 `MODEL_NOT_CONFIGURED` 转换为可操作的 UI 消息，而不是显示通用 HTTP 500。

本 app 还会选择加入 App 私有的依赖状态与生命周期工具。QwenPaw-Data 智能体可以检查与 UI 相同的控制平面，并仅请求已注册的操作；这些工具不会导出到 Main Chat。Host 仍负责能力治理与审计。

### 本地基础设施速查

服务端点由环境变量驱动，本地默认值仅作参考；没有硬编码。`qwenpaw-data-context` 在启动时解析它们（详见 QwenPaw-Data 工作区 `packages/qwenpaw-data-context/src/context_manager/config.py` 和 `packages/qwenpaw-data-context/README.md`）：

| 依赖 | 配置方式 | 本地默认值 |
| --- | --- | --- |
| Graph Store (Neo4j) | **数据底座配置**；外部部署管理 `NEO4J_URI`、`NEO4J_USER`、`NEO4J_PASSWORD`、`NEO4J_DATABASE` | `bolt://localhost:7687` |
| 数据源 (PostgreSQL / MySQL / ODPS / ...) | 通过 DataBridge 语义配置层注册 (`/api/semantic-config/datasource`)，不从 `.env` 读取 | 无 |
| DataBridge LLM / Embedding | **数据底座配置**；环境默认值使用 `OPENAI_API_KEY`、`OPENAI_BASE_URL`、`LLM_MODEL`、`EMBED_*` | — |
| 分析智能体模型 | Data Console 的 **智能体配置** | — |

本地生命周期，按所有者划分：

- **Graph Store (Neo4j)** —— 由 QwenPaw-Data 工作区工具拥有：`scripts/start_databridge.sh` 会复用 bolt 端口上已可达的 Neo4j，否则运行 `packages/qwenpaw-data-context/docker-compose.yml`。这要求运行中的 Docker daemon（例如 `colima start`）以及工作区 `.env` 中的 `NEO4J_PASSWORD`。
- **诊断** —— `qwenpaw-data doctor --json` 以只读方式报告 Docker、Neo4j、DataBridge API 和模型配置的就绪状态，并给出修复建议。
- **数据源服务器** —— 外部基础设施。QwenPaw Data 各包负责其注册和就绪检查，从不负责供应。

独立的 DataBridge API (`127.0.0.1:8765`) 仅在 QwenPaw 外运行 QwenPaw-Data 时使用。在 QwenPaw 内部，PawApp 生命周期会在动态回环端口上管理私有 context service，因此单独的 `doctor` 8765 失败不会影响本 app。

## 各包职责

- `qwenpaw-data-context`：context API、语义配置和图记忆。同时拥有本地 Graph Store 定义 (`docker-compose.yml`) 和语义配置层中的数据源注册。
- `qwenpaw-data-host-core`：共享分析运行时和编排契约。不接触基础设施。
- `qwenpaw-data-skills`：app 提供的数据分析技能。
- `qwenpaw-data-cli`：独立生命周期和诊断工具（`doctor`、`datasource`、`semantic`）；是唯一被设计为拥有本地基础设施命令的 QwenPaw Data 包。数据源服务器本身仍属于外部基础设施。

托管模式下，用户只需启动 QwenPaw 这一个 UI / 后端入口。PawApp 生命周期会自动启动和停止 Context 服务及 `qwenpaw-data-host-core` 分析引擎。内嵌 Data Console 通过 PawApp 网关访问该引擎；`/data` 通过渠道桥接将 QwenPaw 渠道对话路由到同一引擎。
