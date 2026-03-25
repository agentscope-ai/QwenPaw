# CoPaw 协作规范与自动继承说明

## 必要约定（建议每次对话自动加载）

1. 双主线协作模式（docs/devops/dual-track-sop.SKILL.md）
   - 分支管理、同步、PR拆分、冲突处理、操作Checklist
2. 路线图与开发计划（docs/devops/ROADMAP.md、FORK_ROADMAP.md、daily/）
   - 主路线图同步 upstream，fork扩展路线图记录本地特性与兼容性
   - 每日/周/月/年度计划与报告均按日期/周期命名，集中存放
3. 自动化脚本与数据（docs/devops/sync_roadmap.sh、sync_pr_issue.sh、upstream_prs.json等）
   - 路线图、PR/issue自动抓取与合并，辅助制定开发任务
4. 协作技能与联动（docs/devops/copilot-instructions.md、dual-track-sop.SKILL.md）
   - 所有协作、提交、分支操作均受技能约束，自动弹出SOP提示与Checklist
5. 目录结构与说明（docs/devops/README.md）
   - 所有协作、管理、报告、自动化脚本均集中于 docs/devops/，与功能代码区分
6. 用户偏好与历史经验（建议写入 README 或 /memories/ 下）
   - 重要流程、决策、团队约定、历史经验建议集中记录，便于自动继承

## 自动继承机制

- 每次对话开始时，优先读取 docs/devops/README.md、dual-track-sop.SKILL.md、copilot-instructions.md、ROADMAP.md、FORK_ROADMAP.md、daily/ 下最新计划与任务。
- 若有 /memories/ 下的用户偏好、历史经验，也自动加载。
- 所有协作、开发、发布、报告、自动化流程均按上述规范执行。
- 新成员或新对话可快速了解并继承全部约定，无需重复沟通。

---

> 本说明文件建议长期维护，遇到新流程、规范、经验及时补充，保障协作体系自动继承与规范执行。
