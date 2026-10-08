# QwenPaw Evaluation 开发 checklist

基线：`upstream/main`，`f38953469`；分支：`feat/bench`。

设计依据：[评测页面与实现方案](qwenpaw-evaluation-preview.html)。
HTML 中的成绩、历史版本、费用与私榜组合都是 mock，不是实测或兼容性证明。

## 已确认范围

- 不创建根目录 `evaluation/`；YAML 放 `.github/bench/`，辅助脚本放 `scripts/bench/`，uv 隔离依赖；复用 Harbor 的 ACP agent 接口。
- 本期只采用确认已有 Harbor adapter 的 GAIA validation、SpreadsheetBench Verified、SWE-bench Verified，各占 1/3；领域子榜按 benchmark 标签等权，保留单 benchmark 榜。
- PawBench、Claw-Eval 未确认现成 Harbor 接入，暂不加入；AppWorld 移除。允许 benchmark 间题目重叠。
- 六个百炼模型：`qwen3.8-max-0902`、`qwen3.8-27b`、`deepseek-v4-pro-0813`、`deepseek-v4.1-flash`、`glm-5.3`、`glm-5.2`；账户可用性、协议兼容性和版本信息须验证。
- 每 release 公开运行 QwenPaw × 六模型 × 三 benchmark，共 6,390 个 task-trial，不含环境重试。每模型 1,065 题、9 批，每批最多 128 行；模型间串行，批内初始并发 8。
- 所有执行阶段由 GitHub Actions 编排，一 task-trial 一个 GitHub-hosted runner。保留上游任务预算；先验收镜像、磁盘、内存与全阶段耗时，不预设标准 runner 已足够。self-hosted 仅保留扩展点。
- parity、对比和归因离线完成。私榜按 model × harness × SDK 版本组织；Codex、Claude Code、DeepSeek Harness 的组合先验证，不将 mock 当成已支持。
- 费用、耗时、轨迹和配置与分数一起归档；复用 website 部署流程。公开导出不能包含私有数据。
- 图展示模型及 SDK 版本历史，高亮同模型最高分；私榜按 model × harness 高亮。表格保留各 SDK 版本完整记录，不只显示最佳历史运行。

## 实施与验收

- [x] 拉取最新 upstream/main，创建独立 worktree 和 feat/bench。
- [x] 带入已确认 HTML 方案，明确本期范围。
- [x] 核查主线 ACP 接口，固定 Harbor 0.24.0 原生 JobConfig。
- [x] 创建三份 YAML 配置及三个 workflow，不修改产品依赖。
- [x] 实现任务冻结、单题 ACP 调用和 receipt 归一化。
- [x] 实现九批串行、单题独立 runner、artifact 隔离。
- [x] 实现等权汇总、覆盖率校验、费用未知与公开字段白名单。
- [x] 单测 16 项通过，ruff 与 actionlint 通过。
- [ ] 三个 benchmark 的真实容器与模型 API 验收；本机 Docker daemon 不可用。
- [ ] 固定跨 release 数据/镜像/传递依赖，离线完成模型协议与 parity 验收。
- [ ] 实现基础设施失败自动恢复，完成工具/judge/基础设施费用对账。
- [ ] 私有其他 harness 的实际运行接入。
- [ ] 网站 SDK 历史页、结果持久化与自动部署。

当前实现配置、调度和汇总基础链路；未启动真实模型调用、未发布网站。详见 [.github/bench/README.md](../../.github/bench/README.md)。HTML 成绩仍为 mock。
