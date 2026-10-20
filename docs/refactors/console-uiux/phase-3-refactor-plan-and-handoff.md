# 第三阶段重构方案

> 本文同时作为后续实施 Handoff。

> 文档状态：阶段总结与后续交接基线  
> 最后更新：2026-10-20（Asia/Shanghai）  
> 项目：QwenPaw Console UI/UX  
> 长期集成分支：`feat/console-uiux-refactor`  
> 当前基线：`27a1defb5546b721d2ebc23519a3a424d5a1b5bf`  
> 上游 `main` 基线：`7cb6234f25798ee8fe1554206942ad87b65fe73d`  
> Draft PR：[agentscope-ai/QwenPaw#8332](https://github.com/agentscope-ai/QwenPaw/pull/8332)

## 1. 文档目的

本文是第三阶段 Console UI/UX 重构的总方案、变更总结和后续 Handoff。
它服务三个目的：

1. 说明本阶段为什么改、采用了什么设计与工程方案；
2. 汇总已经进入 `feat/console-uiux-refactor` 的实际变化及其证据边界；
3. 把未完成、未验证、外部依赖和下一阶段任务完整交给后续负责人。

本文不是“所有页面、所有控件均已通过”的声明。历史页面族曾完成限定范围的
scoped pass，但这不等于每个生产控件都已被鼠标实际操作。2026-10-20 合入的
上游 `main` 又新增了 Advisor Mode、Chat 路由解析等界面和交互，因此旧控件清单
不能继续作为当前全量覆盖率。

## 2. 第三阶段目标

重构目标不是单纯修复视觉问题，而是让 Console 同时满足：

- **好用**：用户能够理解下一步，核心路径短且反馈明确；
- **易用**：鼠标优先，兼顾键盘、触屏、滚动和焦点恢复；
- **美观**：清晰、克制、连续、一致，符合 `design.md`；
- **正确**：控件值、表单状态、业务状态和请求 payload 真正联动；
- **稳定**：异步请求、Agent 切换、失败重试和取消不会污染其他状态；
- **高性能**：轮询、列表、树和大 payload 处理有明确边界；
- **可维护**：每项修改有独立验证、评审、提交和回滚边界。

### 2.1 设计约束

本阶段遵循以下设计语言：

- 以清晰、精确、克制、连续、用户自主和一致性为核心；
- 使用语义 Token，不在业务组件中扩散硬编码颜色；
- 品牌橙只承担主操作、选中和关键强调，不替代错误、成功等状态色；
- 桌面、平板、移动端优先重排和减少列数，不压缩核心控件；
- 触屏目标以 44×44 CSS px 为基线，视觉尺寸可小但命中区域不能小；
- 弹层必须保留来源与结果的连续性，支持关闭、焦点回退和无残留；
- 图标操作必须有稳定、本地化、动作导向的可访问名称；
- 加载、错误、空状态和恢复动作必须表达真实业务状态。

### 2.2 巡检约束

本阶段采用“真实操作而非静态观感”的证据门禁：

- 看见控件不代表控件可用；
- 弹层展开不代表选项能被鼠标选中；
- 视觉变化不代表值已写入表单或 payload；
- 键盘成功不能替代鼠标成功；
- 页面 smoke 不能替代所有核心控件逐项验证；
- 没有数据或受安全边界限制时必须记为 `U`，不能推断为 `PASS`。

## 3. 当前交付事实

| 项目                 | 当前事实                                              |
| -------------------- | ----------------------------------------------------- |
| 本地/远端分支        | `feat/console-uiux-refactor`                          |
| 当前 HEAD            | `27a1defb5546b721d2ebc23519a3a424d5a1b5bf`            |
| 上游 main            | `7cb6234f25798ee8fe1554206942ad87b65fe73d`            |
| PR                   | 上游 Draft PR #8332，当前 head 已为 `27a1defb5`       |
| 相对当前 main 的规模 | 189 个文件，+13,695 / −1,614，136 个提交              |
| 工作区               | 业务源码干净；`docs/` 为原有未跟踪目录                |
| 全量命令             | 未运行全量 `npm run build/test/format`                |
| 最新冲突验证         | 6 个定点测试文件、263 个测试全部通过                  |
| 最新静态门禁         | Prettier 通过；ESLint 0 error，16 条既有 Hook warning |

`27a1defb5` 是双亲 merge commit：

- 第一父提交：`c4a7b2fab8e7cf1db101073eac869a55bec0d011`；
- 第二父提交：`7cb6234f25798ee8fe1554206942ad87b65fe73d`。

main 合并时共处理 12 个冲突文件：7 个 Console locale、
`ChatSessionTransition` 的组件/样式/测试、`Chat/index.tsx` 和 SDK session
lifecycle 集成测试。最终保留了上游 Advisor Mode 与 Chat 路由解析协议，同时保留
本分支的 Composer 可访问名称、审批队列、SDK loader 重试和视觉状态。

## 4. 总体重构方案

### 4.1 交付方式

方案采用“小型垂直包 + 长期集成分支”，而不是一次性重写：

1. 每项任务从最新 `feat/console-uiux-refactor` 创建独立开发分支；
2. 总设计可在任务分支基础上拆分并行 worktree；
3. 子任务先归并至任务开发分支；
4. 任务分支完成组合验证和独立评审；
5. 只有 `APPROVE` 后才能合并回长期集成分支；
6. 集成后执行同范围回归并记录最终 SHA；
7. 未验证项保留 `U`，不因代码可达或测试存在而升级为 `PASS`。

### 4.2 四条工作路线

| 路线               | 本阶段成果                                                   | 仍需后续工作                                    |
| ------------------ | ------------------------------------------------------------ | ----------------------------------------------- |
| 功能与状态联动     | 修复鼠标点击、选择、表单默认值、Agent 所有权和 stale request | 重新生成全量控件清单并逐控件复验                |
| 视觉系统与页面精修 | 统一导航状态、语义 Token、响应式与弹层样式                   | 完成 IA 收敛、真机触屏和全主题系统验收          |
| 稳定性与恢复       | 大量页面加入错误态、重试、所有权隔离和失败保护               | 另立系统级稳定性专项，建立请求/日志持续门禁     |
| 性能               | 去重轮询、限制 Raw 格式化、限制列表渲染、优化文件树          | 建立 production-like 基准、长任务和真实数据预算 |

## 5. 已完成的主要修改

### 5.1 功能正确性与状态隔离

- Tools 请求显式绑定 Agent，并阻止旧请求覆盖当前 Agent 状态；
- Channels、Skills、MCP、ACP、Heartbeat、Voice、Backups、Imports、Inbox、
  Sessions 等页面增加 Agent 所有权、代次或 stale completion 防护；
- Channels 表单切换 Agent 时清理或重新绑定草稿，隔离重叠操作；
- Channels SIP/MQTT 去除重复 `initialValues`，保持默认值、持久值和 payload 一致；
- SIP 保存边界会清理 dev 模式下无效的 LiveKit 字段，并替换成功后的本地状态；
- Chat history 加入真实 SDK loader 重试，失败时保持旧 surface inert，不伪造空会话；
- ACP 路由规范化并保留别名 URL 状态；
- Security 工具选项去重，避免重复可选项和错误命中；
- Import 扫描和检测重试按 Agent 隔离，避免旧任务覆盖当前页面。

### 5.2 核心交互可用性

- 修复 Settings Drawer 中下拉弹层的 pointer-events，恢复真实鼠标选择；
- 修复 Sidebar tooltip 遮挡导航、点击穿透和选中态反馈；
- 将多条 Chat approval 从同坐标覆盖改为有界队列覆盖层；
- 为 Chat Composer、SDK action、General language Select 和 Provider 操作补充
  稳定的可访问名称；
- Files tree 实现 roving focus、treeitem 语义和方向键导航；
- Sidebar session 行去除重复焦点停靠点，保留行操作和更多菜单；
- Skills 标签筛选支持 Escape 关闭；
- Chat 移动端提交触点扩展至可用尺寸；
- Environment 行操作在多档宽度下可见、可命中并绑定正确数据行。

### 5.3 响应式和视觉精修

- Sidebar hover、selected、pressed 状态统一，并恢复浅色/暗色对比度；
- SettingsCenter 活动导航采用语义 Token，修复浅色主题低对比问题；
- General Settings 在平板宽度下允许控制区换行，避免卡片裁切；
- Sessions 在平板和移动端重排 header、列表与操作；
- Inbox 工具栏在平板宽度保持可见；
- Files 移动端提供工作区面板切换，扩大活动栏目标并修复 border-box；
- Imports 移动端保留内容 gutter；
- Token Usage Range Picker 在移动端使用适配布局；
- Security selector、Debug toolbar 和 Settings selector 在中间宽度保持完整；
- Cron DurationWheel 避免 Drawer 溢出；
- Channel 移动 Sheet 中 `no_text_debounce` 开关保持在容器内并可点击；
- Environment 表格从 viewport 假设改为观察容器宽度；
- Queue 和 BackgroundTask 面板改用语义主题 Token。

### 5.4 错误、空状态和恢复

- Chat history、Sessions、Inbox、Tools、ACP、Heartbeat、Voice、Imports、
  Backups、MCP、Skills 和 Channels 增加明确的加载失败与恢复路径；
- 区分“空数据”和“加载失败”，避免把失败误报为空状态；
- 写入前确认当前 Agent/行/请求仍拥有动作，失败后保留可恢复输入；
- Chat 路由解析支持 not found、ambiguous 和 retry 状态；
- main 新增的 Advisor Mode 与 Chat resolver 已通过冲突组合保留在当前分支。

### 5.5 性能与请求治理

- 去重 `/console/push-messages` 常驻轮询，并共享 desktop approval 状态；
- 页面隐藏时采用更低频的轮询策略；
- Raw tool 内容仅在需要时格式化，并对大 payload 设置处理边界；
- Sessions 移动端渲染数量有界；
- Files tree 降低 refresh 工作量并保持焦点恢复；
- 异步状态写入使用所有权和代次，减少无效渲染与竞态污染。

### 5.6 Ant Design 与运行警告治理

已完成的本地迁移包括：

- Spin route fallback；
- AgentSelector popup class；
- Sessions/ChannelCard body styles；
- Models modal teardown prop；
- Sidebar quick settings 和延迟 Flyout 的 Popover root class。

剩余 fresh Security 页面 `overlayClassName` warning 已通过运行时 DOM、挂载树、
活动 Vite chunk 和 sourcemap 归因到 `@agentscope-ai/design@1.0.29` 内部
`Button → SparkTooltip → Ant Tooltip`。当前 Console caller 没有语义等价的关闭或
迁移 API，因此没有采用替换组件、日志过滤或修改 `node_modules` 的伪修复。

## 6. 页面级变化矩阵

| 页面/区域    | 已完成变化                                                 | 保留边界                                                    |
| ------------ | ---------------------------------------------------------- | ----------------------------------------------------------- |
| Chat         | Composer 名称、审批队列、history retry、路由恢复、移动触点 | 真实发送/停止、外部模型与全场景长会话仍需系统验收           |
| Sessions     | 移动有界渲染、平板布局、失败恢复、Agent 隔离               | save/archive/delete/batch 等真实写入仍有 `U`                |
| Inbox        | 平板工具栏、刷新失败保留消息、Agent 隔离                   | 真实消息和审批写入为 `U`                                    |
| Files        | APG 风格树键盘、移动 panes、触点、refresh 性能             | upload、Git 写入、真触屏为 `U`                              |
| Imports      | 扫描状态、检测重试、Agent 隔离、移动 gutter                | 最终真实 import lifecycle 为 `U`                            |
| Channels     | 所有权隔离、错误恢复、默认值、移动开关、SIP payload 清理   | SIP LiveKit→dev 运行验收为 `DEFERRED/U`                     |
| Heartbeat    | 加载失败防护、Agent 绑定                                   | instruction fixture 和真实保存链仍有限制                    |
| Skills       | 错误/空状态、Agent 隔离、删除确认、上传 auth、Escape       | 真实安装、导入、删除为 `U`                                  |
| Tools        | stale request 防护、失败恢复、Agent header                 | 真实危险工具写入不在本阶段                                  |
| MCP          | 加载恢复、draft 重置、stale mutation 防护                  | 真实 CRUD 只在隔离环境验证                                  |
| ACP          | canonical route、加载失败防护、Agent 隔离                  | runner launch 为 `U`                                        |
| Backups      | 加载失败与空状态分离                                       | create/import/restore/delete job 为 `U`                     |
| Voice        | Agent 隔离、失败时阻止编辑                                 | Whisper provider/API 为 `U`                                 |
| Security     | 工具选项去重、rule modal 响应式、错误显示                  | backend persistence/scanning 和依赖 warning                 |
| Debug        | 中间宽度 toolbar 可用                                      | production backend 内容为 `U`                               |
| Agent Config | 既有鼠标矩阵和失败恢复；main 新增 Advisor Mode             | 新增控件需重新纳入全控件清单                                |
| Checkpoints  | 菜单、预览、取消路径曾通过                                 | destructive write 为 `U`                                    |
| Agent Stats  | hover、日期 query、视觉矩阵曾通过                          | Chrome/macOS 样本边界                                       |
| Market       | browse/search/filter/internal detail 曾通过                | install/update/uninstall/publish/external navigation 为 `U` |
| Models       | 仅保留早期已审修改                                         | 后期全量巡检明确 scope-out，必须单独立项                    |

## 7. 代表性提交与集成节点

| 工作包                            | 代表性提交/集成点                                               |
| --------------------------------- | --------------------------------------------------------------- |
| Wave 1 功能、主题与轮询           | `28109b4cc`、`8b2317cb6`、`57676c037`、`7df8c7819`              |
| Wave 2 Raw/Sessions/Files/Sidebar | `1b0ecec92`、`038e811d9`、`508952dd7`、`9d575bf8b`              |
| Files 性能和移动断点              | `8b5db203f`、`e3e12d986`                                        |
| Ant Design 本地迁移               | `48e8ca957`                                                     |
| Sidebar/Settings 视觉             | `f6530ee34`、`85c44a633`                                        |
| Round 4 恢复与响应式              | `31d0c486a` 至 `cf088ce57` 的独立垂直包                         |
| Round 5 Security/Debug            | `0362e7a5e`、`6179f8dea`                                        |
| Environment/Channels/Sidebar 收尾 | `e822ab338`、`1345210d4`、`6554976db`、`2ce8c05d9`、`9e8f57bc4` |
| SIP 清理                          | `c4a7b2fab`                                                     |
| 最新 main 同步                    | `27a1defb5`                                                     |

旧 Foundation 分支的 5 个提交已由上游 `d81427aed` 压缩合并，涉及的 20 个文件
内容已核对一致，不是遗漏。早期部分 Wave 分支虽然在拓扑上显示未 merge，但其
补丁等价提交已经进入长期集成分支。Models 的完整体验分支则不属于本轮交付。

## 8. 验证和证据总结

### 8.1 已执行的代表性门禁

- 桌面约 1280px、平板 768–900px、移动约 390px；
- 浅色/暗色主题及 selected/hover/disabled/error 状态；
- 鼠标点击、popup hit-test、`pointer-events`、`elementFromPoint`；
- 控件值、相邻字段、payload 和关闭后残留；
- 定点 Vitest、ESLint、Prettier 和 `git diff --check`；
- 浏览器日志、失败请求和非 GET 请求拦截；
- 独立 Reviewer 与独立 Validator 双门禁。

### 8.2 最终收尾证据

- Environment：1280/900/820/769/768/390 六档，Edit/Delete 实际命中，
  `scrollLeft=0`，正确行 Drawer，邻行隔离；
- Channels initialValues：SIP/MQTT 没有重复默认值 warning，默认/持久值保持；
- Channels mobile switch：390px 下 rect `x=302..346`，实际点击和值/payload 联动通过；
- Sidebar popup：本地 quick settings、Appearance、Theme 打开/关闭和无残留通过；
- main 冲突：6 个相关测试文件、263 个测试通过，Prettier 通过，ESLint 0 error；
- 网络安全边界：最终有界验证没有把非 GET 请求继续到真实 8004 后端。

### 8.3 证据解释限制

- targeted test PASS 不等于真实鼠标 PASS；
- 页面族曾完成 scoped pass 不等于所有控件 PASS；
- 代码已经 merge 不等于运行验收通过；
- 单个 macOS/Chrome 样本不代表 Windows/Linux/真实触屏；
- `/tmp` 证据是本机临时材料，不能作为长期唯一归档。

## 9. 未完成工作总账

以下任务必须保留给后续人员，不能因本阶段收尾或 PR 可达而关闭。

### H1 · P1 流程优先级 · 重建全量控件清单并完成鼠标优先验收

**当前状态：** `NOT STARTED ON CURRENT HEAD`。

历史上曾生成静态控件清单，并完成页面族 scoped pass；但该过程被发现存在
“页面可打开即误判完成”“只测显眼控件”和“键盘结果替代鼠标结果”的风险。
main 新增 Advisor Mode 与路由控件后，旧清单已经过期。

**接手动作：**

1. 以 `27a1defb5` 或接手时最新 PR HEAD 重新扫描生产 TSX 控件；
2. 排除测试、Story、隐藏不可达实现，建立页面→任务→控件→输入方式矩阵；
3. 每个核心 Select/Dropdown 必须用真实鼠标选择具体 option；
4. 记录值变化、下游联动、邻字段隔离和请求/payload；
5. 所有未执行项明确写 `NOT TESTED` 或 `UNAVAILABLE`；
6. 新增 Advisor Mode、Chat route resolution 和 main 新增控件必须纳入。

**验收：** 核心 `NOT TESTED=0`；所有 P1/P2 候选均有复现或排除证据；不得用
原生 `select` mock 证明 Ant Design 生产控件可点击。

### H2 · SIP LiveKit → dev 生命周期

**当前状态：** `DEFERRED/U`。

代码已清理 dev payload 的 6 个 `livekit_*` 字段，并在成功后替换本地状态；
定点测试存在。但唯一授权的 5176 运行中，鼠标命中 pyVoIP option 后 Select 仍
显示 LiveKit，未产生 dev PUT，因此无法裁决真实 payload、reopen/resave 和旧值
不复活。

**接手条件：** 用户明确重新开放 SIP 范围，并提供可拦截写入的浏览器通道。

**验收：** 鼠标完成 LiveKit→dev；捕获 dev PUT 且 6 个字段均缺失；保存后关闭、
重开、再次保存仍不复活；相邻字段保持；真实后端写入为 0 或使用隔离 fixture。

### H3 · Models 独立巡检与重构

**当前状态：** `SCOPE-OUT`。

早期已有 Provider action 命名和 modal API 迁移，但后期 Models 被用户明确排除，
不能宣称页面完整可用。

**接手动作：** 独立建立 Models 任务，覆盖 provider、credential、model editor、
thinking capability、默认模型、Chat model picker 与 Agent Config 模型联动。

**验收：** 鼠标真实选择、保存/取消/关闭、错误恢复、移动布局、暗色主题、请求
去重和敏感信息保护全部有证据。

### H4 · 依赖层 Tooltip/forwardRef warning

**当前状态：** `DEFERRED/U — dependency-owned`。

fresh `/security` 的 `overlayClassName` warning 已确认来自
`@agentscope-ai/design@1.0.29` 的 SparkTooltip。两类 `forwardRef` warning
同样属于依赖实现。本仓没有正式 `patch-package`/`patchedDependencies` 机制。

**禁止方案：** 替换本地 design Button、过滤 console、直接改 `node_modules`、
根据文本搜索盲改 Sidebar。

**正确方案：** 单独评估依赖升级或正式补丁机制，在 SparkTooltip 内迁移到
`classNames.root`，并验证普通 Button 未传 tooltipContent 时 warning=0、样式不变。

### H5 · 真实写入、危险操作和外部能力

**当前状态：** 多页面 `U`。

未完整执行的能力包括：Backups restore/import/delete、Market install/update/
uninstall/publish、Skills install/import/delete、Files upload/Git、ACP runner、
Security persistence/scanning、真实 approval/message 写入。

**接手条件：** 隔离租户或 fixture、可清理数据前缀、明确回滚方案和用户授权。

### H6 · 真触屏、屏幕阅读器和跨平台

**当前状态：** `NOT EXECUTED END-TO-END`。

现有证据主要来自 macOS Chrome/IAB 和模拟 viewport。需要补充 iOS/Android 或
触屏桌面、VoiceOver/NVDA，以及 Windows/Linux 文件、滚动、字体和缩放行为。

### H7 · 系统级稳定性专项

**当前状态：** 已完成多个局部 recovery guard，但没有形成当前 HEAD 的系统级
稳定性验收。

**接手动作：** 建立请求拓扑、同 endpoint/scope in-flight 计数、Abort/代次、
Agent 切换、卸载后写状态、离线/超时/重试、监听器和 popup cleanup 基线。

**验收：** 无 stale overwrite、无重复请求风暴、失败可恢复、草稿不丢、隐藏页
降频，console error 为 0，warning 均有 owner/原因/到期条件。

### H8 · 系统级性能专项

**当前状态：** 已有局部修复，没有 production-like 总体验收。

**接手动作：** 固定数据集并测量 LCP/INP/CLS、长任务、路由 bundle、DOM 数、
500/2000 sessions、500/2000 files nodes、1/5/20MB Raw payload。

**建议预算：** LCP≤2.5s、INP≤200ms、CLS≤0.1、主交互同步任务≤50ms、
同 endpoint/scope 同时最多 1 条 in-flight。

### H9 · 信息架构收敛

**当前状态：** 只完成了局部 route canonicalization 和导航视觉，没有实施原审计
提出的六域 IA。

**待决策：** 是否继续 Work / Automations / Agent / Extensions / Insights /
System Settings 六域；是否建立稳定 All features；Classic 与 Desktop OS 是否共享
同一 registry；旧深链迁移和返回位置策略。

### H10 · PR、CI 和文档归档

**当前状态：** Draft PR #8332 已指向 `27a1defb5`。本次文档位于原有未跟踪
`docs/` 目录，尚未形成受版本控制的文档提交，也未归档到钉钉。

**接手动作：**

1. 查看 Draft PR CI，不把“CI 已触发”写成“CI 已通过”；
2. 按 PR 评审门禁处理证据化 finding；
3. 用户确认后再把文档加入提交或归档到钉钉“功能设计”目录；
4. PR ready 前复核 base/head、未解决讨论和 deferred 项表述。

## 10. 建议的后续执行顺序

### 第一优先级：稳定 Draft PR

1. 读取 PR #8332 CI 与 review 状态；
2. 只修复可触达且通过证据门禁的问题；
3. 每个 finding 独立 commit，定点验证后统一回复；
4. 禁止 force-push 主干，禁止用 `--no-verify` 跳过 hook；
5. PR 仍为 Draft 时不宣称可合入。

### 第二优先级：当前 HEAD 的全量控件验收

以页面族并行分片，但每片必须使用同一矩阵和证据格式。优先 Chat、Agent Config、
Channels、SettingsCenter、Files、Sessions；Models 只有在重新纳入范围后执行。

### 第三优先级：稳定性与性能

稳定性与性能各自独立立项，禁止顺手塞入页面美化包。先建立测量和失败复现，
再决定修复；不要从“代码看起来可能慢”直接跳到大范围重构。

### 第四优先级：依赖升级、SIP 和 IA

这三项都需要明确产品/架构授权：依赖升级可能带来 AntD 6 迁移；SIP 需要安全
写入拦截；IA 会改变导航和深链。不得由接手者默默扩大范围。

## 11. 后续任务模板

每个后续任务至少记录：

```text
TASK_BASE_SHA:
TASK_BRANCH:
OWNED_FILES:
USER_JOURNEY:
CONTROL_INVENTORY:
EXPECTED:
ACTUAL:
INPUT_METHOD:
TARGET_VIEWPORTS_THEMES:
REQUEST_PAYLOAD_OR_STATE_PROOF:
TARGETED_TESTS:
BROWSER_EVIDENCE:
REVIEW_RANGE:
REVIEW_VERDICT:
INTEGRATION_COMMIT:
RESIDUAL_U:
ROLLBACK_BOUNDARY:
```

正式问题必须包含复现路径、实际结果、预期结果、输入方式、代码位置、影响范围、
最小修复、回归路径和证据。未通过触达性与契约门禁的内容只能列为 Design
Question、Suggestion 或 Unverified Hypothesis。

## 12. 接手环境与操作边界

- 工作目录：`/Users/mazhijian/Documents/Project_2026/P01_LLM/C02_Solutions/QwenPawCodex`
- Conda：`qwenpaw-codex`
- 后端：`localhost:8004`
- 前端：`localhost:5176`
- 长期分支：`feat/console-uiux-refactor`
- 上游 PR：`agentscope-ai/QwenPaw#8332`

操作规则：

- 不在长期分支直接开发；从其最新 HEAD 建任务分支/worktree；
- 不自行新建 5176 之外的前端服务，除非任务明确授权；
- 不运行全量 `npm run build/test/format`，定点验证不受此限；
- 不把危险写入发到真实 8004，使用拦截或隔离 fixture；
- 不改用户原有未跟踪文件；
- push、PR、依赖升级、钉钉归档和破坏性操作均需对应授权。

## 13. 阶段裁决

第三阶段已经交付一组覆盖交互、视觉、响应式、恢复和局部性能的实质性改造，
并形成上游 Draft PR。当前没有已确认且未处置的本地 P1/Critical 缺陷，但这不构成
全产品无严重问题证明。

本阶段可作如下裁决：

- **代码集成：完成到 `27a1defb5`；**
- **Draft PR：已创建并同步当前 HEAD；**
- **已审垂直包：在各自证据边界内完成；**
- **全量控件验收：未在当前 HEAD 完成；**
- **SIP、Models、依赖 warning、危险写入、真触屏/读屏：保留 Handoff；**
- **系统级稳定性、性能和 IA：需要新的专项阶段。**

后续负责人应从本文件的“未完成工作总账”开始，而不是重新执行已经有充分证据的
历史修复；同时也不得把历史页面关闭状态外推为新增控件或未操作控件的 PASS。
