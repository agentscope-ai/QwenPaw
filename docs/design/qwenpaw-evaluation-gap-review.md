# QwenPaw Evaluation 实现差距核对

核对日期：2026-10-08。依据：[初始方案](qwenpaw-evaluation-preview.html)。状态以 `feat/bench` 的实现和验证证据为准，原型勾选项不代表实现完成。

## 当前结论

调度、汇总和模型费用计算已有实现；**尚不能作为完成验收的正式发布系统**。网站代码仍在工作区，其他 harness 仍为 mock，未跑完整三项 × 六模型。不得将单题链路成功描述为 benchmark 完整验收。

## ACP 初始化修正

- [x] ACP 复用 `ensure_local_runtime_initialized(skip_bootstrap=True)`。新工作区不生成 `BOOTSTRAP.md`；原有 config、技能、PROFILE、MEMORY、HEARTBEAT 等照常准备。
- [x] ACP 不注册 BootstrapHook，不注入身份引导、不创建 `.bootstrap_completed`。
- [x] 普通 init 默认保留 BOOTSTRAP 模板；新增 `--skip-bootstrap` 用于非交互初始化。
- [x] 已有用户文件不删除或覆盖；因此**旧工作区已有 BOOTSTRAP.md 时文件仍存在**。正式评测的独立新容器才满足启动后不存在该文件的条件。
- [x] 48 项相关测试通过，包含真实空目录初始化、普通/跳过两种模式及重复执行；未重新发起付费 smoke。

## 按优先级补齐

| 优先级 | 初始方案要求 | 已有实现 | 未完成与验收条件 |
|---|---|---|---|
| P0 | 网站主榜、子榜、SDK 历史、费用图、方案页与国际化 | React 页面、官方 logo、中英文词条、mock 私榜已在工作区；真实数据默认空 | 完成浏览器交互/移动端/深链验收、正式构建和提交；图表筛选、费用拆解等与原型逐项对齐。不能把未提交页面算交付 |
| P0 | 完整正式执行 | 六模型、三个 benchmark、9 批/模型、每题独立 runner、并发 8、原生超时预检 | Spreadsheet/SWE 真实执行未验收；GAIA 仅单题；六模型权限、工具调用、视觉和附件政策未完整确认。还需重任务资源测量及完整覆盖运行 |
| P0 | 可重复的实验协议 | 单轮任务文件哈希、源码 SHA、Harbor/LiteLLM 主版本与价格快照 | 跨 release 固定 dataset revision、镜像 digest、传递依赖和 Actions SHA；记录模型实际响应版本、工具/skills/搜索政策。当前不能只凭 Index v1 判断两次运行可比 |
| P0 | 离线 parity | 方案明确在线 release 不跑 parity | 完成数据、scorer、ACP 接入和官方条件差异的离线报告；结果 schema/详情引用适用报告与配置摘要。无报告时标未覆盖，不写成已复现 |
| P0 | 费用与预算 | reported → LiteLLM → 价格快照 × usage；缓存、unknown/upper_bound；模型费用含允许尝试 | 缺按批次检查的费用上限与停止机制。工具/judge/infra 费用尚为 unknown；子 agent/重试 usage 完整性需要验收；补 cost/success、分阶段耗时及 P50/P95。已知模型小计不等于整轮账单 |
| P0 | 自动归档与网站发布 | `history.py` 不可变记录校验、bench-results 数据分支、串行更新、hydrate、统一 deploy workflow 已提交本地代码 | 尚未完成真实发布闭环验收；当前只长期保存白名单摘要，manifest/逐题 receipt 等仍依赖短期 artifacts。补长期审计材料、摘要校验和稳定证据链接；原始轨迹需私密归档并审查后公开 |
| P0 | 失败和未完成状态透明 | 基础设施最多补跑一次，不重试正常失败/agent timeout，保留 receipt attempt；缺题不出完整分 | 未完成结果目前只在 artifact，没有网站状态页；丢失 receipt 的费用可能 unknown。恢复 workflow 尚未 hosted 端到端验收 |
| P1 | 私榜 model × harness × SDK | 页面 mock 与 public/private 字段隔离已有草稿；public 导出拒绝 private | 实际执行仍写死 QwenPaw。尚无替代 harness adapter、私有调用/归档完整链路，公私 runner 规格 parity 未验证。先跑通一个替代 harness，再扩到其他 |
| 后续 | self-hosted 扩展、记忆/异步专项 | 设计保留方向 | runner 标签目前硬编码 hosted，尚无可配置扩展入口；专项未实现，不纳入本期三项主榜 |

## 已有代码，不应误列为未开发

- 三项 benchmark 等权及领域/单 benchmark 聚合，缺项不重新分配权重。
- 当前 workflow repository/SHA 动态构建 QwenPaw ACP 包。
- 九批串行、模型串行、每题一个 runner、基础设施一次补跑。
- 公开字段白名单、完整性检查、禁止私有结果公开发布。
- 公开历史不可变追加校验和普通网站部署读取历史的代码。

这些项目的单测不等于正式 hosted 全链路验收。

## 推荐继续顺序

1. 完成网站代码验收/提交及文档同步，先交付可审查的正式界面。
2. 补实验协议冻结、预算停止和长期证据保存，避免直接启动不可控或不可比的完整运行。
3. 完成三项与六模型的离线验收、parity 报告，再启动正式完整运行和自动发布验收。
4. 在私有仓库接通一个替代 harness；随后扩充对照，不进入每次 release 的公开必跑量。

PawBench/Claw-Eval 仍因未确认现成 Harbor 接入而不在首期；AppWorld、Terminal-Bench 已按范围排除，不属于实现遗漏。
