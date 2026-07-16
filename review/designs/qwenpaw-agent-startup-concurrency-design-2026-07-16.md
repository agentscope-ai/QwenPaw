# QwenPaw 多 Agent 启动并发与状态展示设计

**日期**：2026-07-16

**实现基线**：`upstream/main`，commit `166ea7a2`

**阶段**：方案已确认并完成实现

**目标**：降低多 Agent 同时初始化 ReMe 时的内存和 CPU 峰值，让控制台能区分“已启用”和“已经启动完成”，并允许在 AgentSelector 中查看和启停 disabled Agent。
**关联 Issue**：[#6144 — Bound concurrent ReMe initialization during multi-agent startup](https://github.com/agentscope-ai/QwenPaw/issues/6144)

## 一、结论

建议把当前“所有 enabled Agent 一次性 `asyncio.gather()`”调整为两阶段启动：

```text
default ─┐
         ├── 并发启动并等待二者完成 ──> 输出 Ready banner
内置 QA ─┘
                                      ↓
custom enabled Agent（有界并发 + 终端进度条）
```

推荐新增环境变量：

```bash
QWENPAW_CUSTOM_AGENT_STARTUP_CONCURRENCY=2
```

- 只限制第二阶段 custom Agent 的并发初始化数。
- `default` 和内置 QA 并发启动，不占用 custom Agent 的并发额度。
- 默认值建议为 `2`：既能显著降低多个 ReMe 同时建索引的峰值，又不会把大量 Agent 完全串行化。
- `1` 表示 custom Agent 串行启动；大于 custom Agent 数量时等价于全部并发。
- 非法字符串回退到 `2`；小于 `1` 的整数按 `1` 处理。
- 复用现有 `EnvVarLoader`，因此旧前缀 `COPAW_CUSTOM_AGENT_STARTUP_CONCURRENCY` 自动兼容，无需额外分支。

第一阶段完成后立即复用现有 Rich banner 输出核心 Agent 的就绪耗时；第二阶段使用 Rich 单进度条展示 custom Agent 的完成数量，不新增 `tqdm` 依赖。

同时为 Agent 列表 API 增加独立的运行时字段 `startup_status`。`enabled` 仍只表示配置开关，不能被运行时状态替代。

## 二、现状与问题边界

### 2.1 当前启动路径

`src/qwenpaw/app/_app.py` 会先开放 HTTP 服务，再在 `_background_startup()` 中调用：

```python
await workspace_registry.start_all_configured_agents()
```

`src/qwenpaw/app/multi_agent_manager.py` 随后为全部 enabled Agent 创建协程并一次性 `gather()`。`get_agent()` 在耗时的 `Workspace.start()` 期间不会持有全局锁，因此 Agent 数量就是实际初始化并发数。

这意味着 10 个 enabled Agent 可以同时初始化各自的 ReMe、Channel、模型相关资源，启动峰值不受控制。

### 2.2 已确认的 QA 标识

不能硬编码字符串 `qa`。当前内置 QA 的 ID 来自：

```python
BUILTIN_QA_AGENT_ID = "QwenPaw_QA_Agent_0.2"
```

实现时应导入并使用 `BUILTIN_QA_AGENT_ID`。只有该配置存在且为 enabled 时才进入 QA 优先阶段；不存在或 disabled 时直接跳过。

### 2.3 本次不扩大处理的范围

- 不改变单个 Workspace/ReMe 的初始化逻辑。
- 不改变热重载的零停机流程。
- 不限制运行期由不同请求触发的多个 lazy `get_agent()`；环境变量只控制服务启动批次。
- 不把手动 enable API 改成异步任务。当前 enable 请求仍等待 Agent 启动成功或失败后返回，避免改变 API 错误语义。
- 不引入任务队列、新的第三方依赖或新的持久化表；终端进度复用项目已有的 Rich。

最后两点是为了保持最小改动。如果后续确认运行期 lazy start 也会形成明显峰值，可以在独立改动中把同一个 semaphore 下沉到 `get_agent()`，不建议和本次启动顺序调整绑在一起。

## 三、启动流程设计

### 3.1 优先级与失败隔离

推荐固定阶段：

1. 为 `default` 和 enabled 的 `BUILTIN_QA_AGENT_ID` 同时创建启动协程，并用一次 `asyncio.gather()` 等待两者结束。
2. 第一阶段结束后输出 Ready banner。
3. 启动其余 custom enabled Agent，每个启动操作先获取并发 semaphore，并在每个任务结束时推进终端进度。

这样可以确保：

- default 和 QA 以最短墙钟时间完成核心初始化。
- custom Agent 不会与两个核心 Agent 的 ReMe 初始化重叠。
- banner 明确表示核心 Agent 已完成启动，随后可继续观察 custom Agent 进度。

单个 Agent 启动失败不应让 `gather()` 提前取消同阶段的其他任务。沿用当前 `start_single_agent()` 的失败隔离语义，最终结果仍为 `dict[str, bool]`。

核心阶段以 `default` 成功作为最低 Ready 条件：

- `default` 成功且 QA 成功、失败、disabled 或不存在：可以输出 Ready banner，并继续 custom Agent。
- `default` 失败：不输出带有 `Status: Ready` 的 banner，但仍记录失败并继续尝试其他 Agent，便于保留诊断能力。

### 3.2 最小实现形态

保留现有 `start_single_agent()`，只重组调度方式：

```python
priority_results = await asyncio.gather(
    *(start_single_agent(agent_id) for agent_id in priority_agent_ids),
)

print_core_ready_banner_if_default_started(priority_results)

semaphore = asyncio.Semaphore(custom_startup_concurrency)

async def start_bounded(agent_id):
    async with semaphore:
        return await start_single_agent(agent_id)

custom_results = await asyncio.gather(
    *(start_bounded(agent_id) for agent_id in custom_agent_ids),
)
```

上面的 banner 调用只是流程示意。为避免 manager 读取 API 地址或应用状态，建议给现有 `start_all_configured_agents()` 增加一个可选的同步 `on_core_ready(core_results)` 回调。`_app.py` 传入回调并负责打印 banner、设置核心 Ready 事件；不传回调的既有调用仍可正常工作。

不建议先实现固定 worker pool。semaphore 已能约束真正进入 `get_agent()` 的初始化数量，改动更小；其余等待协程只保留少量 Python 状态，不会创建 Workspace 或 ReMe。

### 3.3 配置读取

在 `multi_agent_manager.py` 使用现有工具读取：

```python
EnvVarLoader.get_int(
    "QWENPAW_CUSTOM_AGENT_STARTUP_CONCURRENCY",
    default=2,
    min_value=1,
)
```

不新增 TOML 配置字段，避免配置模型、迁移和控制台设置页的连锁修改。该值每次执行 `start_all_configured_agents()` 时读取，测试可以直接通过 `monkeypatch.setenv()` 覆盖。

### 3.4 Ready banner 与 custom Agent 进度

现有 `print_ready_banner()` 已经使用 Rich，可直接生成用户期望的 rounded panel：

```text
╭──────────────────────────────────────╮
│                                      │
│  ✓ QwenPaw                           │
│  ├── Status:  Ready                  │
│  ├── Address: http://127.0.0.1:8088  │
│  └── Startup: 10.336s                │
│                                      │
╰──────────────────────────────────────╯
```

`Startup` 改为从进程启动到 default 与 QA 启动阶段结束的耗时，不再等待 custom Agent、剩余插件和非关键后台任务。原先后台流程末尾的 banner 必须移除，避免重复输出。

banner 后为 custom Agent 创建一个 Rich `Progress`，建议只显示一条总进度，避免 Agent 较多时刷满终端：

```text
Starting custom agents ━━━━━━━━━━━━━━━━ 6/10 60% current: research
```

进度规则：

- 总数是除 `default` 和 `BUILTIN_QA_AGENT_ID` 外的 enabled Agent 数量。
- 每个 Agent 进入终态（成功或失败）都推进一次，保证失败时进度条仍可结束。
- 成功数和失败数继续通过最终日志输出，进度条只表达“已处理数量”。
- 没有 custom Agent 时不创建空进度条。
- 仅交互式终端动态刷新；非 TTY 环境保留普通日志，避免 CI、systemd 和容器日志产生控制字符。
- 复用同一个 Rich `Console`，不增加 `tqdm` 依赖；Windows 输出异常沿用现有安全降级策略。

职责上，`startup_display.py` 提供一个很小的 custom Agent 进度上下文，manager 因为掌握任务总数和完成时机而负责调用它；banner 仍由 `_app.py` 通过核心完成回调触发。这样不需要把 API 地址或 FastAPI app state 传入 manager。

### 3.5 Ready 语义

Ready banner 表示 default 已经可用且 QA 的本轮启动已经结束，custom Agent 仍可在后台启动。`app.state.startup_ready` 和 `/healthz` 建议同步调整为这个核心就绪点，否则终端显示 Ready 而健康检查仍为 503，语义不一致。

这会把 `/healthz` 从“全部后台初始化完成”调整为“核心 Agent 可服务”。custom Agent 的实时状态通过 `GET /agents` 暴露；请求尚未完成启动的 custom Agent 时，继续沿用 `get_agent()` 的等待机制。

## 四、Agent 运行时状态设计

### 4.1 状态模型

新增 `startup_status`，建议使用以下五个稳定字符串：

| 状态 | 含义 | 控制台展示 |
| --- | --- | --- |
| `disabled` | 配置为 disabled | 灰色静态状态指示灯 |
| `pending` | enabled，已进入启动批次但仍在等待优先阶段或 semaphore | 黄色闪烁状态指示灯 |
| `starting` | 已进入 `get_agent()`，正在初始化 Workspace/ReMe | 黄色闪烁状态指示灯 |
| `running` | `get_agent()` 已完整成功返回 | 绿色静态状态指示灯 |
| `failed` | 最近一次启动失败 | 红色静态状态指示灯 |

黄色闪烁严格覆盖所有“enabled 但启动尚未完成”的正常过渡态：`pending` 和 `starting`。指示灯旁通过 Tooltip 显示本地化状态文本，不再使用红色“已禁用”Tag。

`enabled` 与 `startup_status` 的职责必须分开：

- `enabled` 是持久化配置，决定服务是否应启动 Agent。
- `startup_status` 是当前进程内的瞬时状态，重启后重新计算。

### 4.2 状态存放位置

在 `MultiAgentManager` 增加一个进程内字典，例如：

```python
self._agent_startup_statuses: dict[str, AgentStartupStatus] = {}
```

不把状态写回配置文件。启动状态具有瞬时性，持久化反而可能在异常退出后留下错误的 `starting`。

推荐的状态转换：

```text
enabled batch:  未记录 → pending → starting → running
启动失败:       pending/starting → failed
再次启动:       failed → starting → running/failed
配置 disabled:  API 输出强制为 disabled
```

`start_all_configured_agents()` 应在启动 default 前，一次性把所有 enabled Agent 标记为 `pending`。否则排在 semaphore 后面的 Agent 会在 UI 中短暂显示成未知状态。

状态的 `starting/running/failed` 转换放在 `get_agent()`，而不是只放在批量启动方法中。这样已有的 lazy load 和手动 enable 也能得到一致状态，不重复维护两套生命周期逻辑。

当 Agent 已存在于 `self.agents` 时，API 应返回 `running`。disabled Agent 则无条件返回 `disabled`，避免 manager 中的旧瞬时值覆盖配置事实。

### 4.3 并发一致性

沿用现有 `_lock` 保护“首次领取启动权”和最终写入 Agent 的关键路径。只有真正领取启动权的协程负责写 `starting/running/failed`；等待同一 Agent 的协程不改状态。

列表 API 只需要 manager 提供只读状态查询方法，不应让 router 直接访问 `_pending_starts` 或状态私有字典。

## 五、API 与前端设计

### 5.1 API

为 `AgentSummary` 增加：

```python
startup_status: Literal[
    "disabled",
    "pending",
    "starting",
    "running",
    "failed",
]
```

`GET /agents` 增加 `Request` 参数，通过现有 `_get_multi_agent_manager()` 获取 manager，然后为每个 Agent 计算状态。

这是向响应中增加字段，对现有调用方保持向后兼容。前端 TypeScript 类型同步增加同名联合类型。

### 5.2 状态指示灯展示

在现有 Agent 名称旁增加统一的 `AgentStatusIndicator` 小组件：

- `disabled`：灰色静态圆点。
- `pending`、`starting`：黄色圆点，并使用 CSS opacity 动画闪烁。
- `failed`：红色静态圆点。
- `running`：绿色静态圆点。

组件集中负责颜色、动画、Tooltip、ARIA 文本和 reduced-motion 降级，AgentTable 与 AgentSelector 只传入状态，避免两处复制判断。动画使用 CSS；当系统启用 `prefers-reduced-motion: reduce` 时停止闪烁并保持黄色常亮。

### 5.3 状态自动刷新

当前 `useAgents()` 只在页面首次进入和操作完成后请求一次。仅增加 API 字段会导致黄色标签停留在旧状态，因此需要最小的条件轮询：

- 只要列表中存在 `pending` 或 `starting`，每 1.5 秒静默刷新一次。
- 不触发表格全局 loading，避免轮询闪烁。
- 当所有 Agent 变为 `running`、`failed` 或 `disabled` 时立即停止。
- effect 清理时取消 timeout，避免页面卸载后的请求。
- 同一时刻只允许一个刷新请求，避免慢请求堆积。

相比 WebSocket/SSE，这个方案不增加协议和服务端连接管理，符合本次最小改动目标。

### 5.4 AgentSelector 中展示和启停 disabled Agent

当前 `AgentSelector` 实际上把 disabled Agent 与 enabled Agent 一起传给 Ant Design `Select`，并把 disabled 项设为不可选。它没有独立分组和启用入口，长列表中可发现性很差，也无法直接恢复 Agent。

建议把下拉内容明确分成两段：

```text
当前智能体                                      智能体管理 >
──────────────────────────────────────────────────────
enabled Agent 1                                  [禁用]
enabled Agent 2                                  [禁用]
enabled Agent 3                                  [禁用]
──────────────────────────────────────────────────────
已禁用 (4)                                           v
  disabled Agent 1                               [启用]
  disabled Agent 2                               [启用]
```

交互约定：

- enabled Agent 保留在主选择列表，可正常切换。
- disabled Agent 从 `Select.Option` 主列表移出，放到 `popupRender` 底部的独立折叠区，避免重复渲染。
- 折叠区仅在存在 disabled Agent 时出现，默认收起，标题显示 `已禁用 (N)`。
- 展开状态只保存在 `AgentSelector` 组件内，不写入 Zustand 或 localStorage。
- 顶部“当前智能体 (N)”继续只统计 enabled Agent；disabled 数量由折叠区单独显示。
- disabled Agent 行不可被选为当前 Agent，但提供 Lucide 启用按钮。
- enabled custom Agent 行提供 Lucide 禁用按钮；`default` 不显示禁用按钮。
- 桌面端行内动作保持低视觉权重，在 hover、focus-within 或键盘聚焦时突出；触屏端始终可见，不能依赖 hover 才能操作。
- 点击启停按钮必须 `preventDefault()` 和 `stopPropagation()`，不能顺带选择 Agent 或关闭下拉框。
- 点击启用后立即在前端将 Agent 乐观更新为 `enabled=true`、`startup_status=starting`，移回 enabled 主列表并显示黄色闪烁指示灯；不自动切换当前 Agent。
- 启动成功后服务端状态变为 `running`，指示灯更新为绿色；启动失败后重新拉取服务端状态，显示红色 `failed`，若配置没有成功保存则回到 disabled 区并显示灰色。
- 禁用当前选中的 Agent 成功后立即切换到 `default`，沿用现有提示语义。
- API 失败后重新请求 Agent 列表，以服务端配置为准，不保留错误的乐观状态。

### 5.5 Selector 启停中的加载与并发

复用现有接口：

```text
PATCH /agents/{agentId}/toggle
```

当前 enable API 会等待 Workspace 完成启动后才返回。为保持 API 兼容性，Selector 本次不改变这一行为：

- 点击启用后立即显示黄色闪烁状态指示灯；行内启用按钮同时进入 loading，直到同步 API 返回。
- 点击禁用后，该行显示“正在禁用”。
- 一次只允许一个 Selector 启停请求，其他行按钮临时禁用，避免用户连续启用多个 ReMe 并绕过启动并发预算。
- 请求期间保持下拉框打开；完成后静默刷新 Agent 列表。

`pending` 或 `starting` Agent 不允许执行禁用。原因是当前 `stop_agent()` 只能停止已经进入 `agents` 字典的实例；对初始化中的 Agent 立即写入 disabled 配置会产生“配置 disabled、实例随后仍启动完成”的竞态。

最小而可靠的处理是：

- Selector 和 Agent 管理表对 `pending/starting` 状态禁用启停按钮并显示“启动完成后可操作”的 Tooltip。
- toggle API 在收到“禁用 pending/starting Agent”的请求时返回 `409 Conflict`，防止绕过前端直接触发竞态。
- 本次不实现启动任务取消。等 Agent 进入 `running` 或 `failed` 后即可再次禁用。

### 5.6 Selector 布局与可访问性

- 折叠按钮使用原生 `button`，设置 `aria-expanded` 和关联区域的 `aria-controls`。
- 启用、禁用按钮必须有本地化的 `aria-label` 和 Tooltip，不能只依赖图标表达含义。
- disabled 区与 enabled 主列表共享下拉最大高度；内容过多时在下拉内部滚动，不能让弹层超出视口。
- 桌面端保持当前卡片宽度；窄屏时名称和描述允许省略，启停按钮保持固定点击区域。
- 新增图标只使用项目已采用的 `lucide-react`，不新增图标库或自制动画。

## 六、预计修改范围

### 6.1 业务代码

| 文件 | 最小修改 |
| --- | --- |
| `src/qwenpaw/app/_app.py` | 在核心阶段回调中提前打印一次 banner 并设置核心 Ready；删除原末尾 banner |
| `src/qwenpaw/app/multi_agent_manager.py` | default/QA 并发阶段、custom semaphore、核心完成回调、环境变量读取和运行时状态 |
| `src/qwenpaw/utils/startup_display.py` | 复用 Rich 增加 custom Agent 单进度条和非 TTY 降级 |
| `src/qwenpaw/app/routers/agents.py` | `AgentSummary.startup_status`、列表状态填充及启动中过渡态的 toggle 保护 |
| `src/qwenpaw/app/routers/healthz.py` | 将 readiness 文档语义更新为核心 Agent Ready |
| `console/src/api/types/agents.ts` | 增加状态联合类型和字段 |
| `console/src/components/AgentStatusIndicator/` | 统一灰、黄闪烁、红、绿四类状态指示灯 |
| `console/src/hooks/useAgentStatusPolling.ts` | 复用 pending/starting 条件轮询逻辑 |
| `console/src/pages/Settings/Agents/components/AgentTable.tsx` | 统一状态指示灯和过渡态启停保护 |
| `console/src/pages/Settings/Agents/useAgents.ts` | 仅过渡态存在时静默轮询 |
| `console/src/components/AgentSelector/index.tsx` | enabled 主列表、底部 disabled 折叠区及 Selector 内启停 |
| `console/src/components/AgentSelector/index.module.less` | 折叠区、行内启停按钮和滚动区域样式 |
| `console/src/locales/*.json` | 增加启动状态、disabled 分组、启停加载态及操作提示文案 |

不需要修改 Workspace、ReMe、配置 Pydantic 模型或数据库，也不新增依赖。

### 6.2 测试

后端优先增加定向单测：

1. default 与内置 QA 确实重叠执行，二者都结束前 custom Agent 不会开始。
2. 核心阶段结束后只输出一次 Ready banner，且耗时不包含 custom Agent。
3. custom Agent 的同时初始化数不超过环境变量值。
4. custom Agent 成功或失败都会推进进度，非 TTY 不输出动态控制字符。
5. QA 不存在或 disabled 时正常跳过。
6. 环境变量未设置、非法、为 `0` 和为 `1` 时行为符合约定。
7. 一个 Agent 失败不阻断其他 Agent，结果字典和 `failed` 状态正确。
8. 两个并发调用请求同一 Agent 时仍只启动一次，状态最终一致。
9. `GET /agents` 对 disabled、pending、starting、running、failed 的映射正确。
10. `/healthz` 在 default 成功且 QA 阶段结束后转为 200，不等待 custom Agent。
11. toggle API 拒绝禁用 `pending/starting` Agent 并返回 409，`running/failed` Agent 仍可禁用。

前端增加定向测试或至少覆盖以下断言：

1. `pending` 与 `starting` 显示黄色闪烁指示灯。
2. `failed` 显示红色、`running` 显示绿色、`disabled` 显示灰色指示灯。
3. 只有存在过渡态时轮询，终态后停止，组件卸载后不再请求。
4. Selector 主列表只包含 enabled Agent，disabled Agent 只在底部折叠区出现一次。
5. disabled 折叠区默认收起、计数正确，并具有 `aria-expanded`。
6. 启用成功后 Agent 移入主列表但不自动选中；失败后以重新拉取结果为准。
7. 禁用当前 Agent 后切换到 default；default 不提供禁用操作。
8. 点击行内启停按钮不会选中 Agent 或关闭下拉框。
9. 一个启停请求进行时其他启停按钮不可用，`pending/starting` Agent 不可禁用。

验证命令建议使用项目要求的 conda 环境：

```bash
conda run -n QwenPaw pytest \
  tests/unit/app/test_multi_agent_manager.py \
  tests/unit/app/routers/test_agents_router.py \
  tests/unit/app/routers/test_healthz.py \
  tests/unit/utils/test_startup_display.py

cd console && npm run test -- \
  src/pages/Settings/Agents \
  src/components/AgentSelector/AgentSelector.test.tsx
```

具体测试文件名应以实现时仓库现有测试组织为准，不为了匹配本文强行新建重复测试模块。

## 七、兼容性与风险

### 7.1 兼容性

- 未设置环境变量的部署从“无限并发”变为“custom Agent 最多并发 2 个”，启动总耗时可能增加，但核心 Ready 会更早显示。
- Windows、Linux、macOS 都通过 `os.environ` 的现有封装读取，无路径差异。
- API 只增加字段，不删除或改名现有字段。
- enabled 配置语义、删除行为、热重载和手动 enable 的返回语义保持不变；Selector 只是新增同一 toggle API 的入口。
- `/healthz` 的 200 时机提前到核心 Ready，这是本方案唯一有意调整的现有运行时语义；监控“全部 Agent 完成”应改看 Agent 状态或最终启动日志。

### 7.2 主要风险与处理

| 风险 | 处理 |
| --- | --- |
| default 启动失败却打印 Ready | 只有 default 成功时调用 Ready banner 并设置 readiness |
| QA 失败取消 default | `start_single_agent()` 内部隔离单 Agent 异常并返回失败结果 |
| QA ID 被错误硬编码 | 使用 `BUILTIN_QA_AGENT_ID` 常量 |
| 等待中的 Agent 没有黄色状态 | 批次开始时先统一标记 `pending` |
| 启动失败后一直显示“启动中” | `get_agent()` 异常路径明确写入 `failed` |
| 前端持续轮询 | 只在 `pending/starting` 时轮询，终态自动停止 |
| 大量等待协程仍创建 Workspace | semaphore 放在 `get_agent()` 调用外，等待者不会进入 Workspace 初始化 |
| 进度条污染容器或 CI 日志 | 仅 TTY 动态渲染，非 TTY 使用普通日志 |
| banner 重复出现 | 移除当前后台流程末尾的旧 banner 调用 |
| 禁用初始化中的 Agent 产生配置与实例不一致 | 前端禁用操作不可用，toggle API 同时以 409 防御 |
| 行内启停误触发 Agent 切换 | 对按钮事件执行 `preventDefault()` 和 `stopPropagation()` |
| 连续启用多个 Agent 造成新的 ReMe 峰值 | Selector 全局只允许一个启停请求进行 |
| 禁用当前 Agent 后页面仍引用旧 Agent | 成功后立即切换到 default，再刷新列表 |

## 八、验收标准

- default 与内置 QA 并发启动，custom Agent 只在两者都结束后开始。
- default 成功后只输出一次 Ready banner，其 `Startup` 是核心阶段耗时。
- `/healthz` 与 banner 在同一核心 Ready 节点进入 ready 状态。
- custom Agent 进度条位于 banner 后方，最终达到 `总数/总数`，失败任务也计入已处理数。
- custom Agent 的初始化峰值不超过 `QWENPAW_CUSTOM_AGENT_STARTUP_CONCURRENCY`。
- 控制台中 enabled 但尚未完成启动的 Agent 始终为黄色。
- 启动完成后黄色状态自动消失；失败后显示红色失败状态且停止轮询。
- Selector 主列表只展示 enabled Agent，底部默认收起的 disabled 区显示正确数量。
- 用户可以直接在 Selector 启用 disabled Agent、禁用非 default 的稳定态 Agent。
- 启停按钮不会触发 Agent 选择；禁用当前 Agent 后安全回退到 default。
- `pending/starting` Agent 无法通过 UI 或 toggle API 被禁用。
- 任一 Agent 启动失败不会阻断其他 Agent。
- 未修改 ReMe、Workspace 和热重载核心逻辑。
- 后端定向测试、前端定向测试、类型检查和涉及文件的 pre-commit 检查全部通过。

## 九、待评审决策与实施 Checklist

请重点确认以下七项：

- [x] default 与内置 QA 并发启动，二者阶段结束后才启动 custom Agent。
- [x] 环境变量改为 `QWENPAW_CUSTOM_AGENT_STARTUP_CONCURRENCY`，默认值仍建议为 `2`。
- [x] 同意 Ready banner 与 `/healthz` 都提前到核心阶段完成，并将 `Startup` 定义为核心就绪耗时。
- [x] custom Agent 使用已有 Rich 展示单条总进度，不新增 `tqdm` 依赖。
- [x] 同意手动 enable API 本次保持同步，不改成后台启动；黄色状态主要覆盖后台启动批次和其他 lazy-start 可观察窗口。
- [x] Selector 底部增加默认收起的 disabled Agent 区，并允许直接启用或禁用。
- [x] 同意 `pending/starting` 状态禁止禁用，toggle API 对该竞态返回 409，而不是实现启动任务取消。

评审通过后的实现 Checklist：

- [x] 增加 default/QA 并发核心阶段和 custom Agent semaphore。
- [x] 将 Ready banner 移到核心完成回调，并同步 readiness 语义。
- [x] 增加 custom Agent Rich 进度条及非 TTY 降级。
- [x] 增加 manager 内存态的启动状态机及查询方法。
- [x] 扩展 `GET /agents` 响应与 TypeScript 类型。
- [x] 增加灰、黄闪烁、红、绿状态指示灯和条件轮询。
- [x] 增加 Selector disabled 折叠区、行内启停、加载态和可访问性属性。
- [x] 为 toggle API 和两个前端入口增加启动中过渡态保护。
- [x] 补齐后端并发、顺序、失败与 API 测试。
- [x] 补齐前端状态展示与轮询测试。
- [x] 使用 `conda` 环境执行定向测试、类型检查和 pre-commit。
