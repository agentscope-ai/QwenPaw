<p align="center">
  <img src="logo.png" alt="DataPaw" width="320">
</p>

<p align="center">
  <strong>QwenPaw 数据分析插件</strong>
</p>

<p align="center">
  <a href="#"><img src="https://img.shields.io/badge/License-Apache%202.0-blue.svg" alt="License" /></a>
  <a href="https://www.python.org/downloads/"><img src="https://img.shields.io/badge/Python-3.10%2B-blue.svg" alt="Python" /></a>
  <a href="#"><img src="https://img.shields.io/badge/version-0.1.0-green.svg" alt="Version" /></a>
</p>

<p align="center">
  <a href="README.md">English</a> | <b>中文</b> | <a href="README_ja.md">日本語</a> | <a href="README_ru.md">Русский</a>
</p>

---

DataPaw 是 QwenPaw 的数据分析插件。它内置 **12 个 BI 风格的 agent 技能**——异常检测、维度下钻、归因分析、时间因素分解、自适应阈值、HTML 报告生成、以及把这些串起来的规划 / 路由 skill——让 agent 能端到端地把一个 BI 问题做完：加载 → 清洗 → 分析 → 下钻 → 出报告。

适合这几类场景：

- **多步 BI 分析** —— agent 自动为每一步挑合适的 skill，最后给一份结构化报告。
- **指标异动归因** —— 指标波动时自适应阈值 → 异常检测 → 时间因素分解 → 维度下钻自动跑完，最终落到 HTML 报告。
- **本地文件工作流** —— 在聊天里上传 CSV / Excel / Parquet，或贴绝对路径，或把文件丢到 agent workspace；分析全程走 `execute_shell_command`。

底层每一次多步分析都组织成一张 **DAG 任务图**：每一步是一个命名节点，agent 串行推进，进度持久化到 session 所以可暂停可续跑。DAG 状态通过 SSE 可观测、通过 REST API 可编辑。配套的**任务面板前端**（DAG 可视化 + 节点编辑 UI）正在作为本插件的一部分开发中——见下方 [前端 roadmap](#前端-roadmap)。

DataPaw 完全在你的本地环境运行，数据不出域。

## 快速开始

### 前置要求

| 项 | 要求 |
|---|---|
| **QwenPaw 版本** | **≥ v1.1.7** |
| **Python** | 3.10 ~ 3.13 |
| **LLM 模型** | 已在 QwenPaw 中配置（DataPaw 直接继承活跃模型） |

> QwenPaw 版本低于 v1.1.7，请先升级：`pip install --upgrade "qwenpaw>=1.1.7"`。

### 1. 安装 DataPaw 插件

**通过 Console（推荐）：**

1. 启动 QwenPaw（`qwenpaw app`），打开 http://127.0.0.1:8088/。
2. 在左侧 Settings 下点击「Plugin Manager」，再点「Install Plugin」。
3. 把 `datapaw/` 目录拖进安装对话框，或选 ZIP 文件（DataPaw 已内置在 QwenPaw 的 `plugins/bundle/datapaw/`）。
4. 等安装完成。

**通过 CLI：**

```bash
qwenpaw plugin install /path/to/datapaw
```

> 装完之后**强制刷新浏览器**（`Cmd+Shift+R` / `Ctrl+Shift+R`），让 agent 下拉里出现新的「DataPaw」选项。

### 2. 完成必要配置

#### LLM 模型

在 console「Settings → Models」配置一个 LLM provider 和 API key。DataPaw 不需要单独配置模型，直接继承你当前的活跃模型。详见 [QwenPaw Models 文档](https://qwenpaw.agentscope.io/docs/models)。

#### 把数据交给 agent

DataPaw 不内置任何取数工具。把数据交给 agent 有三种方式，按便利程度排序：

- **聊天里上传文件** —— console 的文件上传会把文件放到 agent workspace 的 `media/` / `file_store/` 下，agent 可以直接读。
- **在消息里贴绝对路径** —— 例如 `/Users/me/Downloads/data.csv`，agent 用 `read_file` / `execute_shell_command` 直接打开。
- **把文件放进 workspace** —— 把 CSV / Excel / Parquet 拷到 `~/.qwenpaw/workspaces/datapaw/` 下，按相对路径引用。

分析过程中的中间产物、图表、报告统一落到 `~/.qwenpaw/workspaces/datapaw/artifacts/<session_id>/<graph_id>/<node_id>/` 下，详见下方 [产物路径](#产物路径) 一节。

### 3. 开始使用

在聊天页面 agent 下拉里选 **DataPaw**，发个需求试试：

```
分析产品 X 25 年 12 月的日访问趋势，输出 HTML 报告。
```

预期能看到：

- agent 调 `analysis-plan-builder` 出分析计划。
- agent 按 DAG 一个节点一个节点推进，每个节点 `pending → ready → in_progress → done`。
- 末尾节点调 `bi-report-generation`，在 artifacts 根目录下生成 HTML 文件。

## 内置 Skills

DataPaw 的核心价值在它内置的这 12 个 skill 上。装上即用，启动时自动安装到 agent workspace 并启用。

### 流程类（把分析串起来）

| Skill | agent 何时调 |
|---|---|
| `data-intent-router` | 每收到一条用户消息，第一件事就是读它分类，路由到对应处理链路。 |
| `analysis-plan-builder` | 把开放性的分析需求转成可确认的结构化计划。 |
| `runtime-guide` | 执行期的通用约定：复用、异常处理、计划调整、自检。 |

### 分析类

| Skill | 做什么 |
|---|---|
| `bi-metric-analysis` | 单指标 / 单 scope 的端到端流水线：指标观测 + 异常检测 + 维度下钻。 |
| `bi-anomaly-detection` | 基于阈值检测时间序列中的显著异常波动点。 |
| `bi-adaptive-threshold` | 从数据自然波动幅度反推异常 / 影响度阈值，避免硬编码。 |
| `bi-attribution-analysis` | 各维度（组）值对指标变动的贡献度，支持可加型和加权平均型指标。 |
| `bi-dimension-drilldown` | 按维度逐层下钻，定位驱动指标变动的关键维度（组）值。 |
| `bi-time-impact-attribution` | 把周期波动拆解为结构变动 / 趋势变动 / 事件影响。 |
| `bi-new-dimension-analysis` | 识别本期新出现的维度值（新渠道 / 新品类 / 新功能），评估其影响。 |
| `bi-semantic-layer-guide` | 通过语义层查询、验证和消歧指标与维度时的约定；有语义层时使用。 |

### 报告类

| Skill | 做什么 |
|---|---|
| `bi-report-generation` | 把分析结论和产物组织成读者友好的 HTML 报告。 |

每个 skill 都带 `SKILL.md`（模型卡片）和必要的脚本 / 参考文档，放在 `skills/<name>/` 下。agent 会在需要时自己读 SKILL.md，使用者无需手动操作。

## 使用示例

**日趋势分析 + HTML 报告**

> 分析产品 X 25 年 12 月的日访问趋势，做异常检测，归因下跌原因，输出 HTML 报告。

DataPaw 会先用 `analysis-plan-builder` 规划 DAG，按依赖顺序串联 `bi-anomaly-detection` → `bi-attribution-analysis` → `bi-report-generation`，最后在 artifacts 根目录下出 `report.html`。

**一次性的简单查询**

> `sessions.csv` 里 session 时长的中位数是多少？

足够简单的问题 DataPaw 会跳过 `create_plan`，直接 `execute_shell_command` 算完返回。

## 前端 roadmap

本次发布只包含 DataPaw 插件的 **backend**：agent、skills、DAG 任务图、REST API、SSE 事件流。

**DataPaw 前端**——DAG 可视化、点节点直接编辑、面板内文件预览、fetch_data 结果渲染——作为本插件的一部分正在开发中，会在 `plugins/bundle/datapaw/` 后续版本里随 backend 一起发布。

在前端落地之前，你可以纯粹通过聊天 agent 使用 DataPaw；DAG 状态和产物都可以通过下面的 SSE 事件流和 REST 接口观测。

## 任务图与 API

每一次多步分析都组织成 DAG、持久化到 session，并通过 REST + SSE 暴露。

### REST 接口（挂在 `/api/tasks/...` 下）

| Method | Path | 用途 |
|---|---|---|
| `GET`  | `/{session_id}` | 当前 DAG + 历史图概要 + artifacts 概要 |
| `GET`  | `/{session_id}/dag` | 当前活跃图完整 DAG |
| `GET`  | `/{session_id}/sop` | 当前图 → YAML |
| `PUT`  | `/{session_id}/sop` | 上传新 SOP YAML（向 agent 排队一条 `[sop_replaced]` 通知） |
| `PUT`  | `/{session_id}/dag` | 局部修订 DAG（排队 `[dag_merged]` 通知） |
| `GET`  | `/{session_id}/history/{plan_id}` | 查询历史图 |
| `GET`  | `/{session_id}/files{,/preview,/download}` | 列出 / 预览 / 下载产物 |

所有写接口经 `_check_not_running` 阻断与运行中 agent 的并发写。Schema 见 `core/routers/tasks.py`。

## 架构

DataPaw 通过 QwenPaw 原生 plugin 系统接入，不修改任何 host 源码，所有扩展在启动时挂上。

```
plugins/bundle/datapaw/
├── plugin.json                # plugin manifest
├── plugin.py                  # 入口：注册 startup / shutdown hook
├── constants.py               # 常量 + sys.path 引导
├── agents_setup.py            # 启动时写内置 agent profile + workspace + skills
├── hooks.py                   # 运行时 patch：smart agent factory、channel SSE、unload 清理
├── prompts/MASTER.md          # 运行时机制段（DAG / plan 工具 / 产物落盘规则）
├── agents/datapaw/{zh,en}/    # 中英文 SOUL.md + PROFILE.md
├── skills/                    # 12 个内置 BI 技能
└── core/                      # 核心实现
    ├── agents/base.py         # DataPawAgent（继承 QwenPawAgent）
    ├── orchestration/         # TaskGraph / RuntimeStateManager / hint / events
    ├── routers/tasks.py       # /api/tasks/* 路由
    └── path_context.py        # 沙箱视角 ↔ host 路径翻译
```

系统提示词分三层装配：

1. host 标准 `AGENTS.md` / `SOUL.md` / `PROFILE.md`（host 的 per-agent prompt 规范）。
2. plugin 的 `MASTER.md` —— DAG 运行时规则与 plan 工具说明，追加在 host 三件套之后。
3. 动态的 `<datapaw-analysis-environment>` 段，注入当前请求的 workspace 路径、artifacts 根目录、执行规范。

## 产物路径

所有分析产物落到 agent workspace 下，按 session / graph / node 三层切分：

```
~/.qwenpaw/workspaces/datapaw/artifacts/
└── <session_id>/
    └── <graph_id>/
        └── <node_id>/
            ├── data.csv
            ├── chart.png
            └── report.html
```

调 `finish_subtask(files=...)` 时填的是相对路径（不带 `artifacts/` 前缀），运行时通过 `PathContext.resolve_artifact_path` 解析回 host 绝对路径。

## 致谢

- 基于 [QwenPaw](https://github.com/agentscope-ai/QwenPaw) 与 [agentscope](https://github.com/modelscope/agentscope) 构建。
