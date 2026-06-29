# Loop 实现差距分析：文档设计 vs 当前实现 vs OMC/OMX

## 一、总览

### 文档设计（loop_engineering.md）定义了 9 个 Loop 模式

| # | Loop 名称 | 文档中描述 | 当前实现状态 | OMC 有 | OMX 有 |
|---|-----------|------------|--------------|--------|--------|
| 1 | **Ralph** | 持久完成循环 — 分解→执行→architect review→标记 done | **仅前端 loopStore 注册了名称 + 空 JSON config** | 完整实现（persistent-mode 929-1248行） | 完整 SKILL.md |
| 2 | **Ultrawork** | 并行委派 — todos 全清自动退出 | **仅前端 loopStore 注册了名称** | 完整实现 | 完整 SKILL.md |
| 3 | **Deep Interview** | 苏格拉底式提问 — ambiguity < 0.3 停止 | **仅前端 loopStore 注册了名称** | 完整实现 | 完整 SKILL.md |
| 4 | **Autopilot** | 多阶段自治 — expansion→planning→execution→QA→validation | **仅前端 loopStore 注册了名称** | 完整实现 | 完整 SKILL.md |
| 5 | **Browser Mission** | 浏览器自动化 — 操控浏览器完成任务 | **刚转为插件（plugin.py 有 JSON config 但无 SKILL prompt 细节）** | 无（QwenPaw 原创） | 无 |
| 6 | **Ultragoal** | 多目标编排 — 每个目标内跑 Ralph | 未实现 | 有（bridge层） | 完整 SKILL.md |
| 7 | **Ralplan** | 共识规划 — Planner+Architect+Critic 三方 | 未实现 | 完整实现（1783-1889行） | 完整 SKILL.md |
| 8 | **Team** | 协同多 agent — tmux/subagent workers | 未实现 | 完整实现（1479-1602行） | 完整 SKILL.md |
| 9 | **Simple Loop** | 最简持久循环 | 未实现 | 无（OMC 不需要） | 无 |

### 结论：**当前 4 个 built-in loop（Ralph/Ultrawork/Deep Interview/Autopilot）只有名字，没有实际的 Skill Prompt 和 Loop Config**

---

## 二、基建层（改动 1-7）实现对比

| 改动 | 文档设计 | 当前实现 | 与 OMC/OMX 对比 | 差距 |
|------|----------|----------|-----------------|------|
| 1. `register_slash_command()` | 注册 slash command 到每个 workspace 的 SlashCommandRegistry | **已实现** `api.py:486` — deferred startup hook 注册 | OMC 用 keyword-detector 正则匹配，QwenPaw 更精确 | **无差距** |
| 2. `register_mode()` | 注册 AgentMode 到 workspace | **已实现** `api.py:544` — startup hook 遍历 workspace 注册 | OMC/OMX 无 mode 概念 | **无差距** |
| 3. `register_runtime_hook()` | 注册 Runtime 8-phase hook | **已实现** `api.py:584` — 注册 HookBase 到 HookRegistry | OMC hooks.json 声明外部 command，QwenPaw 更原生 | **无差距** |
| 4. 动态命令广播 | ACP 动态读取 SlashCommandRegistry + Console API | **已实现**（前端 commandSuggestions 已动态化） | OMC/OMX 不需要（CLI 无自动补全） | **无差距** |
| 5. `register_agent_stop_handler()` | 订阅 AgentScope Stop event，block/continue 判断 | **已实现** `api.py:623` — 注册 handler 到 _stop_handlers | OMC 的 Stop hook 是核心（persistent-mode.ts 2376行），QwenPaw 仅有桥接接口 | **AgentScope 尚未提供 Stop event，handler 注册了但无法真正触发** |
| 6. `register_prompt_section()` | 3 层 prompt 注入（system/context/user_turn） | **已实现** `api.py:676` — 支持 layer/after/priority/condition | OMC 在 UserPromptSubmit hook 中注入 SKILL.md | **无差距** |
| 7. `register_tool_call_observer()` | 每次 tool 调用后观察 + Doom Loop 检测 | **已实现** `api.py:732` — 注册 observer 到 _tool_observers | OMC 在 Stop hook 中检测 thinking-only-streak（不如 QwenPaw 实时） | **无差距（接口层面）** |

### 基建总结：7/7 改动的 API 接口已全部实现。**核心差距在于 Stop event 的真正桥接取决于 AgentScope**。

---

## 三、各 Loop 详细对比

### 3.1 Ralph（文档 vs 实现 vs OMC/OMX）

| 维度 | 文档设计 | 当前 QwenPaw 实现 | OMC 实现 | OMX 实现 |
|------|----------|-------------------|----------|----------|
| **Skill Prompt** | "你是一个任务完成 agent。分解为 stories，逐个完成，spawn architect review..." | **无** — loopStore 只有 `{ name: "ralph", description: "持久完成循环..." }` | 完整 `skills/ralph/SKILL.md`（数百行指令） | 完整 `skills/ralph/SKILL.md`（含 stories/architect/verification） |
| **Rubric** | 硬判断：`stories.every(s => s.status === 'done' && s.architect_verified)` | **无** — 没有 LoopSkillConfig JSON 定义 | `checkRalphLoop()` 320行硬判断 | SKILL.md 内指令驱动 |
| **State Schema** | `{ stories: [{id, title, status, architect_verified}], current_story_index }` | **无** | `.omc/state/ralph-state.json` | `.omx/state/{scope}/ralph-progress.json` |
| **Doom Loop** | 连续 3 轮 same action+target → HITL | **无**（DoomLoopDetector 类存在但未被 ralph 注册） | thinking-only-streak-guard（3次） | 无系统级 |
| **安全阀** | max_iterations:30, streak:3, error:2, token:500k, cost:$5 | **无** | hard-max-iterations + circuit breaker | 依赖 SKILL.md |
| **LoopSkillConfig JSON** | 文档 3.5 节有完整 JSON 示例 | **不存在** | N/A（OMC 不用 JSON config） | N/A |

### 3.2 Ultrawork

| 维度 | 文档设计 | 当前 QwenPaw 实现 | OMC 实现 |
|------|----------|-------------------|----------|
| **Skill Prompt** | 并行分解 todos，逐个完成 | **无** | 完整 SKILL.md |
| **Rubric** | 硬判断：todos 全清 → 自动退出 | **无** | `deactivateUltrawork()` |
| **特殊逻辑** | 检查 agent todo list | **无** | reinforcement_count + linked_to_ralph |

### 3.3 Deep Interview

| 维度 | 文档设计 | 当前 QwenPaw 实现 | OMC 实现 |
|------|----------|-------------------|----------|
| **Skill Prompt** | 苏格拉底式提问，ambiguity_score < 0.3 退出 | **无** | 完整 SKILL.md（含权重化 ambiguity） |
| **Rubric** | 软判断：LLM 评估 ambiguity | **无** | 非持久模式，无 Stop 拦截 |

### 3.4 Autopilot

| 维度 | 文档设计 | 当前 QwenPaw 实现 | OMC 实现 |
|------|----------|-------------------|----------|
| **Skill Prompt** | 多阶段：expansion→planning→execution→QA→validation→complete | **无** | 完整 SKILL.md + state machine |
| **Rubric** | 硬判断：phase = complete | **无** | workflowAuthority 动态优先级 |
| **嵌套** | 内部启动 ralph | **无** | autopilotPriorityFirst |

### 3.5 Browser Mission

| 维度 | 文档设计 | 当前 QwenPaw 实现 |
|------|----------|-------------------|
| **Skill Prompt** | "浏览器自动化 agent，分解 QA stories，操控 browser_use" | **plugin.py 有通用描述但很简短（3句话）** |
| **Rubric** | 硬判断：`prd.json → stories.every(s.passes)` | **有 LoopSkillConfig 但 rubric.mode 未设置为 hard_check** |
| **State Schema** | `{ stories, iteration_count, last_actions }` | **有 state.schema 但无 persist_key 使用** |
| **Doom Loop** | 滑窗 K=3, action+url diversity | **有配置（window:6, threshold:0.8）** |
| **安全阀** | max:20, token:300k, cost:$3 | **有（max:20, token:200k, cost:$2）** |

---

## 四、OMC 有但 QwenPaw 文档/实现中完全缺失的能力

| 能力 | OMC 实现位置 | 说明 |
|------|-------------|------|
| **Architect subagent** | `persistent-mode.ts:874-923` | Ralph 完成 story 后 spawn architect 做 review，分析 transcript 判断 approval/rejection |
| **PRD story tracking** | `ralph/index.ts` + `prd.json` | 每个 story 有 passes/architectVerified 状态 |
| **Thinking-only streak guard** | `persistent-mode.ts:1307-1465` | 连续 N 次无 tool 调用 → 注入纠偏 prompt |
| **Tool error retry guidance** | `persistent-mode.ts` | tool 连续报错时注入重试指导 |
| **Stop breaker / Circuit breaker** | `persistent-mode.ts` | 防止无限循环的硬上限 |
| **Cancel signal TTL** | `persistent-mode.ts:2120-2130` | /cancel 的 session-scoped 信号传播 |
| **Workflow slot ledger** | `persistent-mode.ts:2091-2096` | 多 loop 嵌套时的 slot 管理 + tombstone 回收 |
| **Critical context stop bypass** | `persistent-mode.ts:2098-2107` | context-limit 时绝不 block（防死锁） |
| **Team worker pipeline** | `persistent-mode.ts:1479-1602` | N 个 tmux worker 协同 + shared mailbox |
| **Session isolation** | 全局 | hook 只对匹配 session_id 生效，stale >2h 忽略 |

---

## 五、前端 loopStore 中 4 个 built-in skill 的真实状态

```typescript
// console/src/stores/loopStore.ts — 当前内容
availableSkills: [
  { name: "ralph", description: "持久完成循环 — 分解任务并逐个完成" },
  { name: "ultrawork", description: "并行委派 — 分解 todos 逐个完成" },
  { name: "deep-interview", description: "苏格拉底式提问 — 深挖需求模糊点" },
  { name: "autopilot", description: "多阶段自治 — 自动规划并执行" },
]
```

**这 4 个 skill 在后端没有对应的 LoopSkillConfig JSON 文件或 plugin 注册。** 用户选择后，前端会发送 `/ralph xxx` 到后端，但后端没有注册 `/ralph` slash command 的处理器，消息会作为普通文本发给 LLM。

---

## 六、browser-mission 插件 vs 文档设计的差距

| 维度 | 文档设计 | plugin.py 实际 |
|------|----------|----------------|
| **skill_prompt** | 详细 4 步指令（分解 QA stories→操控浏览器→blocker 报告→prd.json 检查） | 简短 3 句话（"navigate pages, click elements, fill forms"） |
| **rubric.mode** | `hard_check` — 读 prd.json | **缺失** — config 没有 rubric 字段 |
| **rubric.check_expression** | `stories.every(s => s.passes === true)` | **缺失** |
| **rubric.continuation_prompt** | "The browser task is not yet complete..." | 有（但 rubric 整体缺失） |
| **state.mode** | `json_file` | 有 persist_key 但 mode 未设为 json_file |
| **doom_loop.action** | `ask_human` | `ask_human` — **匹配** |
| **safety.budget** | max_tokens:300k, cost:$3 | max_tokens:200k, cost:$2 — **不匹配** |

---

## 七、关键结论

### 已完成
1. **基建层 7/7 API 接口** — 全部实现，单测通过
2. **LoopLoader + Schema** — 翻译引擎存在，可将 JSON config → PluginApi 调用
3. **DoomLoopDetector** — 滑窗相似度检测器已实现
4. **StopHandler 框架** — StopAction/StopHandlerResult 类型已定义
5. **前端 UI** — Chip + Budget Selector + Status Bar 已实现
6. **browser-mission 插件化** — 结构存在但 config 不完整

### 未完成 / 差距
1. **4 个 built-in loop（Ralph/Ultrawork/Deep Interview/Autopilot）没有实际的 LoopSkillConfig JSON 和 Skill Prompt** — 只有前端展示名，后端无注册
2. **browser-mission 的 skill_prompt 过于简短**，缺少文档中定义的 rubric 硬判断
3. **AgentScope 的 Stop event 桥接未就绪** — register_agent_stop_handler() 注册的 handler 没有实际触发点
4. **OMC 的防御机制（architect subagent, streak guard, circuit breaker, PRD tracking）** 在 QwenPaw 中完全没有实现
5. **Cancel 命令** 未注册（文档要求每个 loop 注册 `/cancel`）
6. **HITL 前端弹窗** 未实现（DoomLoopDetector 返回 ESCALATE_HITL 后无 UI 承接）
7. **State file 持久化** 未实现（LoopSession 是内存态，重启丢失）

### 差距严重程度

| 级别 | 说明 |
|------|------|
| **P0 — 不可用** | 4 个 built-in loop 选择后后端无响应（只是前端装饰） |
| **P1 — 不完整** | browser-mission config 不完整；Stop event 未桥接 |
| **P2 — 缺少防御** | 无 architect review、streak guard、circuit breaker、cancel |
| **P3 — 缺少 UX** | HITL 弹窗、state 持久化 |
