# Browser Mission Loop Plugin

将"浏览器自动化循环"从 QwenPaw 内置 loop 技能独立为标准插件。

## 概述

`browser-mission` 是一个 **loop 类型**的插件，通过 QwenPaw 的 Plugin API + Loop Engineering 基础设施运行。它注册 `/browser-mission` 斜杠命令，让 Agent 进入持久循环模式，驱动浏览器完成多步 Web 任务。

## 目录结构

```
plugins/browser-mission/
├── plugin.json   # 插件清单 (元数据、入口、依赖)
├── plugin.py     # 插件入口 + LoopSkillConfig 定义
├── SKILL.md      # Agent skill prompt
└── README.md     # 本文件
```

## 实现原理

### 1. 插件加载

QwenPaw 启动时扫描 `plugins/` 目录，读取 `plugin.json` 中的 `entry_point`，实例化 `plugin.py` 中导出的 `plugin` 对象，调用 `plugin.register(api)`.

### 2. LoopSkillConfig 声明

`plugin.py` 内定义了一个字典 `LOOP_SKILL_CONFIG`，遵循 `qwenpaw.loop.schema.LoopSkillConfig` 的结构：

| 字段 | 用途 |
|------|------|
| `slash_command` | 注册 `/browser-mission` 斜杠命令 |
| `skill_prompt` | 从 `SKILL.md` 读取，注入为系统提示词 |
| `rubric.mode` | `hard_check` — 基于 state 文件字段检查 |
| `rubric.check_expression` | `stories.every(s => s.passes \|\| s.blocker_reason)` |
| `rubric.continuation_prompt` | 每轮迭代结束后的续行提示 |
| `state.mode` | `json_file` — 持久化到 JSON 文件 |
| `state.filename` | `browser-mission-state.json` |
| `doom_loop.window_size` | 6 — 滑窗大小 |
| `doom_loop.similarity_threshold` | 0.8 — 相似度阈值 |
| `safety.max_iterations` | 20 — 最大迭代次数 |
| `safety.budget.max_tokens` | 300,000 — token 上限 |
| `safety.budget.max_cost_usd` | 3.0 — 费用上限 |

### 3. LoopLoader 翻译

`register()` 方法通过 `LoopLoader` 将声明式 config 翻译为一系列命令式 `PluginApi` 调用：

```
LoopLoader.load(config)
  ├─ api.register_slash_command("browser-mission", ...)
  ├─ api.register_prompt_section("loop-skill-browser-mission", ...)
  ├─ api.register_agent_stop_handler(...)  # rubric + budget
  ├─ api.register_tool_call_observer(...)  # doom loop 检测
  └─ api.register_runtime_hook(HitlPauseHook())  # HITL 暂停
```

### 4. 运行时行为

用户在前端 Chat 输入框中选择 `/browser-mission`（或手动输入），前端会：
1. 显示一个原子化的命令 Chip + 预算选择器
2. 发送消息时自动在文本前注入 `/browser-mission ` 前缀

后端接收到带 `/browser-mission` 前缀的消息后：
1. 匹配到已注册的 slash command → 激活 "browser-mission" mode
2. 注入 `skill_prompt`（SKILL.md 内容）到 system 层
3. Agent 开始执行浏览器操作
4. 每轮结束后，stop handler 拦截停止信号：
   - 读取 `.qwenpaw/loop_state/browser-mission-state.json`
   - 检查 `stories.every(s => s.passes || s.blocker_reason)`
   - 若通过 → ALLOW（loop 结束）
   - 若未通过 → BLOCK（注入 continuation_prompt 继续下一轮）
5. **Doom Loop 检测**：若连续 6 次 tool call 的相似度 ≥ 0.8，触发 HITL 干预
6. **预算控制**：token 超限后触发 HITL
7. 达到 `max_iterations` 时循环自动终止

## 自定义

修改 `plugin.py` 中的 `LOOP_SKILL_CONFIG` 字典即可调整：
- 提示词 (`skill_prompt` / `rubric.continuation_prompt`)
- 迭代上限 (`safety.max_iterations`)
- 毁灭循环灵敏度 (`doom_loop.window_size` / `doom_loop.similarity_threshold`)
- 预算上限 (`safety.budget.max_tokens` / `safety.budget.max_cost_usd`)

## 最低版本要求

QwenPaw >= 2.0.0 (需要 Loop Engineering 基础设施)
