# 循环工程（Loop Engineering）

普通对话中，Agent 回复一次就停下来等你的下一条消息。但有些任务不是一个回合能搞定的——修复一串测试、实现一个完整功能、或者把一个大需求拆成多个子任务交给不同的 Agent 去执行。

Loop Engineering 让 Agent **持续工作多个回合**，直到任务完成、预算耗尽或你主动喊停。

---

## 选择哪种模式？

| 你的任务                          | 推荐模式         |
| --------------------------------- | ---------------- |
| 快速问答、小修小补                | 普通对话         |
| 目标明确、需要持续推进的任务      | **Goal 模式**    |
| 调研一个话题并输出完整报告        | **Goal 模式**    |
| 包含多个独立子任务的大型项目      | **Mission 模式** |
| 需要多个 Agent 分工协作的复杂需求 | **Mission 模式** |

> **两种模式的核心区别：** Goal 模式使用单个 Agent 持续工作，通过 **self-audit（自我审计）** 验证完成度——Agent 必须自己证明目标达成。Mission 模式使用多个子 Agent 分工协作，通过 **上下文隔离** 防止长对话中的上下文腐烂——每个 worker 只关注自己的子任务，不会被其他任务的信息干扰。

---

## 普通模式下的 Loop 设置

即使不使用 Goal 模式或 Mission 模式，QwenPaw 也有循环控制机制保护 Agent 的行为。你可以在 Console 中通过 **运行配置 → 智能体 Loop 设置** 来配置以下选项。

### Loop 模板

Console 预设了三种模板，一键切换：

| 模板        | 用途                         |
| ----------- | ---------------------------- |
| **默认**    | 普通对话，适中的迭代上限     |
| **Goal**    | 为 `/goal` 命令优化的参数    |
| **Mission** | 为 `/mission` 命令优化的参数 |

选择模板后，下方的各项参数会自动填入推荐值。你也可以手动调整。

### 迭代限制

防止 Agent 无限循环。当 Agent 的推理-行动（ReAct）迭代次数达到上限时，强制停止。

| 设置项       | 默认值 | 说明              |
| ------------ | ------ | ----------------- |
| 启用迭代限制 | 开启   | 是否启用          |
| 最大迭代次数 | 50     | 到达后 Agent 停止 |

> **什么是一次迭代？** Agent 每做一轮"思考 → 调用工具 → 获取结果"或"思考 → 输出文本"就算一次迭代。一个复杂任务可能需要几十次迭代。

### 重复行为保护

检测 Agent 是否陷入"死循环"——反复做相同的事情（如连续调用同一个工具、传相同的参数）。

系统用一个滑动窗口跟踪最近的工具调用，计算相似度。当检测到重复模式时，分阶段处理：

1. **第一阶段（轻微重复）：** 注入一条提示，建议 Agent 换个思路
2. **第二阶段（严重重复）：** 强制停止循环

默认开启，大多数场景无需手动调整。

### 完成度检查

部分大模型可能仅输出文本而不调用任何工具，导致 Agent 提前停止。启用后，当 Agent 只输出文本（没有工具调用）时，系统会自动注入一条提醒，要求它确认任务是否真的完成。

| 设置项         | 默认值                           | 说明             |
| -------------- | -------------------------------- | ---------------- |
| 启用完成度检查 | 关闭                             | 是否启用         |
| 检查提示语     | _"You did not call any tool..."_ | 注入的提醒文本   |
| 最大干预次数   | 1                                | 每轮最多提醒几次 |

> **什么时候需要开启？** 如果你发现 Agent 经常在任务没做完时就输出一段文字然后停下来，可以开启这个选项。

### 对应的 agent.json 配置

以上 Console 设置对应 `agent.json` 中的 `running.loop` 字段：

```json
{
  "running": {
    "loop": {
      "iteration": {
        "enabled": true,
        "max_iterations": 50
      },
      "doom_loop": {
        "enabled": true,
        "window_size": 6,
        "similarity_threshold": 0.8,
        "stages": [
          { "after": 2, "action": "modify_prompt", "message": "..." },
          { "after": 4, "action": "stop", "message": "..." }
        ]
      },
      "rubric": {
        "enabled": false,
        "prompt": "You did not call any tool in the last turn...",
        "max_interventions": 1
      }
    }
  }
}
```

---

## Goal 模式

设定一个目标，Agent 自主工作直到完成。不限于编程——任何你能描述清楚目标的任务都适用。

### 快速开始

在对话框中输入：

```
/goal 调研 2026 年主流大模型的上下文窗口长度，整理成对比表格
```

更多示例：

```
/goal 修复所有失败的单元测试，确保通过率达到 100%
/goal 将项目文档从中文翻译成英文，保持格式一致
/goal 分析上周的用户反馈数据，生成一份趋势报告
```

Agent 会持续工作——使用工具、分析结果、调整方案——直到目标完成或预算用尽。

### Agent 可以使用的目标工具

Goal 模式会自动为 Agent 启用三个专用工具，你不需要手动配置：

| 工具          | 作用                                                    |
| ------------- | ------------------------------------------------------- |
| `get_goal`    | Agent 查看当前进度——迭代次数、Token 用量、剩余预算      |
| `update_goal` | Agent 标记目标完成（`complete`）或遇到阻塞（`blocked`） |
| `create_goal` | Agent 在对话中创建新目标（仅当你明确要求时）            |

### 什么时候循环会停？

| 条件           | 说明                                                              |
| -------------- | ----------------------------------------------------------------- |
| 目标完成       | Agent 确认所有需求都满足后，调用 `update_goal(status="complete")` |
| 遇到阻塞       | 连续多轮遇到相同问题，Agent 报告阻塞                              |
| 迭代用完       | 达到最大迭代次数（默认 20）                                       |
| Token 预算耗尽 | Token 使用量超过预算（默认 300,000）                              |
| 你主动停止     | 点击停止按钮                                                      |

### 关于完成质量

Agent 不会随便说"我做完了"。在标记目标完成之前，它会：

- 从你的目标描述推导出具体需求
- 逐项检查，找到实际证据（如运行测试、查看文件）
- 把没有确切证据的项视为"未完成"

这意味着 Goal 模式比普通对话更可靠——Agent 必须**证明**任务完成了，而不是仅仅"觉得"完成了。

---

## Mission 模式

将大型任务拆解为多个用户故事（user stories），通过 **master → worker → verifier** 流水线自动完成。每个子 Agent 只处理自己的子任务，上下文完全隔离，避免长对话中信息混杂导致的质量下降。

### 快速开始

```
/mission 用 Python 创建一个 CLI TODO 应用，支持添加、删除、列表和标记完成功能，数据保存到本地 JSON 文件
```

可选参数：

```
/mission 创建 Web API --max-iterations 30 --verify "pytest tests/"
```

查看进度和历史：

```
/mission status    # 当前进度
/mission list      # 所有 mission 列表
```

### 工作流程

**Phase 1 — 任务分解**

Agent 分析你的任务，生成一份 PRD（Product Requirements Document），包含多个用户故事。你确认 PRD 后进入 Phase 2。

**Phase 2 — 自主执行**

1. Master agent 将每个用户故事分配给 worker agent
2. Worker agent 独立实现功能
3. Verifier agent 独立验证每个故事是否满足验收标准
4. 未通过的故事自动重试，直到全部通过或迭代用完

### 进度展示

```
Mission Status — mission-20260415-123456
- Phase: execution
- Progress: 2/4 stories passed

  ✅ US-001: Add Task Feature
  ✅ US-002: List Tasks Feature
  ⬜ US-003: Delete Task Feature
  ⬜ US-004: Mark Complete Feature
```

### 注意事项

1. **Session 隔离**：每个 session 的 mission 独立运行，互不干扰
2. **工具限制**：Phase 2 中 master agent 不能直接编辑文件或使用浏览器，必须委派给 worker agents
3. **安全提示**：Worker 和 verifier agents 会自动绕过安全护栏（因为后台 session 无法响应 `/approve`）。建议仅在完全信任的代码仓库中使用

---

## 模式对比

| 特性           | 普通对话       | Goal 模式              | Mission 模式                         |
| -------------- | -------------- | ---------------------- | ------------------------------------ |
| **适用场景**   | 简单任务       | 目标明确的持续任务     | 大型复杂任务                         |
| **Agent 数量** | 1              | 1                      | 多个（master + workers + verifiers） |
| **循环行为**   | 回复一次即停   | 持续循环 + self-audit  | 多 Agent 流水线 + 上下文隔离         |
| **完成判定**   | Agent 输出文本 | Agent 调用 update_goal | PRD 中所有故事通过                   |
| **预算控制**   | 迭代上限       | 迭代 + Token 预算      | 迭代上限                             |
| **工具限制**   | 无             | 无                     | Master 受限                          |

---

## 开发 Loop 插件

> 以下内容面向插件开发者。如果你只是使用 Goal 模式 或 Mission 模式，前面的内容已经足够。

QwenPaw 的循环系统是完全可插拔的。你可以通过插件 API 注册自定义的循环行为，实现自己的"何时停、何时继续"逻辑。

### 基本思路

循环控制的核心是 **Gate**——每轮迭代结束后，系统会依次询问所有注册的 Gate："要停吗？"。Gate 有三种回答：

- **STOP** — 请求停止循环
- **CONTINUE** — 请求继续循环（可附带一条消息注入对话）
- **None** — 没有意见，不干预

第一个给出 STOP 或 CONTINUE 的 Gate 决定本轮的结果。

### 编写一个 Gate

```python
from qwenpaw.loop.gates.base import (
    StopAction,
    StopGate,
    StopHandlerResult,
)


class TimeoutGate(StopGate):
    """Example: stop after N minutes."""

    def __init__(self, max_minutes=30):
        self._max = max_minutes * 60
        self._start = None

    @property
    def name(self):
        return "timeout"

    @property
    def priority(self):
        return 50  # lower = runs earlier

    async def check(self, ctx):
        import time

        if self._start is None:
            self._start = time.time()
        elapsed = time.time() - self._start
        if elapsed > self._max:
            return StopHandlerResult(
                action=StopAction.STOP,
                reason=f"Timeout after {self._max}s",
            )
        return None  # no opinion
```

`ctx` 是一个字典，包含当前迭代的上下文信息：

| 字段             | 说明                                            |
| ---------------- | ----------------------------------------------- |
| `agent`          | Agent 实例                                      |
| `final_msg`      | Agent 最后一条消息（`None` 表示本轮是工具调用） |
| `iteration`      | 当前迭代序号                                    |
| `has_tool_calls` | 本轮是否有工具调用                              |

### 在插件中注册

```python
from qwenpaw.loop.gates import StopHandler
from qwenpaw.plugins.api import PluginAPI


class MyLoopPlugin(PluginAPI):
    def on_load(self):
        handler = StopHandler()
        handler.register(TimeoutGate(max_minutes=30))

        self.register_agent_stop_handler(
            handler=handler,
            priority=100,
            name="timeout-loop",
        )
```

注册后，你的 Gate 会在每轮 ReAct 迭代结束时被执行，与内置 Gate 并行评估。你开发的 Loop 插件可以发布到 QwenPaw 插件市场，其他用户一键安装即可获得新的循环能力——比如基于外部 API 状态控制循环、根据代码覆盖率决定是否继续、或者接入自定义的质量评估服务。

### Scope 隔离

注册时可以设置 `scope` 来控制 handler 的激活时机：

| scope       | 行为                                            |
| ----------- | ----------------------------------------------- |
| `""` (空)   | 始终运行，无论当前处于什么模式                  |
| `"default"` | 仅在普通对话中运行，Goal/Mission 活跃时自动跳过 |
| 自定义值    | 仅在对应模式活跃时运行                          |

---

## 设计理念

### Gate 系统

QwenPaw 用一套 **Gate（门控）系统** 来管理循环的终止逻辑。你可以把 Gate 想象成流水线上的质检站——Agent 每完成一轮工作，所有 Gate 都会被依次检查。

```
Agent 完成一轮工作
      ↓
   Gate 1 (迭代上限)  →  达到上限？→ STOP
      ↓ 没意见
   Gate 2 (死循环检测)  →  在重复？→ STOP 或 注入提示
      ↓ 没意见
   Gate 3 (完成度检查)  →  只输出文本？→ CONTINUE + 提醒
      ↓ 没意见
   Gate 4 (插件 Gate)  →  自定义逻辑
      ↓ 所有 Gate 都没意见
   Agent 停止（无活跃循环）
```

每个 Gate 有三种回答：

- **STOP**：请求停止循环
- **CONTINUE**：请求继续（可附带消息注入对话）
- **无意见**：不干预，交给下一个 Gate

第一个给出明确回答的 Gate 决定本轮结果。Gate 按优先级排序执行（数字越小越先执行），因此你可以精确控制不同 Gate 之间的优先关系。

### Scope 隔离

不同模式的 Gate 互不干扰。当 Goal 模式 或 Mission 模式 活跃时，普通模式的默认 Gate 会自动退让，只有对应模式的 Gate 在运行。模式结束后，默认 Gate 自动恢复。

这意味着：

- 普通对话 → 只运行迭代限制、死循环检测等默认 Gate
- `/goal` 激活 → 默认 Gate 退让，Goal 模式 的 Gate 接管
- `/mission` 激活 → 默认 Gate 退让，Mission 模式 的 Gate 接管
- 模式结束 → 默认 Gate 自动恢复

### 延迟执行

当 Agent 正在执行工具调用时，STOP 信号不会立即生效——系统会等工具执行完、Agent 拿到结果后再停止。这避免了工具执行到一半被打断的情况。

### Session 隔离

每个用户会话的 Gate 状态完全独立。多个用户同时使用同一个 Agent 时，各自的循环互不影响。

---

## 未来规划

我们正在让循环工程变得更加易用和强大：

**零代码 Gate 编排** — 目前自定义 Gate 需要编写 Python 插件。我们计划在 Console 中提供可视化的 Gate 编排界面：通过拖拽组合不同的 Gate，设定优先级和触发条件，直接在浏览器中预览效果。这意味着产品经理和运维人员也可以定制 Agent 的循环策略，不再需要开发者介入。

**声明式配置** — 除了可视化界面，我们还将支持通过 YAML/JSON 声明式地定义 Gate 链。这让你可以把循环策略纳入版本管理，在不同环境间一键复制，或者在 CI/CD 中自动化部署。
