# Autopilot Loop Plugin

多阶段自治循环 — 从 brief 到 working code 的完整自动化 pipeline。

## 使用方法

在 Chat 中输入 `/autopilot <任务简述>`。

## 6 个阶段

1. Expansion → 2. Planning → 3. Execution → 4. QA → 5. Validation → 6. Complete

每个阶段转换都更新 state file，循环在 `phase === "complete"` 时退出。
