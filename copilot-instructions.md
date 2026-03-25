---
title: CoPaw 协作技能联动说明
scope: repo
keywords: [技能联动, hooks, instructions, 自动化, checklist, SOP]
description: 本文件用于配置 CoPaw 项目协作技能自动联动，确保所有开发、同步、提交、PR 操作自动弹出规范提示与操作建议。
---

## 技能联动配置方案

1. 自动加载 dual-track-sop.SKILL.md，所有分支管理、同步、PR、冲突处理场景自动弹出 SOP 提示。
2. 钩子（hooks）配置：
   - pre-commit、pre-push、post-checkout 等操作自动触发技能检查与提示。
   - hooks 文件可放在 .github/hooks/，如 pre-commit.json、pre-push.json。
3. 工作区 instructions 配置：
   - copilot-instructions.md 文件声明技能联动规则。
   - 统一 applyTo patterns，确保 dual-track-sop.SKILL.md 在所有 git 操作、分支切换、PR 提交时自动生效。
4. Checklist 自动弹出：
   - 每次开发、PR、同步、冲突处理等关键节点，自动弹出操作清单。
5. 技能互相调用：
   - PR 检查、分支清理等技能自动调用 dual-track-sop.SKILL.md，确保 SOP 规范。

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

skills:
  - dual-track-sop.SKILL.md

hooks:
  - .github/hooks/pre-commit.json
  - .github/hooks/pre-push.json
  - .github/hooks/post-checkout.json

checklist:
  - "开发前：fetch/prune、更新镜像线、更新 fork 主线、按目标切分支"
  - "PR前：确认分支基于镜像线、无 fork 私有改动、测试通过、推送并创建 PR"
```

---

> 如需自动化脚本或更多 hooks，可按需扩展。
