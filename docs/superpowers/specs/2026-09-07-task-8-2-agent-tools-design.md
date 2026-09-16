# Task 8.2：Agent 工具配置与运行设计

日期：2026-09-07。状态：用户已确认具体设计，进入实施和隔离环境验收。

本文件对应纵向 Task 8.2，以及总计划内部技术细目 Task 8.3。目标是在保留原工具列表、启停、异步执行、配置、Browser 实验状态、后台任务和 ToolCards 的前提下，完成 Agent 成员权限、工具 Secret 与多用户 Browser 资源边界。

## 已核实的现状

- `/tools` 的安全读取已允许全部 Agent 成员，写请求由统一 Agent 路由限制为 owner/collaborator；前端也根据 `can_edit` 进入只读状态。服务端权限已有基础，但缺少针对各写入口和跨 Agent 的直接合同测试。
- 工具启停、异步执行和全部配置仍写入 Agent 的 `agent.json`。插件清单中的 `password` 字段只在响应中替换为 `***`，提交时再靠该字符串推断保留，因此明文 Secret 仍落入普通工具配置。
- 当前至少 Wan、Qwen Image、GPT Image 和 Creator 工具声明了密码配置。插件运行时通过同步 `get_tool_config()` 读取配置，不能在工具函数中直接等待异步数据库查询。
- Browser 工具开关本身按 Agent 保存，但页面中的“实验模式”会修改进程级全局 `browser.experimental`。它决定进程实际导入哪套 Browser 实现，不能作为 Agent 级开关。
- 统一 Browser 仅在真正调用时按需启动。执行 Worker 按工作区与会话隔离，BrowserContext 按会话隔离；空闲 Worker 和会话会回收。当前没有完备的多用户全局/单用户并发配额，并且 `user/profile/connect_cdp` 可接触真实登录态或外部浏览器。
- 统一 Browser 已有子进程隔离，但配置说明明确表示 OS 沙箱仍在规划中。因此它不适合作为多用户服务的默认能力。

## 方案选择

采用“Agent 配置 + Credential Binding + 平台 Browser 策略”的分层方案：

1. 工具目录、插件代码和版本仍由管理员治理；Agent 页面只能配置已经安装并发布到目录中的工具。
2. 启停、异步执行和非敏感字段继续使用现有 Agent 配置，避免为当前需求新增整套工具配置表。
3. 每个 `password` 字段使用既有 PostgreSQL Credential Store，以 Agent 为 scope、工具为 consumer、字段名为 purpose 建立绑定。Agent 配置只保存非敏感值和稳定绑定标记，不保存明文。
4. 应用启动、Agent 预载或重载时异步解析已授权绑定，写入进程内短生命周期运行缓存；插件原同步 `get_tool_config()` 合并非敏感配置和该缓存，保持插件 API 兼容。撤销、替换和 Agent 卸载立即清除对应缓存。
5. Browser 能否在多用户模式运行由平台策略决定。Agent 页面只能看到有效策略并在允许时启停工具，不能切换进程级实现或连接方式。

仅保留 `***` 掩码方案不能消除普通配置中的明文；把全部工具配置迁入新数据库表会扩大本任务且与现有 Agent 配置体系重复；为每个插件改成异步配置 API 会破坏插件兼容。因此不采用这些方案。

## 权限与 API 契约

- owner/collaborator 可以启停工具、设置异步执行和编辑非敏感配置；user 可以读取有效工具列表并调用已启用工具，所有写入口返回 403。
- 管理员通过普通 Agent 页面也遵循成员关系；全局插件安装、升级、停用和卸载继续使用管理员治理入口。
- `ToolInfo` 增加 `can_edit`、`policy_locked`、`policy_reason` 与密码字段的 `credential_status`。任何响应均不包含密码值、掩码替身或 Credential ID。
- 工具配置读取只返回非敏感字段。密码状态单独表示 `missing/configured/revoked`。
- 工具配置提交把非敏感值与密码动作分开：`keep`、`replace(value)`、`delete`。页面不再提交 `***`。
- 未安装、未发布或不属于该 Agent 工具目录的名称一律拒绝，避免借路由创建任意工具配置。
- 批量启停继续复用单工具接口，不新增无必要的批量写 API；部分失败后前端重新加载服务端状态。

## Secret 保存与运行解析

- 每个密码字段单独绑定，consumer 类型为 `agent_tool`，consumer ID 由 Agent 数据库 ID 与工具名稳定派生，purpose 包含字段名。scope 固定为目标 Agent。
- replace 创建新 Credential 并撤销旧值；delete 撤销绑定；keep 不触碰 Credential Store。状态读取只查询元数据。
- 非敏感配置保存前按插件清单过滤和类型校验，密码字段不会进入 `agent.json`。对历史明文只做只读识别和迁移预览，本任务不静默搬迁原值。
- 运行缓存只存在于服务进程内，按 Agent/工具索引。缓存装载必须验证 scope、consumer 和 active 状态；数据库异常时该工具视为缺少凭据，不能回退读取历史明文。
- 日志、异常、API、SSE 与 ToolCards 不记录 Secret。运行时缓存不得暴露管理读取接口。
- 文件配置与数据库凭据不能跨介质形成单一事务。保存流程先校验完整请求，再执行凭据动作和非敏感原子文件写；任一步失败都返回未完全生效，并重新装载数据库事实。针对替换后的文件失败执行补偿撤销，禁止把部分成功报告为成功。

## 多用户 Browser 策略

- 多用户模式默认 `browser` 不可启用；现有 Agent 即使历史配置为启用，运行时也按平台策略计算为禁用，页面显示锁定原因。
- 平台操作者显式允许后，多用户 Browser 强制使用 `guest + incognito + headless` 和应用托管 Chromium。拒绝 `identity=user/avatar`、`context=profile`、`connect_cdp`、自定义 `cdp_url`、`user_data_dir` 与直接控制真实 Chrome。
- 增加平台全局并发上限和单用户并发上限。并发主体取实际调用用户；资源不足时有限等待，超时返回可识别的繁忙错误。会话结束、归档、删除、超时和服务关闭均释放配额。
- 进程级 `browser.experimental`、backend 和启动参数只作为平台有效配置。Agent Tools 页面移除可写实验模式按钮，保留当前模式、可用性和锁定状态展示。
- 单用户桌面模式保留原 Browser 开关、实验模式兼容入口和身份模式，不改变既有工作流。
- 本任务提供配置文件级平台开关与配额；管理员图形化安全策略编辑归入纵向 Task 11.2。

## 原功能保真

- 工具列表的已启用/可用分组、全开/全关、逐项启停、异步执行按钮、配置表单及成功/失败反馈保持。
- Browser 当前模式仍可见；多用户受限时显示平台锁定，不显示可误导的可写按钮。
- ToolCards、`/tools`、`/tool-bg`、`/tool-cancel`、前台转后台、取消和历史事件不改变数据协议。
- 插件运行继续通过 `get_tool_config()` 获得同形字典；合法绑定存在时，插件无需了解 Credential Store。
- Legacy/单用户模式继续支持文件配置。多用户模式不自动迁移历史工具 Secret，迁移前保持原文件不变并输出不含明文的预览。

## 实施范围

- 后端：工具 DTO/路由、工具配置服务、Credential 运行缓存与插件配置读取、Agent 启动/重载接线、Browser 平台策略与配额。
- 前端：Tools 页面权限、显式 Secret 动作、Credential 状态、Browser 锁定与有效模式展示。
- 测试：路由权限与跨 Agent 隔离、Secret 不回读/替换/撤销/重启装载、插件运行解析、Browser 默认关闭和隔离配置、并发配额、原后台任务与 ToolCards 回归。
- 不安装/升级依赖，不改插件安装治理，不迁移原 MCP，不写入原工具 Secret，不重启原 18089 服务。

## 验收标准

- owner/collaborator 的启停、异步和非敏感配置生效；user 可用但所有配置写入被服务端拒绝。
- 密码读取只有状态，keep/replace/delete 正确；`agent.json`、API、日志和事件中无新 Secret 明文。
- 服务重启后合法绑定可供插件运行，撤销或跨 Agent 绑定不能解析；数据库不可用时安全失败。
- 多用户默认无法运行 Browser；平台允许后只使用隔离访客模式，并发超限可控且资源释放后可恢复。
- 单用户 Browser 原行为、工具页面主要交互、后台任务命令和 ToolCards 回归通过。
- 使用独立 PostgreSQL、合成账户和隔离端口完成至少 owner/collaborator/user 三角色浏览器验收；原数据哈希保持。

## 设计自检

配置、凭据、运行缓存和 Browser 策略各自承担单一职责；复用 Credential Store、Agent 权限和插件 API，避免新增重复事实源。多用户 Browser 采用默认关闭与显式平台开放，当前只实现必要的隔离和配额，不提前建设完整管理员安全策略页面，符合 KISS、DRY、SOLID 与 YAGNI。
