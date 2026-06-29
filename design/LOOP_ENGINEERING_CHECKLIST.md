# Loop Engineering 实施 Checklist

> 状态说明: ⬜ 待开始 | 🟡 进行中 | ✅ 完成 | ❌ 取消

---

## 前置分析：现有基建盘点

| 已有组件 | 文件位置 | 与 Loop 的 GAP |
|---|---|---|
| `PluginApi` | `src/qwenpaw/plugins/api.py` | 无 slash_command / mode / runtime_hook / stop_handler / observer / prompt_section 暴露 |
| `SlashCommandRegistry` | `src/qwenpaw/runtime/slash_command_registry.py` | 完整可用，但插件无法注册到此 |
| `HookRegistry` 8-phase | `src/qwenpaw/runtime/hooks.py` | 完整可用，插件无 API 注册 |
| `WorkspacePlugins` | `src/qwenpaw/app/workspace/workspace_plugins.py` | 已有 `register_mode()` |
| `AgentMode` 基类 | `src/qwenpaw/modes/base.py` | 完整可用 |
| `ToolCoordinator` | `src/qwenpaw/tool_calls/_coordinator.py` | 有 `on_completion()` 但不通过 PluginApi 暴露，无通用 observer |
| `ToolHookRegistry` per-tool | `src/qwenpaw/tool_calls/_hooks.py` | 按 tool 名注册，不支持全局 observer |
| `PluginRegistry.register_prompt_section()` | `src/qwenpaw/plugins/registry.py:531` | 只有 system prompt 注入，无 context/user turn 注入，无 priority，PluginApi 未暴露 |
| `PromptManager` | `src/qwenpaw/runtime/prompt_manager.py` | 只有 system prompt 层 |
| ACP `_build_available_commands()` | `src/qwenpaw/agents/acp/server.py:987` | 硬编码 `_ADVERTISED_COMMAND_ORDER` |
| Console commandSuggestions | `console/src/pages/Chat/index.tsx` | 硬编码列表 |

---

## 第一部分：基建层改动（按文档顺序 1-7）

### 改动 1：`PluginApi.register_slash_command()`

**目标**：让插件能注册 `/xxx` 命令到 workspace 的 `SlashCommandRegistry`。

- ⬜ 1.1 在 `PluginApi` 新增 `register_slash_command(name, handler, *, aliases, category, help_text, metadata)` 方法
- ⬜ 1.2 内部通过 startup hook 将 `CommandSpec` 注册到每个 workspace 的 `SlashCommandRegistry`
- ⬜ 1.3 同时注册 `workspace_created` hook，保证后续新建 workspace 也能注册
- ⬜ 1.4 单测：startup 后命令可 resolve + dispatch

**设计要点**：
- 注册是 deferred（startup hook）——因为 PluginApi 初始化时 workspace 未就绪
- 与 `register_control_command()` 的区别：后者走全局优先级路由，前者直接进 workspace slash registry

---

### 改动 2：`PluginApi.register_mode()`

**目标**：让插件能注册完整的 `AgentMode`（commands + tools + hooks + prompt_contributors 捆绑）。

- ⬜ 2.1 在 `PluginApi` 新增 `register_mode(mode_cls)` 方法
- ⬜ 2.2 startup hook 中遍历所有 workspace 调用 `workspace.plugins.register_mode(mode, workspace)`
- ⬜ 2.3 workspace_created hook 中对新 workspace 也注册
- ⬜ 2.4 单测：mode 注册 + setup 调用 + 命令/hook/tool 均挂载

**设计要点**：
- `WorkspacePlugins.register_mode()` 已存在，只需桥接
- Mode 优先级链：多 loop 嵌套时按 mode priority 排序（后期 Phase 2）

---

### 改动 3：`PluginApi.register_runtime_hook()`

**目标**：让插件能注册 runtime 8-phase hook。

- ⬜ 3.1 在 `PluginApi` 新增 `register_runtime_hook(hook: HookBase)` 方法
- ⬜ 3.2 startup hook 中将 hook 注册到每个 workspace 的 `HookRegistry`
- ⬜ 3.3 workspace_created hook 中对新 workspace 也注册
- ⬜ 3.4 单测：hook 注册到指定 phase + 执行顺序正确

---

### 改动 4：动态命令广播

**目标**：插件注册的命令在 ACP 协议 + Console 前端中可见。

- ⬜ 4.1 修改 ACP `_build_available_commands()` 为动态读取 workspace `SlashCommandRegistry.names()`
- ⬜ 4.2 过滤掉 `_ACP_REDUNDANT_COMMANDS` 中的命令
- ⬜ 4.3 ACP 方法需接收 session_id → 定位 workspace → 获取 registry
- ⬜ 4.4 Console 新增 `/api/commands/available` endpoint（或在 session init 携带）
- ⬜ 4.5 前端改为从 API 获取命令列表替代硬编码
- ⬜ 4.6 单测：插件注册的命令出现在 ACP 广播 + API 响应中

---

### 改动 5：`PluginApi.register_agent_stop_handler()` — Loop 核心

**目标**：当 agent 想停止时，stop handler 可以 BLOCK 并注入 continuation message（Rubric 机制）。

- ⬜ 5.1 定义 `StopAction` 枚举：`ALLOW` / `BLOCK`
- ⬜ 5.2 定义 `StopHandlerResult` dataclass：`action: StopAction` + `continuation_message: str` + `reason: str`
- ⬜ 5.3 在 `PluginApi` 新增 `register_agent_stop_handler(handler, *, priority, name)` 方法
- ⬜ 5.4 实现 handler 优先级链（priority 越低越优先）
- ⬜ 5.5 桥接实现（AgentScope Stop event 不存在时的 workaround）
- ⬜ 5.6 BLOCK 时将 `continuation_message` 作为 **user turn** 注入到下一轮
- ⬜ 5.7 单测：handler BLOCK → continuation 注入 → agent 继续新一轮

**Workaround 方案（AgentScope 无 Stop event）**：
- 在 `POST_RESPONSE` phase 新增检测 hook
- 检测 agent 回复是否为"完成类"信号（无 tool 调用 + 结尾语气 or 固定格式）
- 触发 stop handler 优先级链
- 如果 BLOCK → Runtime 启动新一轮 `run()` 调用，input 为 continuation_message

---

### 改动 6：Prompt 注入体系（3 层设计）

**目标**：支持 System Prompt / Context Injection / User Turn Injection 三层注入。

**参考 Claude Code**：CC 的 `additionalContext` 可从任何 hook 返回，注入位置取决于 hook 时机。CC 的 Stop hook `reason` 作为 continuation 触发新 turn。

#### (A) System Prompt 注入
- ⬜ 6.1 在 `PluginApi` 新增 `register_prompt_section(name, after, provider, *, priority, condition, agent_id)` 方法
- ⬜ 6.2 `priority` 参数（数字越小越靠前，默认 100）
- ⬜ 6.3 `condition` 参数（callable 返回 bool，loop 激活时才注入）
- ⬜ 6.4 同一 anchor 内按 priority 排序
- ⬜ 6.5 单测：priority 排序 + condition 过滤

#### (B) Context Injection（动态上下文追加）
- ⬜ 6.6 定义 `ContextInjection` dataclass：`content`, `source`, `priority`
- ⬜ 6.7 在 `HookContext` 新增 `context_injections: list[ContextInjection]`
- ⬜ 6.8 提供 `ctx.inject_context(content, *, priority, source)` 方法
- ⬜ 6.9 Runtime 组装 messages 时将 injections 按 priority 排序后作为 system reminder 插入
- ⬜ 6.10 单测：context injection 出现在 agent 可见 messages 中

#### (C) User Turn Injection（Stop handler 续命专用）
- ⬜ 6.11 `StopHandlerResult.continuation_message` 作为下一轮 user input
- ⬜ 6.12 不是 system prompt，而是新 user turn（agent 视为用户给了新指令）
- ⬜ 6.13 单测：BLOCK 后 continuation 作为 user message 触发新一轮

---

### 改动 7：`PluginApi.register_tool_call_observer()` + HITL 触发（Doom Loop 基建）

**目标**：每次 tool 调用完成后实时检测行为模式，doom loop 时升级到 HITL。

#### (A) Observer 注册
- ⬜ 7.1 定义 `DoomLoopSignal` 枚举：`OK` / `ESCALATE_HITL` / `FORCE_STOP`
- ⬜ 7.2 在 `ToolCoordinator` 新增 `_observers: list[Observer]`
- ⬜ 7.3 在 `_finalize_completed()` 中广播到所有 observers：`(tool_name, args, result, history)`
- ⬜ 7.4 在 `PluginApi` 新增 `register_tool_call_observer(observer, *, name)` 方法
- ⬜ 7.5 通过 startup hook 注册到 coordinator
- ⬜ 7.6 单测：observer 收到每次 tool call 完整信息

#### (B) Doom Loop 检测器
- ⬜ 7.7 实现 `DoomLoopDetector` 类：滑动窗口比较 action 模式相似度
- ⬜ 7.8 配置参数：`window_size`、`similarity_threshold`、`action`
- ⬜ 7.9 相似度计算：比较 tool_name + args hash
- ⬜ 7.10 单测：模拟重复 tool 调用，验证检测触发

#### (C) HITL 触发机制
- ⬜ 7.11 定义 `DoomLoopAlert` ACP 事件结构
- ⬜ 7.12 后端：observer 返回 ESCALATE_HITL → session-level `loop_paused = True`
- ⬜ 7.13 下一轮 `PRE_DISPATCH` hook 检测到 paused → SHORT_CIRCUIT + 等待用户输入
- ⬜ 7.14 ACP 发送 `DoomLoopAlert` 事件到前端
- ⬜ 7.15 前端弹窗 UI：继续 / 终止 / 给 agent 新指令
- ⬜ 7.16 用户选择通过正常 prompt 接口回传（`/loop-continue` 或 `/loop-stop`）
- ⬜ 7.17 单测：完整 HITL 链路

---

## 第二部分：前端交互设计（Slash Command Chip + Budget Selector）

### 交互 1：Slash Command 作为 Atomic Chip

**目标**：`/ralph` 不是逐字符输入的普通文本，而是一个**可整体选中/删除的 chip 组件**。

- ⬜ F.1 Chat Input 中输入 `/` 时弹出命令选择菜单（类似 Slack/Notion 的 slash menu）
- ⬜ F.2 选中命令后，在输入框中渲染为 **chip/tag**（有背景色 + 圆角 + 图标）
- ⬜ F.3 Chip 作为原子单元：按 Backspace 整体高亮 → 再按一次整体删除（不逐字符删）
- ⬜ F.4 Chip 后面是参数输入区域（自由文本）
- ⬜ F.5 Chip 视觉：左侧小图标（Lucide `Terminal` 或 `Play`）+ 命令名 + 右侧可选关闭按钮

**交互参考**：
```
┌─────────────────────────────────────────────────────┐
│ [⚡ /ralph]  实现用户登录功能，包含验证码...         │
│                                                     │
│                              [Budget: ●●○ Med] [▶]  │
└─────────────────────────────────────────────────────┘
```

---

### 交互 2：Budget Selector（费用预算选择器）

**目标**：每次触发 loop 时用户可直观选择资源预算（low/medium/high），预算是 loop 安全阀的核心维度。

- ⬜ F.6 Chat Input 右侧（或 chip 旁）显示 Budget 选择器
- ⬜ F.7 Budget 三档预设：

| 档位 | 标签 | 默认 max_tokens | 默认 max_cost_usd | 默认 max_iterations |
|---|---|---|---|---|
| **Low** | 轻量探索 | 100k | $1.0 | 10 |
| **Medium** | 标准任务 | 300k | $3.0 | 20 |
| **High** | 深度工作 | 500k+ | $5.0+ | 30+ |

- ⬜ F.8 选择器 UI：3 级滑块/分段控件（SegmentedControl），直接在 chat input 区域可点击
- ⬜ F.9 自定义选项：点击 "Custom" 弹出详细配置（具体数字）
- ⬜ F.10 Budget 选择和 slash command chip 绑定——作为命令参数的一部分传给后端
- ⬜ F.11 后端接收 budget 参数 → 映射到 loop config 的 `safety` 字段

**Budget 和 Loop 安全阀的关系**：
```json
{
  "safety": {
    "max_iterations": 20,
    "thinking_only_streak_limit": 3,
    "consecutive_error_limit": 5,
    "budget": {
      "max_tokens": 300000,
      "max_cost_usd": 3.0,
      "on_exceed": "hitl"
    }
  }
}
```

- ⬜ F.12 Loop 运行时实时统计 token/cost 消耗
- ⬜ F.13 接近 budget 时前端显示进度条/警告
- ⬜ F.14 超出 budget 时触发 `on_exceed` 动作（HITL 弹窗 or 自动终止）

---

### 交互 3：Loop Status 实时展示

- ⬜ F.15 Loop 激活后 chat 区域顶部显示 Loop Status Bar（loop 名称 + 当前迭代 + budget 消耗百分比）
- ⬜ F.16 Status Bar 中有 [Pause] [Stop] 按钮
- ⬜ F.17 Budget 消耗进度可视化（绿 → 黄 → 红渐变）

---

## 第三部分：Loop Skill Schema + LoopLoader

### Schema 定义

- ⬜ S.1 定义 `LoopSkillConfig` pydantic model（6 个维度 + budget 详细字段）
- ⬜ S.2 schema 验证：必填（slash_command + skill_prompt）+ 可选（rubric + state + doom_loop + safety）
- ⬜ S.3 budget 在 `safety` 字段内，包含 `max_tokens`, `max_cost_usd`, `on_exceed`

**完整 Schema**：
```json
{
  "name": "string (required)",
  "version": "1.0.0",
  "slash_command": "string (required)",
  "description": "string",

  "skill_prompt": "string (required)",

  "rubric": {
    "mode": "hard_check | soft_judge | none",
    "check_expression": "string (硬判断时)",
    "soft_judge_prompt": "string (软判断时)",
    "continuation_prompt": "string (BLOCK 时注入)"
  },

  "state": {
    "mode": "json_file | none",
    "filename": "string",
    "schema_hint": "string"
  },

  "doom_loop": {
    "enabled": true,
    "window_size": 3,
    "similarity_threshold": 0.8,
    "action": "hitl | force_stop | inject_correction",
    "hitl_message": "string"
  },

  "safety": {
    "max_iterations": 30,
    "thinking_only_streak_limit": 3,
    "consecutive_error_limit": 5,
    "budget": {
      "max_tokens": 500000,
      "max_cost_usd": 5.0,
      "on_exceed": "hitl | force_stop",
      "warning_threshold": 0.8
    }
  }
}
```

### LoopLoader

- ⬜ S.4 实现 `LoopLoader` 类
- ⬜ S.5 `load(config_path)` → 解析 JSON → 调用 7 个基建 API
- ⬜ S.6 budget 参数传递：前端 Budget Selector 选择 → 覆盖 config 中默认 safety 值
- ⬜ S.7 单测：完整 config 加载 + 所有注册正确触发

---

## 第四部分：Loop Designer 前端页面

### 4.1 配置表单
- ⬜ D.1 新建 Loop Designer 页面路由
- ⬜ D.2 6 区域配置表单（触发 / Skill Prompt / Rubric / State / Doom Loop / 安全阀+Budget）
- ⬜ D.3 模板加载（Ralph / Deep Interview / Ultrawork / Browser Mission / 自定义）
- ⬜ D.4 Save → 调用后端 API 保存 JSON + 触发 LoopLoader

### 4.2 AI 辅助
- ⬜ D.5 "描述你想要的循环" 输入框 + AI 生成按钮
- ⬜ D.6 LLM 生成 6 维度配置 → 填充表单

### 4.3 Preview
- ⬜ D.7 预览生成的 SKILL.md
- ⬜ D.8 预览 Stop handler / Doom Loop 逻辑

---

## 第五部分：预置 Loop 模式

### 5.1 Deep Interview（最简循环，仅 prompt 注入）
- ⬜ L.1 编写 `deep-interview.json` loop config
- ⬜ L.2 SKILL.md：苏格拉底式提问 + ambiguity 评分
- ⬜ L.3 集成测试：`/deep-interview` → prompt 注入 → 循环提问

### 5.2 Ralph（持久完成循环）
- ⬜ L.4 编写 `ralph.json` loop config
- ⬜ L.5 State file IO：`.qwenpaw/loop_state/ralph.json`
- ⬜ L.6 Stop handler：检查 stories done
- ⬜ L.7 Doom loop 检测
- ⬜ L.8 Budget 约束（安全阀）
- ⬜ L.9 集成测试

### 5.3 Ultrawork（并行委派）
- ⬜ L.10 编写 `ultrawork.json` loop config
- ⬜ L.11 Stop handler：检查 todos 清空
- ⬜ L.12 集成测试

---

## 关键设计决策

### Q1: AgentScope Stop Event 不存在时如何实现 "阻止退出"？

**方案**：在 `POST_RESPONSE` phase 新增 hook：
1. 检测 agent 回复是否为"完成类"信号（无 tool 调用 + 结尾语气/固定格式）
2. 遍历 stop handlers（按 priority 排序）
3. BLOCK → `continuation_message` 作为下一轮 user input 注入
4. Runtime 启动新一轮 `run()` 调用

### Q2: Doom Loop "每次 tool 调用后" 如何接入？

**方案**：扩展 `ToolCoordinator._finalize_completed()` 后广播到 `_observers`。Observer 和 completion_handler 的区别：
- completion_handler: 只收 `ToolCallEntry`
- observer: 收 `(tool_name, args, result, history)` + 可返回 `DoomLoopSignal`

### Q3: HITL 暂停机制？

**方案**：
1. Observer 返回 ESCALATE_HITL → session `loop_paused = True`
2. 下一轮 `PRE_DISPATCH` hook → SHORT_CIRCUIT + ACP 事件
3. 前端弹窗 → 用户选择 → 回传 `/loop-continue` 或 `/loop-stop`

### Q4: 前端命令动态加载？

**方案**：ACP 的 `available_commands` 改为动态读取 registry + 增加 REST endpoint

### Q5: Loop state 文件？

**方案**：`{workspace_dir}/.qwenpaw/loop_state/{loop_name}.json`

### Q6: Prompt 注入 3 层 vs Claude Code additionalContext？

| 层 | 用途 | 对标 CC |
|---|---|---|
| System Prompt | SKILL.md 角色/规则（静态） | CLAUDE.md |
| Context Injection | 动态上下文追加到对话 | `additionalContext` |
| User Turn Injection | Stop BLOCK 续命 | Stop hook `reason` |

QwenPaw 区分 3 层的优势：in-process Python 更精确控制注入位置，priority 解决隐式依赖，多 loop 同时激活时调试更清晰。

### Q7: Budget 如何实时追踪？

**方案**：
1. 每轮 LLM 调用后统计 `usage.prompt_tokens` + `usage.completion_tokens`
2. 通过 provider 返回的 usage 数据累加到 loop session state
3. 费用估算：token × model price_per_token
4. 接近 `warning_threshold`（默认 80%）时发送 ACP 事件给前端显示警告
5. 达到上限时触发 `on_exceed` 动作

### Q8: Slash Command Chip 的技术实现？

**方案**：
- 使用 contentEditable div 或 ProseMirror/TipTap 富文本编辑器
- `/` 触发时渲染一个 inline non-editable node（chip）
- Chip 内部存储 command metadata（name + budget 等）
- Backspace 行为：光标紧贴 chip 时第一次选中（高亮），第二次删除
- 提交时从 chip 中提取结构化数据传给后端 API

---

## 实施优先级与依赖

```
改动1 (slash_command) ──┐
改动6A (prompt_section) ┼──→ 第5部分 L.1-L.3 (Deep Interview) → 验收 P0
改动4 (动态广播)        ┘
                                    │
改动5 (stop_handler)   ──┐          ▼
改动3 (runtime_hook)    ─┼──→ 第5部分 L.4-L.9 (Ralph + Budget) → 验收 P1
改动6C (user turn inj)  ┘
                                    │
改动7A (observer)    ────┐          ▼
改动7B (detector)    ────┼──→ 改动7C (HITL) → 验收 P1.5
                         │
改动2 (mode)       ──────┤
第3部分 (schema+loader) ─┼──→ 验收 P2（手写 JSON loop 可用）
                         │
前端 F.1-F.5 (chip)  ────┤
前端 F.6-F.14 (budget) ──┼──→ 验收 P2+（完整前端交互）
前端 F.15-F.17 (status) ─┘
                                    │
                                    ▼
                         第4部分 (Loop Designer 页面) → 验收 P3
```

---

## 风险与约束

| 风险 | 影响 | 缓解 |
|---|---|---|
| AgentScope 无 Stop event | 改动5需 workaround | POST_RESPONSE hook 检测"完成信号" |
| Agent 不发出明确完成信号 | Stop handler 无法可靠触发 | SKILL.md 中指示 agent 完成时输出固定格式 |
| Budget 追踪精度（streaming 时 usage 延迟） | 可能超出 budget 几% | warning_threshold=0.8 提前预警 |
| Doom Loop 误报 | 用户体验差 | 高 threshold + HITL 让用户选择 |
| Chat Input chip 实现复杂度 | 需要富文本编辑器 | 用 TipTap/ProseMirror 或退而求其次用 react-tag-input |
| 多 loop 嵌套优先级 | handler 冲突 | priority 链 + circuit breaker |

---

## 预估工时

| 阶段 | 预估 | 说明 |
|---|---|---|
| 改动 1-3（Plugin API 基建） | 2 天 | 3 个方法 + startup/workspace hook |
| 改动 4（动态广播） | 1 天 | ACP + REST endpoint |
| 改动 5（Stop handler + workaround） | 2 天 | POST_RESPONSE hook + user turn 注入 |
| 改动 6（Prompt 3 层注入） | 2 天 | system + context + user turn |
| 改动 7（Observer + Doom Loop + HITL） | 3 天 | Coordinator 扩展 + 检测器 + 前端弹窗 |
| 前端 Chip + Budget（F.1-F.14） | 3 天 | 富文本 chip + budget selector + 实时追踪 |
| 前端 Loop Status（F.15-F.17） | 1 天 | Status bar + 进度条 |
| 第3部分 Schema + LoopLoader | 2 天 | Pydantic model + 加载器 |
| 第4部分 Loop Designer 页面 | 3-4 天 | 6 区域表单 + 模板 + AI |
| 第5部分 预置 Loop 模式 | 2 天 | 3 个 JSON config + 集成测试 |
| **合计** | **21-23 天** | |

---

## 验收标准

### P0 验收（改动1 + 4 + 6A + L.1-L.3）
- [ ] 插件注册 `/deep-interview` 后，chat 输入可触发循环
- [ ] ACP / Console 动态显示 `/deep-interview`
- [ ] SKILL.md 内容注入到 system prompt

### P1 验收（改动5 + 3 + 6C + L.4-L.9）
- [ ] `/ralph` 触发后 agent 持续工作
- [ ] Stop handler 检查 state → BLOCK → continuation 注入 → agent 继续
- [ ] Budget 约束生效：超出 max_tokens 或 max_cost 时触发 HITL

### P1.5 验收（改动7）
- [ ] 连续 N 轮相同操作 → Doom Loop 检测 → HITL 弹窗
- [ ] 用户选择继续/终止/给新指令 → 正确响应

### P2 验收（第3部分）
- [ ] 手写 `my-loop.json` → LoopLoader 加载 → `/my-loop` 可用
- [ ] 6 维度 + budget 正确翻译为基建 API 调用

### P2+ 验收（前端交互）
- [ ] `/ralph` 在输入框渲染为 atomic chip
- [ ] 按 Backspace 整体删除 chip
- [ ] Budget selector 可选 Low/Med/High
- [ ] Loop 运行时 Status Bar 显示迭代次数 + budget 消耗百分比
- [ ] 接近 budget 上限时进度条变色 + 警告

### P3 验收（第4部分 Loop Designer）
- [ ] 可视化配置 6 维度 + Save 生成 JSON
- [ ] 预置模板一键加载
