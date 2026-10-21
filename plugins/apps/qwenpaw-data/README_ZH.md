# QwenPaw-Data

**企业级自进化、图驱动的 Agentic BI**

源码：[QwenPaw-Data](https://github.com/agentscope-ai/QwenPaw-Data)

[English README](./README.md)

QwenPaw-Data 是一个原生 QwenPaw 应用。其前端挂载在 `/apps/qwenpaw-data`，后端注册在 `/api/qwenpaw-data`，context service 由后端私有管理。

## QwenPaw-Data 是什么？

[QwenPaw-Data](https://github.com/agentscope-ai/QwenPaw-Data) 将自主、图驱动的数据分析能力引入 QwenPaw 工作区，让用户可以用自然语言提出业务问题，并获得可追溯、富含工件、由真实企业数据支撑的答案。

## 会话工作区

<p align="center">
  <img src="https://raw.githubusercontent.com/agentscope-ai/QwenPaw-Data/main/assets/qwenpaw-app/session-workspace.png" alt="QwenPaw-Data 会话工作区，展示分析结果、CSV 工件和对话轮次" width="900" />
  <br/>
  <em>会话工作区：在对话中查看数据分析、可追溯结果和可下载工件。</em>
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

## 从提问到结果

对已导入的 GAAP 演示数据，可以问：**「查看 product X 在 2026 年 3 月每日的 GAAP 值」**。
演示表是 `dws_gaap_di`。

1. **连接并选择数据。** 在 DataBridge 登记并测试数据源，然后在 Data Console 选择该源、重新加载数据集，并按需选择数据集随问题提交。仅启动数据库不会自动登记数据源或导入语义定义。
2. **确认问题口径。** 智能体结合所选数据源和 DataBridge 上下文确认指标、日期范围及相关表；问题不明确时可以请求澄清。
3. **执行分析。** 智能体调用取数和分析工具。简单问题可以直接执行，复杂分析可以建立任务计划并使用分析技能；并非每个问题都会创建 DAG。
4. **查看并继续。** 在会话工作区查看回答、业务轨迹及可用的输出和执行记录，下载生成的工件，或在同一会话继续追问。

具体计划和输出取决于问题、可用数据、模型和工具配置。完成一次分析不等于自动更新业务定义或技能。

## 运行时形态

```text
Embedded QwenPaw-Data Console
  -> /api/qwenpaw-data/engine/* -> analysis engine
  -> /api/qwenpaw-data/config  -> DataBridge model and Neo4j settings
  -> linked Context console
     -> /api/qwenpaw-data/context/* -> DataBridge context service
```

PawApp 后端代理服务请求并注入服务 token。托管服务使用动态回环端口，外部服务使用配置的地址。QwenPaw-Data 显式启用 PawApp 标准能力；未选择加入的现有 PawApp 不会获得额外的 chat、storage、toast 或 notify 路由。

## 快速开始：安装应用与 Python 运行时

应用 **1.0.3** 面向 QwenPaw **2.2.2**，已验证的 QwenPaw-Data 运行时为 **0.3.3**。
应用 ZIP 和 Python 运行时需要分别安装。

1. 在 QwenPaw 的应用管理中安装或更新 QwenPaw-Data。
2. 在 QwenPaw 使用的 Python 环境中安装运行时。锁定已验证版本的命令为：

   ```bash
   python -m pip install "qwenpaw-data-context==0.3.3" "qwenpaw-data-host-core[service]==0.3.3" "qwenpaw-data-cli==0.3.3" "qwenpaw-data-skills==0.3.3"
   ```

   也可以在 QwenPaw 源码仓库运行 `./plugins/apps/qwenpaw-data/scripts/setup-pypi.sh`。
   该脚本安装 `>=0.3.3,<0.4` 范围内的兼容版本，并非精确锁定 0.3.3。
   如果运行时使用独立环境，在启动 QwenPaw 前将 `QWENPAW_DATA_CONTEXT_PYTHON`
   设置为该环境的 Python 可执行文件；QwenPaw 进程必须能够访问它。
3. 启动或重启 QwenPaw，并启用应用。Python 安装方式可以运行：

   ```bash
   qwenpaw app
   ```

4. 在主聊天配置模型服务商和工作区默认模型。Data 分析默认继承该模型；摘要和 DataBridge 默认继承分析模型，无需重复配置凭据。
5. 配置 DataBridge 的 Neo4j 连接和 Embedding 服务，再登记并测试 SQL 数据源。打开 `/apps/qwenpaw-data`，选择数据源、重新加载数据集并提问。

托管模式下，应用在私有回环端口启动 Context 服务和分析引擎。Neo4j 和数据库服务器需要单独就绪。
启动服务器、登记数据源和导入语义元数据是不同的步骤。

## 使用 Docker Compose 启动本地基础设施

在 QwenPaw 源码仓库中，可以只启动 Neo4j 和 PostgreSQL，让应用管理 **0.3.3** 的 Context 和 Engine 服务：

```bash
cd plugins/apps/qwenpaw-data
# 仅首次配置时复制；保留已有 .env。
cp -n .env.example .env
docker compose up -d neo4j postgres
```

按示例默认值，Neo4j 地址是 `bolt://127.0.0.1:7687`，用户名 `neo4j`，密码 `qwenpaw-data-demo`。
PostgreSQL 登记为 `127.0.0.1:55432`，数据库 `qwenpaw_data_demo`，用户名 `qwenpaw_data`，密码 `qwenpaw-data-demo`。
如果修改过 `.env`，使用修改后的值。这些地址适用于 QwenPaw 与 Docker 发布端口位于同一宿主机的情况。

以上只启动基础设施，**不会**填充 GAAP 数据或导入语义定义。已有数据库可以直接登记。
演示资产和语义导入、织网说明见
[QwenPaw-Data 示例](https://github.com/agentscope-ai/QwenPaw-Data/tree/v0.3.3/examples)及
[CLI 指南](https://github.com/agentscope-ai/QwenPaw-Data/blob/v0.3.3/packages/qwenpaw-data-cli/README.md)。

仓库中的 `context` 和 `seed` Dockerfile 仍锁定 **0.3.0**，属于旧版演示，不是应用 1.0.3 的推荐安装方式。
不指定服务的 `docker compose up -d` 还会构建 `qwenpaw` 服务；只有显式选择服务才能排除它。
完整演示栈的升级和验证需要单独处理，不包含在本次 README 与打包修复中。

如果使用独立部署且兼容运行时 0.3.3 的 Context 服务，在启动 QwenPaw 前配置
`QWENPAW_DATA_CONTEXT_MODE=external`、`QWENPAW_DATA_CONTEXT_URL` 和 `QWENPAW_DATA_CONTEXT_TOKEN`。
该服务必须提供运行时模型绑定能力；不兼容时应用会明确报错。
分析引擎仍需要运行时，除非另行配置了外部 Engine 服务。

## 源码开发

从 QwenPaw 仓库根目录开始，并准备兼容的 QwenPaw-Data 源码 checkout；复现本次发布时使用其 `v0.3.3` 标签。
这些脚本需要 Bash、Python、uv、Node.js 和 npm。

```bash
export QWENPAW_DATA_SOURCE_DIR="$HOME/dev/QwenPaw-Data"
cd plugins/apps/qwenpaw-data
./scripts/setup-dev.sh
./scripts/sync-context-ui.sh
(cd ui && npm ci && npm run build)
```

`setup-dev.sh` 在 QwenPaw-Data checkout 中运行 `uv sync --all-packages`，并创建指向独立 `.venv`、源码和技能的开发链接；
它不会构建或安装应用 UI。`sync-context-ui.sh` 先构建公开的 Context 控制台，然后应用 UI 构建将其复制到 `ui/dist/`。

Data Console 使用 `ui/public/data-console/` 中经过审核的快照。常规构建无需 QwenPaw-Data-Cloud 仓库；
维护者通过 `scripts/update-data-console.sh` 刷新快照并审核差异。

构建 Context 控制台后，在应用目录运行 `./scripts/dev.sh`，可以构建、暂存并热安装到**已经运行**的本地 QwenPaw。
用 `QWENPAW_HOST` 和 `QWENPAW_PORT` 指定目标实例，默认是 `127.0.0.1:8089`；
目标实例使用自定义数据目录时，还需设置 `QWENPAW_WORKING_DIR`。

## 配置

应用打开内嵌的 **Data Console**。**设置 → 智能体配置（Agent Configuration）** 中有 **Models** 和 **Agent behavior** 两个标签页。
独立的 **数据底座配置（DataBridge Configuration）** 页面管理共享 Context 服务；**数据语义配置中心（Data Bridge）** 打开关联的 Context 控制台。

| 配置内容 | 配置入口 |
| --- | --- |
| 模型服务商凭据与工作区默认模型 | 主聊天的模型设置 |
| Data 分析、摘要及 DataBridge 模型覆盖 | **设置 → 智能体配置 → Models** |
| 迭代次数与模型调用重试策略 | **设置 → 智能体配置 → Agent behavior** |
| 共享 DataBridge 语义服务的 LLM、Embedding 与 Neo4j | **设置 → 数据底座配置** |
| PostgreSQL、MySQL 等 SQL 数据源 | **数据语义配置中心 → 数据源** |

数据底座配置提供 **测试连接**、**保存** 和 **保存并重启 Context 服务**，其中的 LLM 用于语义织网和文档摄取等服务任务。
分析对话默认使用主聊天工作区模型，摘要和 DataBridge 默认继承分析模型，仅在需要时选择覆盖。
Embedding 及图索引是独立的共享服务设置，也可以在 **Models → Embedding & data index** 中管理。

在数据源页面登记 SQL 连接信息、测试连接，并在发起分析时选择已登记的数据源。DataBridge 通过 `/api/semantic-config/datasource` 管理这些凭证，将其保存在语义配置注册表（`semantic_config.db`）中。保存 Neo4j 或模型设置不会创建 SQL 数据源，也不会将 SQL 凭证写入 `.env`。

### 配置存储与运行时文件

保存 **数据底座配置** 时，应用在 QwenPaw 工作目录下写入以下文件（`<QWENPAW_WORKING_DIR>/apps/qwenpaw-data/`；未指定工作目录时优先使用已有的 `~/.copaw`，否则使用 `~/.qwenpaw`）：

- `config.json` —— PawApp 的 DataBridge 模型与 Neo4j 设置、宿主模型复用标记，以及 Context 服务选中的数据源 ID。SQL 凭证保存在 DataBridge 注册表中。
- `.env` —— 为托管 Context 服务生成的 Neo4j 与模型变量（`NEO4J_*`、`OPENAI_*`、`LLM_MODEL`、`EMBED_*`）。
- `models.json` —— Context 服务的 LLM 与 Embedding 设置。

模型选择以引用形式保存在 `model-bindings/`，按已认证用户和工作区隔离；每个新回合在服务端解析主聊天凭据，引用中不保存这些凭据。Advanced 中的应用专用连接通过 Engine 偏好 API 管理。每次启动托管 Context 服务时，PawApp 都会从 `config.json` 重新生成 `.env` 和 `models.json`。模型变更也会推送给运行中的 Context 服务；托管模式下修改 Neo4j 后，使用 **保存并重启 Context 服务** 生效。外部服务由部署维护者负责重启。

DataBridge 启用 **复用 QwenPaw 已配置的模型** 后，保存配置或启动托管 Context 服务会从宿主当前可用的激活模型刷新快照。Embedding 复用共享宿主服务商的地址和凭证，但保留所选的 Embedding 模型与维度。这些共享服务默认值与 **智能体配置 → Models** 中的每回合模型选择分别管理。

### 环境默认值与覆盖规则

首次初始化时，PawApp 从环境变量填充空缺的 DataBridge 字段；工作区模型在每个回合解析。保存配置后，`config.json` 是生成运行时文件和托管子进程环境的权威来源：Shell 或 QwenPaw 环境变量不会覆盖已保存值；清空受管字段后，下次启动不再带入旧值。保存配置、复用宿主模型及启动两个托管服务均不修改 QwenPaw 主进程环境。环境默认值只在首次初始化时导入，不会补回已清空的凭证。

托管子进程只继承基础操作系统变量，以及各服务在 [`backend/main.py`](backend/main.py) 中明确声明的变量。两个服务均声明了网络代理和证书配置；Context 另接收声明过的存储、数据管道和 Embedding 参数，Engine 另接收声明过的运行参数和 Docker 配置。其他全局变量不再自动透传，新增集成需明确声明所需变量；QwenPaw 全局环境变量管理本身保持原有行为。

请通过 **数据底座配置** 修改已保存值；直接编辑应用生成的 `.env` 会在下次保存或启动托管服务时被覆盖。外部 Context 服务的启动环境由该部署管理。两种模式下，SQL 数据源凭证都通过数据源注册表管理。

### 配置检查

配置完成后检查以下行为：

1. 保存 DataBridge 模型与 Neo4j 设置，检查 `config.json`、`.env` 中已填写的 Neo4j/模型变量，以及 `models.json` 中的 LLM/Embedding 设置。`.env` 不应被要求包含 SQL 数据源变量。
2. 启用宿主模型复用，切换到另一个兼容的宿主激活模型，然后保存配置或重启托管 Context 服务。确认模型快照刷新，且已保存的设置在重启后仍然存在。
3. 在数据源页面登记并测试 SQL 数据源。确认 Context 服务重启后注册信息仍然存在，再在 Data Console 中选择该数据源，对测试数据库执行一次只读查询。
4. 在 **智能体配置 → Models** 中确认 Analysis 继承主聊天模型、Summaries/DataBridge 继承分析模型。切换工作区默认模型后，新回合应使用新选择，已运行的回合保留原有模型。

旧用例中“保存 Neo4j/LLM 配置后，`.env` 同时生成 SQL 数据源变量”的预期不适用于当前配置契约。

## 运行时健康检查与本地服务

- 在主聊天配置模型凭据和工作区默认模型，在 **智能体配置 → Models** 查看实际使用的模型。独立的 **数据底座配置** 管理共享服务默认值。
- QwenPaw-Data 通过 PawApp 依赖契约声明 Context API、Graph Store 和已发现数据源。Data sources 页面会显示就绪状态、能力影响、修复建议和可用的实际操作。
- 本 app 不会调用 Docker 或供应 Graph Store / 数据源基础设施。这些资源是外部依赖，仅接受只读的就绪检查。本地生命周期和诊断属于 `qwenpaw-data-cli` 包；生产生命周期由部署的服务所有者负责。

分析模型未配置或不受支持时，提交回合前返回 HTTP 409。Context 服务不可用或缺少运行时模型绑定能力时返回 HTTP 503。应检查模型设置和服务状态，而不是将这些错误理解为数据库中没有数据。

本 app 还会选择加入 App 私有的依赖状态与生命周期工具。QwenPaw-Data 智能体可以检查与 UI 相同的控制平面，并仅请求已注册的操作；这些工具不会导出到 Main Chat。Host 仍负责能力治理与审计。

### 本地基础设施速查

服务端点由环境变量驱动，本地默认值仅作参考；没有硬编码。`qwenpaw-data-context` 在启动时解析它们（详见 QwenPaw-Data 工作区 `packages/qwenpaw-data-context/src/context_manager/config.py` 和 `packages/qwenpaw-data-context/README.md`）：

| 依赖 | 配置方式 | 本地默认值 |
| --- | --- | --- |
| Graph Store (Neo4j) | **数据底座配置**；外部部署管理 `NEO4J_URI`、`NEO4J_USER`、`NEO4J_PASSWORD`、`NEO4J_DATABASE` | `bolt://localhost:7687` |
| 数据源 (PostgreSQL / MySQL / ODPS / ...) | 通过 DataBridge 语义配置层注册 (`/api/semantic-config/datasource`)，不从 `.env` 读取 | 无 |
| DataBridge LLM / Embedding | **数据底座配置**；环境默认值使用 `OPENAI_API_KEY`、`OPENAI_BASE_URL`、`LLM_MODEL`、`EMBED_*` | — |
| 分析智能体模型 | Data Console 的 **智能体配置 → Models** | 主聊天工作区模型 |

本地生命周期，按所有者划分：

- **Graph Store (Neo4j)** —— 由 QwenPaw-Data 工作区工具拥有：`scripts/start_databridge.sh` 会复用 bolt 端口上已可达的 Neo4j，否则运行 `packages/qwenpaw-data-context/docker-compose.yml`。这要求运行中的 Docker daemon（例如 `colima start`）以及工作区 `.env` 中的 `NEO4J_PASSWORD`。
- **诊断** —— `qwenpaw-data doctor --json` 以只读方式报告 Docker、Neo4j、DataBridge API 和模型配置的就绪状态，并给出修复建议。
- **数据源服务器** —— 外部基础设施。QwenPaw Data 各包负责其注册和就绪检查，从不负责供应。

独立 CLI 默认检查 `127.0.0.1:8765`，托管应用使用动态私有端口；外部服务模式也可以使用 8765。CLI 默认地址检查失败，并不单独证明应用的 Context 服务不可用。应用状态可通过 `/api/qwenpaw-data/status` 查看。

## 各包职责

- `qwenpaw-data-context`：context API、语义配置和图记忆。同时拥有本地 Graph Store 定义 (`docker-compose.yml`) 和语义配置层中的数据源注册。
- `qwenpaw-data-host-core`：共享分析运行时和编排契约。不接触基础设施。
- `qwenpaw-data-skills`：app 提供的数据分析技能。
- `qwenpaw-data-cli`：独立生命周期和诊断工具（`doctor`、`datasource`、`semantic`）；是唯一被设计为拥有本地基础设施命令的 QwenPaw Data 包。数据源服务器本身仍属于外部基础设施。

托管模式下，用户只需启动 QwenPaw 这一个 UI / 后端入口。PawApp 生命周期会自动启动和停止 Context 服务及 `qwenpaw-data-host-core` 分析引擎。内嵌 Data Console 通过 PawApp 网关访问该引擎；`/data` 通过渠道桥接将 QwenPaw 渠道对话路由到同一引擎。

## 独立应用 1.0.3

本次发布基于稳定版 QwenPaw 2.2.2，配套 QwenPaw-Data 运行时 0.3.3。
Data 分析默认使用主聊天当前工作区的模型，摘要和 DataBridge 默认继承分析模型。
在 Data 的「设置 → 智能体配置 → Models」中选择覆盖；供应商凭据仍在主聊天中管理。
Embedding 与图索引属于共享数据服务，单独配置。
应用通过 Engine 原生 Console API 运行，并在稳定版平台上继承主聊天模型。声明的兼容范围为 `>=2.2.2,<2.2.3`。
发布顺序及边界见 [RELEASE.md](RELEASE.md)。
