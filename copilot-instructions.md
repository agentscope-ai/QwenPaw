---
title: CoPaw 协作技能联动说明
scope: repo
keywords: [技能联动, hooks, instructions, 自动化, checklist, SOP, 流程编排]
description: 本文件用于配置 CoPaw 项目协作技能自动联动，确保所有开发、同步、提交、PR 操作自动弹出规范提示与操作建议。包含分支管理 SOP 与流程编排规范。
---

## 技能联动配置方案

### 1. 分支管理与 SOP
自动加载 dual-track-sop.SKILL.md，所有分支管理、同步、PR、冲突处理场景自动弹出 SOP 提示。

### 2. 流程编排规范（Pipeline Specification）
Agent 技能库内置流程编排指南 `pipeline-orchestration-specification`，在以下场景自动激活：
- 创建、编辑或讨论流程模板（pipeline templates）
- 定义工作流步骤（workflow orchestration step）
- 调试流程执行问题（pipeline runtime issues）
- 验证流程 JSON 格式（schema validation）
- 组建流程最佳实践（pipeline composition patterns）

位置：`src/copaw/agents/skills/pipeline/`
- `SKILL.md` — 完整规范、JSON schema、验证规则、最佳实践
- `example-*.json` — 常见模式参考实现（简单线性、质量门、双语对齐、分析报告）

### 3. 钩子（hooks）配置
- pre-commit、pre-push、post-checkout 等操作自动触发技能检查与提示。
- hooks 文件可放在 .github/hooks/，如 pre-commit.json、pre-push.json。

### 4. 工作区 instructions 配置
- copilot-instructions.md 文件（本文）声明技能联动规则。
- 统一 applyTo patterns，确保技能在相关上下文自动生效。

### 5. Checklist 自动弹出
- 每次开发、PR、同步、冲突处理等关键节点，自动弹出操作清单。

### 6. 技能互相调用
- PR 检查、分支清理等技能自动调用 dual-track-sop.SKILL.md，确保 SOP 规范。
- 流程编排对话自动引用 pipeline-orchestration-specification，确保模板生成准确。

---

## 示例 copilot-instructions.md

```
# CoPaw 协作技能自动联动

applyTo:
  - "feat/upstream/*"
  - "feat/fork/*"
  - "fork/main"
  - "mirror/upstream-main"
  - "git push"
  - "git checkout"
  - "git rebase"
  - "git merge"
  
# 流程相关操作
  - "*pipeline*"
  - "*workflow*"
  - "*orchestration*"

skills:
  - dual-track-sop.SKILL.md
  - pipeline-orchestration-specification

hooks:
  - .github/hooks/pre-commit.json
  - .github/hooks/pre-push.json
  - .github/hooks/post-checkout.json

checklist:
  # 分支管理
  - "开发前：fetch/prune、更新镜像线、更新 fork 主线、按目标切分支"
  - "PR前：确认分支基于镜像线、无 fork 私有改动、测试通过、推送并创建 PR"
  
  # 流程编排
  - "创建流程模板前：查阅流程规范、选择合适的 step kind、确保 ID 唯一性"
  - "流程测试前：验证 JSON 格式、检查步骤顺序、确认描述清晰"
  - "发布流程前：版本控制、归档示例、更新知识库引用"
```

---

## 快速参考

### 何时触发流程编排技能？

| 场景 | 触发器 | 参考技能 |
|------|--------|---------|
| 创建新流程模板 | "创建 pipeline"、"新增工作流" | pipeline-orchestration-specification |
| 编辑现有流程 | "修改步骤"、"调整流程顺序" | pipeline-orchestration-specification |
| 流程运行失败 | "pipeline 错误"、"流程执行问题" | pipeline-orchestration-specification + 运行日志 |
| 设计工作流架构 | "流程设计"、"步骤规划" | pipeline-orchestration-specification |
| 验证流程定义 | "检查 JSON"、"验证格式" | pipeline-orchestration-specification |

### 快捷查看流程规范

```bash
# 查看完整规范
cat src/copaw/agents/skills/pipeline/SKILL.md

# 查看示例流程
cat src/copaw/agents/skills/pipeline/example-*.json
```

---

> 如需自动化脚本或更多 hooks，可按需扩展。最新版本的流程规范维护在上述 Agent 技能目录位置。
