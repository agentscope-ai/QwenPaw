---
title: CoPaw 双主线协作技能
scope: repo
keywords: [分支管理, upstream, fork, PR, cherry-pick, rebase, git, checklist, 自动化, 冲突处理]
description: 本技能用于在 CoPaw 项目中自动化、规范化双主线协作流程，确保所有开发、同步、提交、PR 操作严格遵循双主线 SOP。
---

## 1. 分支管理规范
- `mirror/upstream-main`：只做上游镜像，禁止直接开发，始终对齐 `upstream/main`。
- `fork/main`：fork 主发布线，可包含自定义提交。
- `feat/upstream/*`：准备提交 upstream 的功能分支，必须从 `mirror/upstream-main` 切出。
- `feat/fork/*`：仅保留在 fork 的功能分支，从 `fork/main` 切出。

## 2. 日常同步流程
- 每次开发前，自动 fetch/prune origin/upstream。
- 自动更新 `mirror/upstream-main`（reset --hard），再 rebase `fork/main`。
- 冲突只在 `fork/main` 解决。

## 3. PR 提交与拆分
- PR 前自动检查分支来源，确保基于 `mirror/upstream-main`，无 fork 私有改动。
- 检查混合提交，建议 cherry-pick 拆分。
- 上游贡献建议拆分为“稳定性修复 PR”和“开发体验 PR”。

## 4. 冲突处理建议
- upstream 同步冲突优先在 `fork/main` 解决。
- PR 分支冲突时，优先 rebase `mirror/upstream-main` 后再推送。
- 多人协作时，历史已公开分支建议用 merge，避免强推风险。

## 5. 自动化脚本建议
- 提供一键同步、分支清理、cherry-pick 拆分脚本。
- 定期清理已合并分支与无用 stash。

## 6. 操作 Checklist
- 开发前：fetch/prune、更新镜像线、更新 fork 主线、按目标切分支。
- PR前：确认分支基于镜像线、无 fork 私有改动、测试通过、推送并创建 PR。

## 7. Skill 应用方式
- 本技能自动弹出 SOP 提示词，所有协作、提交、分支操作均受其约束。
- 可与其他协作技能联动，形成完整协作链。

---

> 本技能文件与 docs/dual-track-sop.md 保持一致，后续如 SOP 有更新需同步修改。
