# Browser Mission Loop Plugin

将"浏览器自动化循环"从 QwenPaw 内置 loop 技能独立为标准插件。

## 概述

`browser-mission` 是一个 **loop 类型**的插件，通过 QwenPaw 的 Plugin API + Loop Engineering 基础设施运行。它注册 `/browser-mission` 斜杠命令，让 Agent 进入持久循环模式，驱动浏览器完成多步 Web 任务。

## 目录结构

```
plugins/browser-mission/
├── plugin.json   # 插件清单 (元数据、入口、依赖)
├── plugin.py     # 插件入口 + LoopSkillConfig 定义
└── README.md     # 本文件
```

## 实现原理

### 1. 插件加载

QwenPaw 启动时扫描 `plugins/` 目录，读取 `plugin.json` 中的 `entry_point`，实例化 `plugin.py` 中导出的 `plugin` 对象，调用 `plugin.register(api)`.

### 2. LoopSkillConfig 声明

`plugin.py` 内定义了一个字典 `LOOP_SKILL_CONFIG`，遵循 `qwenpaw.loop.schema.LoopSkillConfig` 的结构：

| 字段 | 用途 |
|------|------|
| `trigger.slash_command` | 注册 `/browser-mission` 斜杠命令 |
| `skill_prompt` | Agent 进入循环后注入的系统提示词 |
| `rubric.continue_prompt` | 每轮迭代结束后的续行提示 |
| `rubric.max_iterations` | 最大迭代次数 (20) |
| `rubric.stop_phrases` | Agent 输出含这些短语时自动停止循环 |
| `state.persist_key` | 状态持久化的 key |
| `state.schema` | 状态初始结构 (url/步骤/错误等) |
| `doom_loop` | 毁灭循环检测：滑窗=6，相似度阈值=0.8，超出后进入 HITL |
| `safety.budget` | 预算安全阀：max 200k token / $2.0，超出后 ask_human |

### 3. LoopLoader 翻译

`register()` 方法通过 `LoopLoader` 将声明式 config 翻译为一系列命令式 `PluginApi` 调用：

```
LoopLoader.load(config)
  ├─ api.register_slash_command("browser-mission", ...)
  ├─ api.register_mode("browser-mission", ...)
  ├─ api.register_agent_stop_handler(...)
  ├─ api.register_prompt_section(layer="system", ...)
  ├─ api.register_tool_call_observer(...)  # doom loop 检测
  └─ api.register_runtime_hook("post_llm_call", ...)  # stop phrase 检测
```

### 4. 运行时行为

用户在前端 Chat 输入框中选择 `/browser-mission`（或手动输入），前端会：
1. 显示一个原子化的命令 Chip + 预算选择器
2. 发送消息时自动在文本前注入 `/browser-mission ` 前缀

后端接收到带 `/browser-mission` 前缀的消息后：
1. 匹配到已注册的 slash command → 激活 "browser-mission" mode
2. 注入 `skill_prompt` 到 system 层
3. Agent 开始执行浏览器操作
4. 每轮结束后，stop handler 拦截停止信号，注入 `continue_prompt` 继续下一轮
5. **Doom Loop 检测**：若连续 6 次 tool call 的相似度 ≥ 0.8，触发 HITL 干预
6. **预算控制**：token 或费用超限后触发 `ask_human`
7. 当 Agent 输出 `TASK_COMPLETE` / `MISSION_DONE`，或达到 `max_iterations`，循环自动终止

## 自定义

修改 `plugin.py` 中的 `LOOP_SKILL_CONFIG` 字典即可调整：
- 提示词 (`skill_prompt`, `rubric.continue_prompt`)
- 迭代上限 (`rubric.max_iterations`)
- 停止关键词 (`rubric.stop_phrases`)
- 毁灭循环灵敏度 (`doom_loop.window_size`, `doom_loop.similarity_threshold`)
- 预算上限 (`safety.budget.max_tokens`, `safety.budget.max_cost_usd`)

## 最低版本要求

QwenPaw >= 2.0.0 (需要 Loop Engineering 基础设施)
