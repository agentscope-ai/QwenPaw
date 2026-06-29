# Ralph Loop Plugin

持久完成循环 — 将任务分解为 stories，逐个完成并由 architect subagent 验证。

## 使用方法

在 Chat 中输入 `/ralph <任务描述>`，Agent 将进入 Ralph 循环模式。

## 循环流程

1. 收到任务 → 分解为 stories → 写入 `ralph-state.json`
2. 逐个执行 story → 完成后 spawn architect subagent review
3. Review 通过 → 标记 `verified: true` → 继续下一个 story
4. 所有 stories 完成且验证 → 循环自动退出

## 配置

见 `plugin.py` 中的 `LOOP_SKILL_CONFIG`。
