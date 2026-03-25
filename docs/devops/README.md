# CoPaw 协作与报告目录说明

## 目录结构

- docs/devops/
  - ROADMAP.md：主路线图（同步 upstream + fork 扩展）
  - FORK_ROADMAP.md：fork 扩展路线图与兼容性约束
  - DAILY_PLAN_TEMPLATE.md：每日开发计划模板
  - DAILY_PLAN_YYYY-MM-DD.md：每日开发计划（按日期命名）
  - DAILY_PLAN_AUTOMATION.md：每日计划自动化说明与脚本示例
  - WEEKLY_REPORT_AUTOMATION.md：周报自动化说明与脚本示例
  - WEEKLY_REPORT_YYYY-WW.md：周报（按周命名）
  - MONTHLY_REPORT_AUTOMATION.md：月报自动化说明与脚本示例
  - MONTHLY_REPORT_YYYY-MM.md：月报（按月命名）
  - YEARLY_REPORT_AUTOMATION.md：年度报告自动化说明与脚本示例
  - YEARLY_REPORT_YYYY.md：年度报告（按年命名）
  - dual-track-sop.SKILL.md：双主线协作技能
  - copilot-instructions.md：技能联动说明
  - sync_roadmap.sh：路线图同步脚本
  - sync_pr_issue.sh：PR/issue梳理脚本
  - upstream_prs.json / upstream_issues.json / fork_prs.json / fork_issues.json：自动抓取 PR/issues 数据

## 使用建议

- 所有协作、管理、报告、自动化脚本均集中于 docs/devops/，与功能代码区分。
- 每日/周/月/年度计划与报告均可自动生成，便于团队协作、进度追踪、历史复盘。
- 路线图、技能、协作规范、贡献计划等均可随时补充、调整。
- 自动化脚本支持批量抓取、汇总、生成报告，提升管理效率。

---

> 本目录说明便于新成员快速了解协作体系，支持持续优化与扩展。
