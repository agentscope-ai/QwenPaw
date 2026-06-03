---
name: memory-distill
description: 智能记忆蒸馏工具。通过标题差集检测从每日笔记中发现真正的新信息（~92%去噪），增量追加到 MEMORY.md，避免冗余存储。适合周期性记忆整理。
metadata:
  builtin_skill_version: "1.0"
  qwenpaw:
    emoji: "🧠"
---

# 记忆蒸馏

## 什么时候用

当需要**整理和压缩记忆**时使用本 skill：

### 应该使用
- 代理发现 MEMORY.md 和 daily notes 之间的信息重复
- 用户要求"整理一下记忆"、"蒸馏一下笔记"
- 定期维护（例如每 7-15 天整理一次）
- 需要快速了解当前记忆健康状况

### 不应使用
- 只是需要搜索已有记忆 → 用 `memory_search`
- 只是需要记录单条信息 → 直接更新 MEMORY.md 或 daily note
- 完全不需要记忆管理的时候

## 可用工具

本 skill 提供三个工具函数（通过 `memory-distill` 插件注册）：

| 函数 | 用途 | 常用参数 |
|:---|:---|---:|
| `distill_memory()` | 标题差集蒸馏 — 扫描每日笔记，发现新信息 | `days=7`, `dry_run=True` |
| `consolidate_memory()` | 全流程整理 — 蒸馏→归档→清理→审计 | `days=15`, `dry_run=True` |
| `inspect_memory()` | 快速健康检查 | 无参数 |

## 使用流程

### 1. 先检查记忆健康
```python
result = await inspect_memory()
```

### 2. 预览蒸馏结果（推荐先 dry-run）
```python
result = await distill_memory(days=7, dry_run=True)
```

### 3. 确认后执行蒸馏
```python
result = await distill_memory(days=7, dry_run=False)
```

### 4. 完整整理流程
```python
# 每 15 天执行一次完整整理
result = await consolidate_memory(days=15, dry_run=False)
```

## 核心原理

1. **标题差集检测**：从 MEMORY.md 提取加粗关键词和 `###` 标题作为"已知话题"，与 daily notes 的 `##` 标题比对
2. **模板过滤**：自动跳过 15+ 个常见模板标题（如"计划"、"进展"、"关键决策"）
3. **增量追加**：新发现追加到 `🔄 Auto Discovery` 独立段落，不重写 MEMORY.md
4. **~92% 去噪率**：相比纯 LLM 驱动的方式大幅减少冗余

## 注意事项

- 始终先 `dry_run=True` 预览结果，确认后再执行
- 不会删除任何原始 daily notes（仅选择性追加到 MEMORY.md）
- `consolidate_memory` 会归档旧日志文件到 `archive/` 目录
