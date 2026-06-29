# Loop Engineering Phase 2 设计文档

> **目标**：补齐 Loop 能力，实现完整的 loop 模式闭环。
> **原则**：内置精简 `/goal`，其余全部插件化，前端提供 Loop Designer。

---

## 一、总体架构

```
┌─────────────────────────────────────────────────────────┐
│                      前端 Console                        │
│                                                         │
│  Chat Input (现有)        Loop Designer (新增)           │
│  ┌─────────────────┐     ┌────────────────────────────┐ │
│  │ /goal chip      │     │ 6 区域配置表单             │ │
│  │ /ralph chip     │     │ 模板加载 + AI 辅助         │ │
│  │ /loop1 chip     │     │ 保存 → loop.json          │ │
│  │ Budget Selector │     │ 管理已有 loops             │ │
│  │ Status Bar      │     └────────────────────────────┘ │
│  └─────────────────┘                                     │
├─────────────────────────────────────────────────────────┤
│                      后端 QwenPaw                        │
│                                                         │
│  Built-in /goal Mode ← GoalMode(AgentMode)              │
│         │                                               │
│  PluginApi (改动 1-7 已完成)                             │
│         │                                               │
│  LoopLoader ← loop.json (用户自定义 + 预置插件)         │
│         │                                               │
│  ┌──────┴──────────────────────────────────────────┐    │
│  │ AgentScope Stop Hook (新增)                     │    │
│  │  _reasoning() 结束时 → 调用 stop_handlers       │    │
│  │  BLOCK → inject continuation → outer loop 继续  │    │
│  │  ALLOW → yield final_msg → agent 停止           │    │
│  └─────────────────────────────────────────────────┘    │
│                                                         │
│  Plugins:                                               │
│    plugins/ralph/          → LoopSkillConfig JSON       │
│    plugins/ultrawork/      → LoopSkillConfig JSON       │
│    plugins/deep-interview/ → LoopSkillConfig JSON       │
│    plugins/autopilot/      → LoopSkillConfig JSON       │
│    plugins/browser-mission/ → (已创建,需补充)            │
│    .qwenpaw/user-loops/    → 用户自定义 loop JSON       │
└─────────────────────────────────────────────────────────┘
```

---

## 二、实现清单

### Part A：AgentScope Stop Hook 实现

**目标**：在 AgentScope 的 ReAct 循环中增加 stop hook 扩展点，让 QwenPaw 的 `register_agent_stop_handler()` 有实际触发点。

**当前 AgentScope 行为分析**：
```python
# agentscope/agent/_agent.py → _reply() 核心循环
while self.state.cur_iter < self.react_config.max_iters:
    action, data = self._check_next_action()
    if action == "reasoning":
        async for evt in self._reasoning():
            if isinstance(evt, Msg):
                # ← 这里！agent 产出了最终文本（无 tool call）
                # ← 当前直接 yield + return → agent 停止
                yield ReplyEndEvent(...)
                yield evt
                return  # ← STOP POINT
```

**改动方案**（参考 LangChain DeepAgents RubricMiddleware）：

在 `QwenPawAgent._reasoning()` 中（不改 AgentScope 源码），覆写 stop 逻辑：

```python
# src/qwenpaw/agents/react_agent.py
async def _reasoning(self, **kwargs):
    """Override: intercept stop point for loop continuation."""
    async for evt in super()._reasoning(**kwargs):
        if isinstance(evt, Msg):
            # Agent 想停止了 — 检查 stop handlers
            result = await self._run_stop_handlers(evt)
            if result.action == StopAction.BLOCK:
                # 不 yield Msg → 注入 continuation
                self._inject_continuation(
                    result.continuation_message,
                )
                return  # outer loop 继续
            # ALLOW → 正常停止
        yield evt
```

**关键设计**：
- **不修改 AgentScope 源码** — 完全在 QwenPawAgent 层覆写
- 参考 LangChain RubricMiddleware 的 "grader verdict → needs_revision → re-prompt" 模式
- stop_handlers 按 priority 顺序执行，任何一个返回 BLOCK 即阻止退出
- iteration 计数 + max_iterations 硬上限防止无限循环
- 使用 `spawn_subagent` 工具做 architect review（类似 OMC 的 architect subagent）

**验证标准**：
- agent 无 tool call 时，stop handler 被触发
- BLOCK 时 continuation message 注入，agent 继续循环
- ALLOW 时 agent 正常停止
- 达到 max_iterations 时强制停止

---

### Part B：Built-in `/goal` Mode

**对标**：Codex 的 `/goal` 模式 — 设定目标，agent 持续工作直到目标达成。

**与其他 loop 的区别**：`/goal` 是 QwenPaw 唯一的内置循环，它是最通用的"设定目标 → 持续工作 → rubric 判定完成"模式。其他 loop（ralph, ultrawork 等）是特化的插件。

**实现**：

```python
# src/qwenpaw/modes/goal.py — 新文件
class GoalMode(AgentMode):
    """Built-in /goal mode: persistent until rubric satisfied."""

    name = "goal"

    def setup(self, workspace):
        workspace.slash_command_registry.register(
            "goal", self._activate,
            help_text="Set a goal. Agent works until done.",
        )
        workspace.slash_command_registry.register(
            "cancel", self._cancel,
            help_text="Cancel active goal.",
        )
```

**GoalMode 的 Stop Handler 逻辑**：
1. 用户输入 `/goal <task description>` → 激活 Goal Mode
2. Agent 收到 goal 描述 + skill_prompt → 开始工作
3. Agent 想停止时 → stop_handler 触发
4. **Rubric 判定**（两种模式）：
   - **LLM-as-Judge（软判断）**：spawn_subagent 做 grader，评估 agent 输出是否满足 goal
   - **硬判断**：检查 state file 中的完成条件
5. 判定未完成 → BLOCK + inject "Goal not yet met. Continue working. Feedback: {criteria_feedback}"
6. 判定已完成 → ALLOW → agent 正常停止

**Rubric Grader（LLM-as-Judge）实现**：
```python
async def _rubric_judge(self, goal, agent_output):
    """Use spawn_subagent as rubric grader."""
    grader_task = (
        f"Evaluate if this output satisfies the goal.\n"
        f"Goal: {goal}\n"
        f"Output summary: {agent_output[-2000:]}\n"
        f"Reply JSON: {{'verdict':'satisfied'|'needs_revision',"
        f"'feedback':'...'}}"
    )
    result = await spawn_subagent(
        task=grader_task,
        fork=False,
        background=False,
        timeout=60,
    )
    return parse_grader_verdict(result)
```

**GoalMode 状态**：
```json
{
  "goal": "用户设定的目标文本",
  "active": true,
  "iteration": 3,
  "max_iterations": 20,
  "rubric_mode": "llm_judge",
  "last_verdict": "needs_revision",
  "last_feedback": "Tests not passing yet",
  "budget": {
    "tokens_used": 45000,
    "max_tokens": 300000,
    "cost_usd": 0.8,
    "max_cost_usd": 3.0
  }
}
```

**前端 loopStore 更新**：将 `goal` 作为唯一 built-in skill 注册（其余由插件动态注册）。

---

### Part C：Ralph/Ultrawork/Deep Interview/Autopilot 插件化

将 4 个 loop 从 loopStore 硬编码移到 `plugins/` 目录，每个都有完整的 LoopSkillConfig JSON + 丰富的 Skill Prompt。

#### C1: plugins/ralph/

```
plugins/ralph/
├── plugin.json       # type: "loop"
├── plugin.py         # register via LoopLoader
├── loop_config.json  # LoopSkillConfig — 6 维度完整配置
├── SKILL.md          # 详细 Skill Prompt（参考 OMC/OMX）
└── README.md
```

**loop_config.json** 核心：
```json
{
  "name": "ralph",
  "slash_command": "ralph",
  "description": "持久完成循环 — 分解任务并逐个完成，architect 验证",
  "skill_prompt": "<从 SKILL.md 读取>",
  "rubric": {
    "mode": "hard_check",
    "check_expression": "state.stories && state.stories.every(s => s.status === 'done' && s.verified)",
    "continuation_prompt": "还有 {remaining} 个 story 未完成。当前进度: {progress}%。继续工作。"
  },
  "state": {
    "mode": "json_file",
    "filename": "ralph-state.json",
    "schema_hint": "stories: [{id, title, status, verified}], current_story_index"
  },
  "doom_loop": {
    "enabled": true,
    "window_size": 3,
    "similarity_threshold": 0.8,
    "action": "hitl"
  },
  "safety": {
    "max_iterations": 30,
    "thinking_only_streak_limit": 3,
    "consecutive_error_limit": 5,
    "budget": {
      "max_tokens": 500000,
      "max_cost_usd": 5.0,
      "on_exceed": "hitl"
    }
  },
  "priority": 90
}
```

**SKILL.md** 核心内容（参考 OMC `skills/ralph/SKILL.md`）：
- 任务分解：收到任务后分解为 stories，保存到 state file
- 逐个执行：按顺序完成每个 story
- Architect Review：每完成一个 story，使用 `spawn_subagent` spawn architect subagent 做 review
- 标记完成：review 通过后标记 `status: 'done', verified: true`
- 退出条件：所有 stories done → 输出总结 → `/cancel` 退出

#### C2: plugins/ultrawork/

```json
{
  "name": "ultrawork",
  "slash_command": "ultrawork",
  "description": "并行委派 — 分解 todos 逐个完成",
  "skill_prompt": "...",
  "rubric": {
    "mode": "hard_check",
    "check_expression": "state.todos && state.todos.every(t => t.done)",
    "continuation_prompt": "还有 {remaining} 个 todo 未完成。"
  },
  "state": {
    "mode": "json_file",
    "filename": "ultrawork-state.json"
  },
  "safety": {
    "max_iterations": 25,
    "budget": { "max_tokens": 400000, "max_cost_usd": 4.0 }
  }
}
```

**Ultrawork SKILL.md** 核心：
- 并行分解：将任务分解为多个独立 todos
- 逐个/并行完成：可使用 `spawn_subagent` 并行执行
- 自动退出：todos 全清自动退出，无需 `/cancel`

#### C3: plugins/deep-interview/

```json
{
  "name": "deep-interview",
  "slash_command": "deep-interview",
  "description": "苏格拉底式提问 — 深挖需求模糊点",
  "skill_prompt": "...",
  "rubric": {
    "mode": "soft_judge",
    "soft_judge_prompt": "Evaluate if the user's requirements are sufficiently clear. All key questions answered? Ambiguity score below 0.3?",
    "continuation_prompt": "There are still ambiguous areas. Continue questioning."
  },
  "state": { "mode": "none" },
  "doom_loop": {
    "enabled": true,
    "window_size": 5,
    "similarity_threshold": 0.7,
    "action": "hitl",
    "hitl_message": "Agent 反复问同一类问题"
  },
  "safety": {
    "max_iterations": 20,
    "budget": { "max_tokens": 100000, "max_cost_usd": 1.0 }
  }
}
```

#### C4: plugins/autopilot/

```json
{
  "name": "autopilot",
  "slash_command": "autopilot",
  "description": "多阶段自治 — 自动规划并执行",
  "skill_prompt": "...",
  "rubric": {
    "mode": "hard_check",
    "check_expression": "state.phase === 'complete'",
    "continuation_prompt": "Current phase: {state.phase}. Continue to next phase."
  },
  "state": {
    "mode": "json_file",
    "filename": "autopilot-state.json",
    "schema_hint": "phase: expansion|planning|execution|qa|validation|complete"
  },
  "safety": {
    "max_iterations": 40,
    "budget": { "max_tokens": 500000, "max_cost_usd": 5.0 }
  },
  "priority": 80
}
```

#### C5: plugins/browser-mission/ — 补充完善

修复现有的 browser-mission 插件：
- 补充完整的 `SKILL.md`（详细浏览器操作指令）
- 修正 `plugin.py` 中的 `LOOP_SKILL_CONFIG`，加入 `rubric.mode: "hard_check"`
- 调整 budget 与文档一致

---

### Part D：Loop Designer 前端 UI

**目标**：让非技术用户通过图形界面设计自定义 Loop，保存为 `loop.json` 并注册为 `/loopN` 斜杠命令。

**入口**：Console 侧边栏新增 "Loop Designer" 菜单项。

**页面结构**：

```
┌──────────────────────────────────────────────────────────┐
│ Loop Designer                    [Save] [Preview]        │
├──────────────────────────────────────────────────────────┤
│ ┌─ 1. 触发方式 ──────────────────────────────────────┐   │
│ │ 命令名: [____________]  描述: [________________]    │   │
│ └────────────────────────────────────────────────────┘   │
│ ┌─ 2. Skill Prompt ─────────────────────────────────┐   │
│ │ [多行文本编辑器]                                    │   │
│ │ [从模板加载 ▼]  字数: 234                          │   │
│ └────────────────────────────────────────────────────┘   │
│ ┌─ 3. Rubric ───────────────────────────────────────┐   │
│ │ 模式: (●) 硬判断  ( ) 软判断  ( ) 无              │   │
│ │ [条件表达式 / 评估标准]                             │   │
│ │ Continuation Prompt: [_____________]               │   │
│ └────────────────────────────────────────────────────┘   │
│ ┌─ 4. State ────────────────────────────────────────┐   │
│ │ 模式: (●) JSON 文件  ( ) 无状态                    │   │
│ │ 文件名: [____________]  Schema: [________]         │   │
│ └────────────────────────────────────────────────────┘   │
│ ┌─ 5. Doom Loop ────────────────────────────────────┐   │
│ │ [✓] 启用   窗口: [3]   阈值: [80%]               │   │
│ │ 动作: (●) HITL  ( ) 自动终止  ( ) 注入纠偏        │   │
│ └────────────────────────────────────────────────────┘   │
│ ┌─ 6. 安全阀 ──────────────────────────────────────┐   │
│ │ 最大迭代: [20]  空转限制: [3]  连续失败: [5]      │   │
│ │ Token 上限: [300000]  费用上限: [$3.00]           │   │
│ │ 超出动作: (●) HITL  ( ) 自动终止                   │   │
│ └────────────────────────────────────────────────────┘   │
├──────────────────────────────────────────────────────────┤
│ Templates: [Ralph] [Ultrawork] [Deep Interview] [+更多]  │
├──────────────────────────────────────────────────────────┤
│ My Loops:                                                │
│ ┌──────────────────────────────────────────────────────┐ │
│ │ /daily-review  "每日代码审查"         [Edit] [Delete]│ │
│ │ /news-crawler  "新闻抓取循环"         [Edit] [Delete]│ │
│ └──────────────────────────────────────────────────────┘ │
└──────────────────────────────────────────────────────────┘
```

**技术实现**：
1. 前端 React 页面 `console/src/pages/LoopDesigner/`
2. 后端 API endpoint:
   - `POST /api/loops` — 保存自定义 loop（写入 `.qwenpaw/user-loops/{name}.json`）
   - `GET /api/loops` — 列出所有 loop（built-in + 插件 + 用户自定义）
   - `PUT /api/loops/{name}` — 更新
   - `DELETE /api/loops/{name}` — 删除
3. 保存时 LoopLoader 即时注册，无需重启
4. 模板加载：从预置插件的 `loop_config.json` 读取

**用户自定义 Loop 存储**：
```
<workspace>/.qwenpaw/user-loops/
├── daily-review.json    # /daily-review
├── news-crawler.json    # /news-crawler
└── my-qa-loop.json      # /my-qa-loop
```

---

### Part E：前端 loopStore 动态化

**当前问题**：`loopStore.ts` 中 `availableSkills` 硬编码了 4 个 skill。

**改动**：
1. 启动时从后端 `GET /api/loops` 获取所有可用 loop
2. 保留 `goal` 作为唯一 built-in（不从 API 获取）
3. 插件注册的 loop + 用户自定义 loop 从 API 动态加载
4. Loop Designer 保存后实时刷新列表

```typescript
// loopStore.ts — 改动
availableSkills: [
  // Built-in (永远存在)
  { name: "goal", description: "设定目标 — Agent 持续工作直到完成", builtin: true },
  // 以下从 API 动态加载
],

fetchAvailableSkills: async () => {
  const res = await fetch('/api/loops');
  const loops = await res.json();
  set({ availableSkills: [
    GOAL_BUILTIN,
    ...loops.map(l => ({ name: l.slash_command, description: l.description })),
  ]});
},
```

---

### Part F：HITL 弹窗 UI

**当前问题**：DoomLoopDetector 返回 `ESCALATE_HITL` 后没有前端 UI 承接。

**实现**：
1. 后端通过 ACP SSE 发送 `DoomLoopAlert` 事件
2. 前端 Chat 页面监听该事件，弹出模态对话框：

```
┌──────────────────────────────────────────┐
│  ⚠ Agent 行为异常                        │
│                                          │
│  Agent 在循环 "ralph" 中连续 3 轮         │
│  执行相同操作 (file_write → same file)。  │
│                                          │
│  [继续循环]  [给 Agent 新指令]  [终止循环] │
└──────────────────────────────────────────┘
```

3. 用户选择后通过 ACP 回传给后端：
   - 继续 → resume loop
   - 新指令 → 注入用户消息 + resume
   - 终止 → deactivate loop

---

### Part G：Cancel 命令

注册全局 `/cancel` 命令，deactivate 所有活跃的 loop：

```python
# 在 GoalMode 和每个 loop 插件的 stop handler 中检查
# /cancel 命令由 LoopLoader 自动注册
```

---

## 三、实现顺序（依赖关系）

```
Phase 2 实现路线图:

Step 1: AgentScope Stop Hook     ← 所有 loop 的前提
  └─ QwenPawAgent._reasoning() 覆写
  └─ _run_stop_handlers() 方法
  └─ 单测验证 BLOCK/ALLOW/max_iterations

Step 2: Built-in /goal Mode      ← 验证 Stop Hook 可用
  └─ GoalMode 类
  └─ Rubric Grader (spawn_subagent)
  └─ /cancel 命令
  └─ 前端 loopStore 更新

Step 3: 5 个 Loop 插件            ← 验证 LoopLoader 端到端
  └─ plugins/ralph/
  └─ plugins/ultrawork/
  └─ plugins/deep-interview/
  └─ plugins/autopilot/
  └─ plugins/browser-mission/ (补充完善)
  └─ 每个插件含 SKILL.md + loop_config.json + README.md

Step 4: 前端 Loop Designer        ← 验证用户自定义 loop
  └─ 后端 API endpoints (/api/loops CRUD)
  └─ 前端 LoopDesigner 页面 (6 区域表单)
  └─ 模板加载 + 保存 + 实时注册
  └─ loopStore 动态化

Step 5: HITL 弹窗 + Cancel        ← 完善安全网
  └─ ACP DoomLoopAlert 事件
  └─ 前端 HITL 模态框
  └─ /cancel 全局命令

Step 6: 自测 + 集成测试
  └─ 单测: Stop Hook / GoalMode / LoopLoader
  └─ 集成: /goal 端到端 → stop → rubric → continue/stop
  └─ 前端: Loop Designer 保存 → /custom-loop 可用
```

---

## 四、文件变更清单

| 文件 | 操作 | 说明 |
|------|------|------|
| `src/qwenpaw/agents/react_agent.py` | **修改** | 覆写 `_reasoning()`，加入 stop handler 调用 |
| `src/qwenpaw/modes/goal.py` | **新增** | Built-in GoalMode |
| `src/qwenpaw/modes/__init__.py` | **修改** | 导出 GoalMode |
| `src/qwenpaw/app/_app.py` | **修改** | 注册 GoalMode 到 workspace |
| `src/qwenpaw/loop/loader.py` | **修改** | 支持从 SKILL.md 读取 skill_prompt |
| `src/qwenpaw/loop/rubric_grader.py` | **新增** | LLM-as-Judge rubric 评估器 |
| `src/qwenpaw/app/routers/loops.py` | **新增** | /api/loops CRUD API |
| `plugins/ralph/` | **新增** | Ralph 完整插件 |
| `plugins/ultrawork/` | **新增** | Ultrawork 完整插件 |
| `plugins/deep-interview/` | **新增** | Deep Interview 完整插件 |
| `plugins/autopilot/` | **新增** | Autopilot 完整插件 |
| `plugins/browser-mission/` | **修改** | 补充 SKILL.md + 修正 config |
| `console/src/pages/LoopDesigner/` | **新增** | Loop Designer 前端页面 |
| `console/src/stores/loopStore.ts` | **修改** | 动态化 + goal built-in |
| `console/src/components/HITLModal/` | **新增** | HITL 弹窗组件 |
| `tests/unit/loop/test_stop_hook.py` | **新增** | Stop Hook 单测 |
| `tests/unit/loop/test_goal_mode.py` | **新增** | GoalMode 单测 |

---

## 五、不做什么（明确排除）

1. **不修改 AgentScope 源码** — 完全通过 QwenPawAgent 覆写实现 stop hook
2. **不做 Workflow DAG 编辑器** — Loop Designer 是 6 区域表单，不是 n8n
3. **不实现 Team/Ultragoal/Ralplan** — 这三个复杂度高，作为后续 Phase 3
4. **不做 Plugin Marketplace** — 导入导出 + 市场是 Phase 3

---

## 六、验证标准

| 场景 | 预期行为 |
|------|----------|
| 用户输入 `/goal fix all tests` | agent 持续工作，每轮停止时 rubric grader 判定，未满足则继续 |
| agent 达到 max_iterations | 强制停止，输出 "Max iterations reached" |
| agent 进入 doom loop | 前端弹出 HITL 弹窗，用户可选择继续/终止/给新指令 |
| 用户输入 `/cancel` | 所有活跃 loop 立即停止 |
| 用户输入 `/ralph build the auth module` | Ralph 插件激活，分解 stories，逐个完成 + architect review |
| 用户在 Loop Designer 创建 `/daily-review` | 保存后立即可在 chat 输入框选择 `/daily-review` |
| 预算超出 | 触发 on_exceed 动作（HITL 弹窗或自动终止） |
