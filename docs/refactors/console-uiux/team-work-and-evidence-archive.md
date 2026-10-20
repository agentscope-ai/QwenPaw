# Console UI/UX 团队工作与证据归档

> 更新时间：2026-10-20（Asia/Shanghai）  
> 归档范围：总设计、总设计 v2、评审者、验证者、文档官及并行任务；本地文档；历史 `/tmp` 证据索引。  
> 当前代码基线：`feat/console-uiux-refactor@27a1defb5546b721d2ebc23519a3a424d5a1b5bf`  
> Draft PR：`agentscope-ai/QwenPaw#8332`

## 1. 归档说明

本文件用于防止团队会话、worktree 和临时证据随环境清理而丢失。事实来源按可靠性排序：

1. 当前 Git 对象、分支与提交；
2. 仓库 `docs/refactors/console-uiux/` 和 `docs/audits/` 中的记录；
3. Codex 会话的完成消息、工具输出和任务摘要；
4. 已消失 `/tmp` 目录在文档中留下的路径、统计和 SHA-256 清单。

`/tmp` 与 `/private/tmp` 已在 2026-10-20 复查，当前没有可读取的本项目临时证据。下文保留的是可追溯索引，不代表原始截图、JSON、控制台日志或网络日志仍然存在。后续验证必须将需要长期保留的证据写入仓库文档目录或外部归档，不能只存 `/tmp`。

## 2. 角色与责任

| 角色      | 会话                                   | 主要责任与产出                                                   |
| --------- | -------------------------------------- | ---------------------------------------------------------------- |
| 总指挥    | `01a13e14-b9df-71f2-bd3c-1198d5ba7813` | 范围、优先级、冻结/恢复、合入与最终交付决策                      |
| 总设计    | `01a13e1d-d252-7813-aaad-cf4a94a63dd0` | 首轮证据化巡检、Wave 1/2 设计拆解、任务分支集成与收口            |
| 总设计 v2 | `01a14251-1f80-7b02-8f17-a317f39e7ae8` | 复用旧成果后的全域页面普查、垂直包组织、Round 4/5 收口           |
| 评审者    | `01a13e66-462a-7292-a7fe-aafb5d3662d8` | 固定范围独立评审，给出 APPROVE/REQUEST CHANGES 与 Finding 裁决   |
| 验证者    | `01a13f1a-c9e9-7002-852a-b4d6f1de5140` | 定点测试、真实浏览器交互、运行日志/网络/性能证据，不代替独立评审 |
| 文档官    | `01a13eb1-b058-79e3-820b-960acefc9370` | SSOT、计划、Finding、Wave closeout、handoff 与证据等级治理       |

## 3. 已完成工作总览

### 3.1 证据化巡检与设计

- 建立 Console 页面、核心任务与控件清单，区分真实鼠标复现、键盘验证、静态推断和不可验证项。
- 原始正式问题 F1–F12 覆盖 Tools 状态竞态、审批遮挡、设置页裁切、Chat 可访问名称、重复轮询、大 payload 同步格式化、Sessions 移动端全量渲染、主题 Token、侧栏焦点、文件树键盘模型、语言选择器和模型提供商上下文。
- 制定目标信息架构、视觉 Token、公共组件、性能预算、分阶段实施和回滚边界。

### 3.2 Wave 1–4 与后续页面包

- Wave 1：F1–F5、F8、F11、F12 及相关修复完成，补齐桌面审批轮询共享与移动提交触点。
- Wave 2：F6、F7、F9、F10 完成；组合验证 10 个文件、117 个测试通过；独立评审 APPROVE。
- Wave 3：A1 Files 平板标签与 C1 大文件树刷新性能完成；独立评审无 Critical/Important/Minor。
- Wave 4：应用侧 Ant Design W2/W5/W6 与 `destroyOnClose` 迁移完成；W1/W3 判定为 `@agentscope-ai/chat` / `@agentscope-ai/design` 依赖债务，不在 Console 内做无证据补丁。
- 后续页面包：侧栏交互视觉、SettingsCenter 对比度，以及设置/控制/调度相关垂直包完成；Round 5 记录为 19/19 范围页关闭，Models 按用户要求排除。
- 最新主分支同步：merge commit `27a1defb5`，保留 Advisor Mode/路由解析与重构分支的 Composer、审批队列和 SDK loader 修复；定点验证 6 文件、263 测试通过。

## 4. 并行任务索引

| 任务                                      | 会话                                   | 结果摘要                             |
| ----------------------------------------- | -------------------------------------- | ------------------------------------ |
| `console-tools-race`                      | `01a13e3d-aa73-7861-8672-25f82da5b8fd` | Tools Agent 切换竞态修复             |
| `console-polling`                         | `01a13e3d-dd82-7840-81ef-26cfc5ce46d1` | 常驻轮询去重与生命周期治理           |
| `console-settings-ux`                     | `01a13e3d-bb96-7fa0-a3bf-89467af504d0` | 设置中心交互与视觉修复               |
| `console-chat-ux`                         | `01a13e3d-9835-7330-bd91-d44663c9781f` | Chat 核心交互、触点和状态反馈        |
| `console-raw-performance`                 | `01a13e92-0194-7991-b060-3896350751f5` | Raw tool 延迟/有界格式化             |
| `console-sessions-mobile`                 | `01a13e92-65c9-7202-97de-987cbb843c32` | Sessions 移动端有界渲染与 44px 触点  |
| `console-sidebar-keyboard`                | `01a13e92-2fac-7ed2-a659-92092016fe1a` | 侧栏焦点顺序与跳转入口               |
| `console-filetree-keyboard`               | `01a13e92-82c2-70f3-8e5e-2a0f461fdeff` | Files tree roving focus              |
| `console-mobile-runtime-validation`       | `01a13eb8-034b-7290-aabc-c40a4f2b8a79` | 移动/平板运行时只读验证，A1 证据来源 |
| `console-expanded-tree-performance-audit` | `01a13eb7-e48e-7400-8e16-14c16a175ed9` | 500/2000 节点刷新与焦点恢复性能审计  |
| `console-files-tablet-tabs`               | `01a13ee7-f13a-76e2-9dff-2f165c4b36a1` | A1 平板标签可发现性修复              |

## 5. `/tmp` 历史证据索引

| 证据包                                                             | 结论或内容                                                    | 可恢复状态                                      |
| ------------------------------------------------------------------ | ------------------------------------------------------------- | ----------------------------------------------- |
| `/tmp/qwenpaw-console-mobile-validation.Ia4heA/`                   | 移动/平板运行时验证，形成 A1                                  | 原文件已消失；结论见 Wave 3、Finding 台账       |
| `/tmp/qwenpaw-tree-perf.WejBM5/`                                   | 大文件树初始性能测量，形成 C1                                 | 原文件已消失；结论见 Wave 3                     |
| `/tmp/qwenpaw-c1-segmented.DMZ8kc/`                                | C1 分段诊断，12 个有效样本/档                                 | 原文件已消失；样本说明见 Wave 3                 |
| `/tmp/qwenpaw-c1-implementation-e3e12d9/`                          | C1 修复后结果、绑定与报告                                     | 原文件已消失；四个文件 SHA-256 见 Wave 3        |
| `/tmp/qwenpaw-wave4-warning-governance-20261015-184506-8b5db203f/` | 6 路由 × 2 新上下文的 warning、console、network、binding 证据 | 原文件已消失；10 个文件哈希见 Wave 4            |
| `/tmp/qwenpaw-wave4-tooltip-vendor-20261015-191010-8b5db203f/`     | W1/W3 依赖归属与版本兼容矩阵                                  | 原文件已消失；4 个文件哈希见 Wave 4             |
| `/tmp/qwenpaw-wave4-postmerge-runtime-20261016-082932-48e8ca957/`  | 应用侧 warning 修复后的 12 个浏览器案例                       | 原文件已消失；清单哈希 `944611f6...b61`         |
| `/tmp/qwenpaw-round5-cf088ce5/REMAINING_MATRIX.md`                 | Round 5 剩余页面矩阵                                          | 原文件已消失；文档 SHA-256 `056a135d...8f95d8c` |

### 已保留的 C1 关键哈希

- `results-8b5db203f.json`: `00fcac4e6ccd0d1d8c61eea093689166cdb3527d1f856232431bf0e7f4215f25`
- `results-8b5db203f-2000-confirm.json`: `848f064692bdd585f04b6c89f41fe6ce418f72c523464ad448cea9eaa8217842`
- `evidence-binding.json`: `90006f4965ca6031ab5dcec26300a1d143731153ba3b231e8e2867c1dd094e10`
- `validation-report.md`: `840bc58910f58a5a353d93133a5d39aa6133275e37b2fe8210157d4013bd3c9e`

### 已保留的 Wave 4 关键哈希

- warning 基线：`manifest.json` `1954dc2a...b748`；`report.md` `103fa5a7...8d3a8d3`；`results.json` `057723c1...22c0`；`console.json` `b8cbb6af...a55ea`；`network.json` `be56faf0...e5cc73`。
- vendor 归属：`report.md` `df658cfd...c2bce36`；`compatibility-matrix.json` `e5a839d7...21a8e`；`owner-attribution.json` `e4c5331c...499911`；`manifest.json` `da71684c...8b11`。

缩写哈希只用于快速识别，完整值以 Wave 4 原文档为准。

## 6. 当前真实状态与未完成工作

- 长期分支：`feat/console-uiux-refactor`；当前远端与本地已对齐到 `27a1defb5`。
- Draft PR：`https://github.com/agentscope-ai/QwenPaw/pull/8332`。
- 当前分支相对最新 `main`：189 个文件，约 `+13,695 / -1,614`。
- 已完成范围不等于全产品永久验收通过。当前 HEAD 仍需重新生成全量控件清单，并按鼠标优先复测实际状态与字段联动。
- SIP LiveKit → dev 生命周期仍为 `DEFERRED / U`；若再次失败，应保持搁置，不阻塞其他收尾。
- Models 明确 scope-out。
- 危险写入、Market 安装/更新/卸载/发布、外部导航、真触屏、屏幕阅读器、Linux/Windows 仍属于 U 或未验证。
- 稳定性与性能后续应各自建立独立 handoff、基线、预算和验收门禁。
- `@agentscope-ai/design` 与 `@agentscope-ai/chat` 的依赖侧 warning 应集中记录为依赖治理问题，不应在业务页面重复制造补丁。

## 7. 后续接手顺序

1. 稳定 Draft PR：核对 CI、冲突、PR 描述与最新 main。
2. 在 5176 现有环境重新生成当前 HEAD 的页面/控件矩阵，鼠标优先逐项操作；对每次点击核对 DOM 状态、表单值、业务联动、console 和 network。
3. 修复仍可触达的 P1/P2；每个 Finding 独立提交、定点验证、独立评审后再合入长期分支。
4. 分别启动稳定性专项和性能专项；不要与视觉收尾混成一个无界任务。
5. 依赖治理、SIP、Models、真触屏/辅助技术和 IA 收敛按独立授权推进。

## 8. 防丢失规则

- 原始证据首先落到 `docs/refactors/console-uiux/evidence/<task>/` 或受控制品存储；`/tmp` 只作为采集缓存。
- 每个证据包保留 `README.md`、环境、步骤、结果、失败信号、commit、完整 SHA-256 和脱敏说明。
- 会话完成消息必须包含任务基线、任务 HEAD、集成 HEAD、测试结果、评审裁决、证据路径和剩余 U。
- 文档更新采用整篇覆盖，避免同一事实在多个版本中互相矛盾。
