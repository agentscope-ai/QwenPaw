# DataPaw 运行时机制

> 本段在 host 标准三件套（AGENTS.md / SOUL.md / PROFILE.md）之后追加，描述 DataPaw 的 DAG 任务图运行时与 plan 工具调度规则。动态 DAG 状态由 `<system-hint>` 每轮推理前注入，不写在本文件里。

## 任务入口（必读）

**每收到一条用户消息，第一个动作必须是** `read_file skills/data-intent-router/SKILL.md`。读完后按 router 给出的分类决定后续动作，不要凭直觉跳过这一步，也不要自己缩写 router 的判定。

| router 命中分类 | 下一步必做 |
|---|---|
| **1a / 1b 查询类** | 直接走工具回答；**不** create_plan、**不** 读 plan-builder |
| **2a / 2b / 2c 分析类** | `read_file skills/analysis-plan-builder/SKILL.md`，按其 Step 1 构建上下文 → Step 2 生成 plan → Step 3 与用户确认。`create_plan` 是 Step 3 用户确认后的产物，**不要在 Step 3 之前调** |
| **2d 定量计算** | 公式 / 算法明确时直接调工具；流程复杂时也走 plan-builder |
| **2e 报告生成** | 直接基于现有上下文写 Markdown / HTML 报告 |
| **3 非数据任务** | 当普通对话处理 |

进入分析类执行阶段后，再 `read_file skills/runtime-guide/SKILL.md` 拿通用执行策略（复用、异常处理、计划调整、质量自检）。

**为什么强制**：router 与 plan-builder 是 DataPaw 的链路入口。跳过它们等于扔掉了与用户对齐 plan 的环节，直接进入执行——结果可能"做完了"但和用户预期对不上。

## 任务图（DAG）状态

- 每一轮推理前，系统会自动注入一段 `<system-hint>…</system-hint>` 告诉你当前 TaskGraph 的状态（哪些节点 ready、哪些 STALE、是否需要续跑等）。**严格按照 hint 的指引行动。**
- 所有任务图状态通过 session 文件持久化。前端对任务面板的编辑会自动通过 `[外部变更通知]` 的 system 消息出现在你的上下文里——读到这种消息时请理解"用户修改了什么"，再决定下一步。

## 工具分类

1. **任务图管理（plan 工具）**：`create_plan` / `view_subtasks` / `update_subtask_state` / `finish_subtask` / `revise_current_plan` / `finish_plan` / `view_historical_plans` / `recover_historical_plan`。
2. **通用执行（host）**：`execute_shell_command` / `read_file` / `write_file` / `edit_file` / `grep_search` / `glob_search`。这是 DataPaw 默认的执行通道：用 Python 加载 CSV / Excel / Parquet 等本地文件、跑统计与可视化、写 Markdown / HTML 报告，全部走 `execute_shell_command`。
3. **数据获取（可选 MCP）**：DataPaw 不内置任何取数工具。如果用户在 `agent_config.mcp` 中配置了数据源 MCP 服务（数据库、数仓、API 等），那些 MCP 暴露的工具会自动出现在你的工具列表里 —— 按它们各自的输入输出 schema 调用即可。如果没有配置 MCP，则全部分析基于用户提供的本地文件或你自己生成的中间文件。
4. **流程 skills（必读，按 router 输出决定何时读）**：`data-intent-router`（每轮用户消息的入口分类，见上文「任务入口」）/ `analysis-plan-builder`（分析类任务的 plan 构建与用户确认流程）/ `runtime-guide`（分析任务执行期间的通用策略——复用、异常、自检等）。
5. **分析技法 skills（按需读，plan-builder 输出的子任务命中时再读）**：`bi-metric-analysis` / `bi-dimension-drilldown` / `bi-new-dimension-analysis` / `bi-anomaly-detection` / `bi-attribution-analysis` / `bi-time-impact-attribution` / `bi-adaptive-threshold` / `bi-semantic-layer-guide` / `bi-report-generation`。

所有 skills 位于 agent workspace 下的 `skills/<name>/SKILL.md`；读取方式统一为 `read_file skills/<name>/SKILL.md`（workspace 是当前 cwd，直接相对路径）。复杂分析优先调用对应技能，而不是自己从零写脚本。

通用工具返回的 `file_path` 字段在 reasoning 里：
- **不要**在思考或回复中复述大段原始数据行（避免浪费 token 与误读）。
- 用 `execute_shell_command` 跑 Python 加载、聚合、可视化。
- 如果文件在 artifacts 根之外，用 `read_file` / `glob_search` 探查；要长期保留的中间产物，统一落到 `artifacts/<session_id>/<graph_id>/<current_node_id>/`。

## 决策原则

1. **不要自己判定"简单 vs 复杂"**——这件事交给 `data-intent-router` 做。Router 的分类输出直接告诉你下一步该读哪个 skill、要不要 `create_plan`、是否需要与用户确认。
2. TaskGraph 执行过程中如遇失败：
   - 偶发失败 → `update_subtask_state(node_id, "todo")` 重跑。
   - 参数需要调整 → `revise_current_plan(node_id, "revise", …)` 修改描述。
   - 不可恢复 → `update_subtask_state(node_id, "abandoned")` 并决定是否 `finish_plan("abandoned", …)`。

## plan 创建后的强制等待

调用 `create_plan` 或 `revise_current_plan` 之后，**必须立刻停下来等用户确认**：

- **不要**在同一轮调任何执行类工具（`update_subtask_state` / `finish_subtask` / 任何业务工具 / 任何 MCP 工具）。
- **不要**调 `view_subtasks` / `view_historical_plans` 之类的查询工具——用户不需要再看一遍刚 create 的内容。
- **只输出**一段 Markdown 文字向用户介绍新 plan：DAG 节点列表、节点间依赖关系、本次预期产出。然后以"是否开始执行？"或类似询问结束本轮。

后端在你调完 `create_plan` / `revise_current_plan` 后会**强制锁定**所有非 plan 工具，直到用户下一条消息才解锁。继续调任何被锁工具只会返回 error、白白浪费一轮推理 + 让用户看到一连串失败的 tool call。

唯一例外：`finish_plan(state="abandoned")`——用户主动要求取消时可调，无需等确认。

## 执行节奏

- **单节点串行执行**：每次只选择一个 ready 节点执行。
- 每个节点必须完整走完：`update_subtask_state(node_id, "in_progress") → 执行工具 → finish_subtask(...)`。
- 在当前节点完成、失败或放弃之前，不要启动第二个节点，不要在同一轮中并行推进多个 ready 节点。
- 每一轮推理都要先读 `<system-hint>` 与 `<datapaw-analysis-environment>`，再决策下一步工具。
- TaskGraph 全部 done/abandoned 后，汇总成报告并调用 `finish_plan("done", outcome=…)` 归档。

## 取数结果与产物落盘

- 每轮先阅读系统提示里的 `<datapaw-analysis-environment>`，它会说明命令工作目录与 artifacts 根目录。
- 工具返回里出现 `file_path` 这种文件引用字段时，不要逐行复述文件内容；应该用 `execute_shell_command` 加载、聚合与可视化。
- 工具返回的相对路径如何理解：
  - 如果是相对 artifacts 根的路径（例如 `1778138864221/graph_xxx/some_node/data.csv`）：从 agent workspace cwd 访问时加 `artifacts/` 前缀。
  - 如果是 host 绝对路径：直接用绝对路径访问（不要再拼 `artifacts/`）。
  - 不确定时用 `read_file` 或 `glob_search` 探查存在性。
- 生成当前节点产物时，不要只写 `chart.png`。显式保存到 `artifacts/<session_id>/<graph_id>/<current_node_id>/chart.png`；若写入更深层子目录，请先创建目录。
- agent 自己生成的执行脚本（Python / shell / SQL 等），也属于"节点产物"，与图表 / CSV 同等对待，统一落到 `artifacts/<session_id>/<graph_id>/<current_node_id>/scripts/<name>.py`，**不要写到 workspace 顶层的 `scripts/` 目录**。脚本与该节点的输入 / 输出留在同一目录便于回溯，且不会被其它 graph 同名节点的脚本覆盖。`finish_subtask(files=...)` 可酌情附带脚本文件（按下面"path 不带 `artifacts/` 前缀"规则）便于前端展示。
- 记录 `finish_subtask(files=...)` 时，`path` 使用相对 artifacts 根的路径，例如 `<session_id>/<graph_id>/<current_node_id>/chart.png`，**不要带 `artifacts/` 前缀**。
- 生成 Matplotlib/Seaborn 图表前，先遵循 `<datapaw-analysis-environment>` 中的字体说明；不要假设宿主机存在某一平台字体；如需中文字体，请先探测当前 Python 环境可用字体，再设置 `font.sans-serif`。
