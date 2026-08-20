# datapaw

**企业级自进化、图驱动的 Agentic BI**

源码：[QwenPaw-Data](https://github.com/agentscope-ai/QwenPaw-Data)

[English README](./README.md)

datapaw 是一个原生 QwenPaw 应用。其前端挂载在 `/apps/datapaw`，后端注册在 `/api/datapaw`，context service 由后端私有管理。

## 运行时形态

```text
QwenPaw-Data UI
  -> app-scoped PawApp SDK
  -> /api/datapaw/*
  -> QwenPaw-Data PawApp backend
  -> dependency status and typed lifecycle control
  -> managed QwenPaw-Data context service
```

浏览器不感知服务端口或 bearer token，也不调用旧的 plugin 全局对象、固定端口或第二个请求客户端。QwenPaw-Data 显式启用 PawApp 标准能力；未选择加入的现有 PawApp 不会获得额外的 chat、storage、toast 或 notify 路由。

## datapaw 是什么？

datapaw 是 [QwenPaw-Data](https://github.com/agentscope-ai/QwenPaw-Data) 在 QwenPaw 中的原生入口。它将自主、图驱动的数据分析能力引入 QwenPaw 工作区，让用户可以用自然语言提出业务问题，并获得可追溯、富含工件、由真实企业数据支撑的答案。

## 界面截图

<p align="center">
  <img src="assets/screenshots/cm-graph.png" alt="元数据图谱可视化" width="900" />
  <br/>
  <em>元数据图谱：语义模型、维度、指标与血缘关系</em>
</p>

<p align="center">
  <img src="assets/screenshots/analysis-result.png" alt="端到端分析结果" width="900" />
  <br/>
  <em>端到端分析：自然语言提问 → 受控 SQL → 可追溯答案</em>
</p>

## 核心理念

企业数据分析是开放式、充满歧义且持续演进的。一个可用的数据智能体必须在每次任务中回答三个问题：

- **用什么事实**：业务概念、指标、维度、表、血缘和历史上下文。
- **如何分析**：可复用的分析方法论，而不是每次请求都临时推理。
- **如何运行**：可控的长周期、以工件为中心的 workflow 运行时。

datapaw 通过三层协作架构实现这一目标：

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

## 快速开始（推荐：PyPI）

无需 `QwenPaw-Data` 源码工作区，最快的运行方式是将运行时包从 PyPI 安装到与 QwenPaw 相同的 Python 环境中。

```bash
pip install qwenpaw[datapaw]
```

如果你想锁定兼容版本，也可以使用便捷脚本：

```bash
./plugins/apps/datapaw/scripts/setup-pypi.sh
```

然后启动 QwenPaw 并启用 datapaw app。PawApp 生命周期会自动检测 PyPI 包，并在动态回环端口上启动托管 context service。

```bash
qwenpaw app
```

> 该路径推荐给只需要 datapaw app、已有自己的 Neo4j / PostgreSQL 基础设施，或想在没有 demo 数据的情况下试用 app 的用户。

### PyPI + docker-compose 演示数据

如果你还需要 bundled GAAP 演示数据（Neo4j 图 + PostgreSQL 数据源），先启动基础设施容器，再以 external context mode 运行 QwenPaw：

```bash
cd plugins/apps/datapaw
cp .env.example .env
docker compose up -d neo4j postgres context seed

# 在另一个终端
DATAPAW_CONTEXT_MODE=external \
DATAPAW_CONTEXT_URL=http://127.0.0.1:8765 \
DATAPAW_CONTEXT_TOKEN=datapaw-demo-token \
qwenpaw app
```

这是**推荐的一键演示路径**：无需在 Docker 内编译 QwenPaw，即可获得完整播种的图和数据源。

## 本地包开发环境

源码工作区默认位于 `~/dev/QwenPaw-Data`。其隔离的 `.venv` 中包含 `datapaw-context`、`datapaw-host-core`、`datapaw-cli` 和 `datapaw-skills` 的可编辑安装，因此它们的依赖版本不会影响 QwenPaw 环境。

```bash
./scripts/setup-dev.sh
cd ui && npm install && npm run build
```

UI 以浏览器原生 ES module 形式交付。其 Vite 配置在构建时替换 `process.env.NODE_ENV`，因此打包后的依赖不会把 Node 专属的 `process` 全局变量泄漏到 QwenPaw Console 中。

`setup-dev.sh` 会同步 QwenPaw-Data 工作区并在本 app 下创建被忽略的 development links。如需使用其他 checkout，请设置 `DATAPAW_SOURCE_DIR`。运行时仅当另一个进程管理器拥有该服务时，才使用 `DATAPAW_CONTEXT_MODE=external` 并配置 `DATAPAW_CONTEXT_URL` 和 `DATAPAW_CONTEXT_TOKEN`。

如需一步完成构建、暂存并安装到本地 QwenPaw 实例，运行 `./scripts/dev.sh`。`QWENPAW_BIN` 和 `QWENPAW_WORKING_DIR` 用于选择目标实例。安装程序默认指向 `127.0.0.1:8089`；需要时可通过 `QWENPAW_HOST` 和 `QWENPAW_PORT` 覆盖。

## Docker compose 一键演示

如果你希望在没有本地 `QwenPaw-Data` 源码工作区的情况下，一键启动 Neo4j + PostgreSQL + 已播种 GAAP 数据，可以使用以下 stack。该 stack 使用 PyPI 上的 `datapaw-context` 和 `datapaw-cli` 包。

```bash
cd plugins/apps/datapaw
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
DATAPAW_CONTEXT_MODE=external DATAPAW_CONTEXT_URL=http://127.0.0.1:8765 DATAPAW_CONTEXT_TOKEN=datapaw-demo-token qwenpaw app
```

如需手动重新运行 seed 容器（例如在清空 Postgres 卷后）：

```bash
./scripts/init-demo.sh
```

## 运行时健康检查与本地服务

- 在使用 Analysis chat 之前，请在 QwenPaw 的 **Settings → Models** 中配置并激活一个语言模型。全新的 `QWENPAW_WORKING_DIR` 故意不包含任何 provider 凭据或激活模型。
- QwenPaw-Data 通过 PawApp 依赖契约声明 Context API、Graph Store 和已发现数据源。Data sources 页面会显示就绪状态、能力影响、修复建议和可用的实际操作。
- 本 app 不会调用 Docker 或供应 Graph Store / 数据源基础设施。这些资源是外部依赖，仅接受只读的就绪检查。本地生命周期和诊断属于 `datapaw-cli` 包；生产生命周期由部署的服务所有者负责。

缺失的 host 配置会通过 PawApp SDK 以结构化的 service-unavailable 错误上报。QwenPaw-Data 将 `MODEL_NOT_CONFIGURED` 转换为可操作的 UI 消息，而不是显示通用 HTTP 500。

本 app 还会选择加入通用的 `datapaw_dependency_status` 和 `datapaw_dependency_action` 工具。智能体可以检查与 UI 相同的控制平面，并仅请求已注册的操作；host 仍负责工具治理与审计。

### 本地基础设施速查

服务端点由环境变量驱动，本地默认值仅作参考；没有硬编码。`datapaw-context` 在启动时解析它们（详见 QwenPaw-Data 工作区 `packages/datapaw-context/src/context_manager/config.py` 和 `packages/datapaw-context/README.md`）：

| 依赖 | 配置方式 | 本地默认值 |
| --- | --- | --- |
| Graph Store (Neo4j) | 工作区 `.env` 中的 `NEO4J_URI`、`NEO4J_USER`、`NEO4J_PASSWORD`、`NEO4J_DATABASE` | `bolt://localhost:7687` |
| 数据源 (PostgreSQL / MySQL / ODPS / ...) | 通过 DataBridge 语义配置层注册 (`/api/semantic-config/datasource`)，不从 `.env` 读取 | 无 |
| LLM / Embedding | `OPENAI_API_KEY`、`OPENAI_BASE_URL`、`LLM_MODEL`、`EMBED_*` | — |

本地生命周期，按所有者划分：

- **Graph Store (Neo4j)** —— 由 QwenPaw-Data 工作区工具拥有：`scripts/start_databridge.sh` 会复用 bolt 端口上已可达的 Neo4j，否则运行 `packages/datapaw-context/docker-compose.yml`。这要求运行中的 Docker daemon（例如 `colima start`）以及工作区 `.env` 中的 `NEO4J_PASSWORD`。
- **诊断** —— `datapaw doctor --json` 以只读方式报告 Docker、Neo4j、DataBridge API 和模型配置的就绪状态，并给出修复建议。
- **数据源服务器** —— 外部基础设施。DataPaw 各包负责其注册和就绪检查，从不负责供应。

独立的 DataBridge API (`127.0.0.1:8765`) 仅在 QwenPaw 外运行 QwenPaw-Data 时使用。在 QwenPaw 内部，PawApp 生命周期会在动态回环端口上管理私有 context service，因此单独的 `doctor` 8765 失败不会影响本 app。

## 各包职责

- `datapaw-context`：context API、语义配置和图记忆。同时拥有本地 Graph Store 定义 (`docker-compose.yml`) 和语义配置层中的数据源注册。
- `datapaw-host-core`：共享分析运行时和编排契约。不接触基础设施。
- `datapaw-skills`：app 提供的数据分析技能。
- `datapaw-cli`：独立生命周期和诊断工具（`doctor`、`datasource`、`semantic`）；是唯一被设计为拥有本地基础设施命令的 DataPaw 包。数据源服务器本身仍属于外部基础设施。

QwenPaw 仍是用户唯一需要启动的 UI / 后端进程。在 managed mode 下，PawApp 生命周期会自动启动和停止 context service。

第一阶段迁移使用 QwenPaw 的 app-scoped chat 配合 QwenPaw-Data context 工具，不会从 `datapaw-host-core` 启动第二个智能体。host-core 的任务图、工件和工具渲染适配器将在 chat 集成稳定后加入。
