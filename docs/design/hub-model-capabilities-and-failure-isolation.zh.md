# Hub 模型能力与目录故障隔离

针对 PR #7779 2026-09-17 复审，只修复确认的问题和草稿格式兼容，不扩大网络模块范围。

## 能力契约

成员目录仅增加 `supports_agent_thinking` 能力，不公开真实模型 ID、连接地址或供应商密钥。Runtime 根据此能力把 Agent 思考级别放入受限的 `hub_thinking_level` 字段；网关校验枚举值，依据服务端模型快照和现有 provider 的映射规则生成上游参数。原始思考字段、连接覆盖和任意 extra_body 仍不能由成员透传。网关不支持的模型明确拒绝显式思考控制。

思考映射复用 provider 规则，并在 Hub 内转换原生适配器参数为 Chat Completions 请求体。`inherit` 保留供应商默认行为。网关继续覆盖模型路由与输出上限，思考配置不能修改预算边界。

## 故障隔离

供应商列表保留个人数据。Hub 目录失败时，返回带现有 `models_last_sync_error` 字段的只读 Hub 条目，不暴露底层异常。前端分开处理供应商列表与 active model 的加载结果，取消重复请求控制面的成员目录；只要列表可用就保留个人配置入口，同时显示局部错误。显式 Hub 推理仍报错，不添加模型 fallback。

## 注册与迁移

邀请注册的用户数量查询在线程池执行。仅保留 base 分支已有的 `registration.enabled`／`registration_enabled` 升级路径；删除本分支治理表的旧开关、邀请覆盖和失败启动占位状态兼容。已明确写入的注册模式始终优先。

## 验证 checklist

- [x] 注册慢读取不阻塞事件循环。
- [x] Agent off/high 经真实 Runtime 参数生成后抵达 mock 上游，且不泄露真实模型 ID。
- [x] 非法思考值、任意上游覆盖与不支持的能力被拒绝。
- [x] 目录故障保留个人列表与界面，Hub 推理仍失败；目录恢复后错误清除。
- [x] 已发布配置迁移正常，草稿字段与占位推断不再参与迁移。
- [x] 运行相关 Python／前端回归与静态检查。
- [x] 提交不包含新增测试；临时验证脚本不进入版本库。

## 本次验证结果

- Conda `QwenPaw`：Hub、Provider、runtime 边界和 Hub CLI 既有回归 **854 passed，2 skipped**。
- 模型设置页面既有前端回归 **165 passed**；TypeScript 检查通过。
- 仓库外 Python 定向验证 **20 passed**：真实 Agent 工厂经 loopback listener 向 mock 上游发送 GPT-5 `off/high/inherit`，分别得到 `minimal/high/无覆盖`；验证目录只输出安全能力元数据、非法参数拒绝、DashScope 参数转换与思考预算限制、注册慢读取、SQLite 锁等待及结算清理。
- 前端临时验证 **3 passed**：目录失败/恢复、active model 加载失败、页面保留个人供应商入口及重试按钮；验证后删除临时文件。
- 注册读取注入 250ms 延迟时，20ms 心跳约 25ms 执行；SQLite 写锁持有 350ms 时心跳约 21ms。这里只验证执行边界，不代表生产性能基准。
- 本轮没有调用真实模型供应商或重新执行原生 Windows／容器部署测试；网络契约未变更。

## 授权上下文与 formatter 能力快照

复审确认 `runtime_id == "admin-test"` 不应决定管理员测试权限。管理员路由通过仅供内部调用的 keyword 参数 `admin_test=True` 进入共享网关；请求体不能传入该字段，runtime 路由也不从凭证或请求中读取它。预算准入事务重新检查账户当前角色，仅管理员可使用测试上下文。普通 runtime 不论名称如何，均校验 capability、生命周期、模型启用状态和成员授权。`admin-test` 仅保留为管理员测试台账的标记，不承载权限。

模型构建使用已取得的 `ModelInfo` 为 formatter 固定多模态能力，覆盖 Hub、个人模型和 fallback。异步 `format()` 将该快照传入归一化逻辑，不再查询当前全局模型或组织目录；显式模型选择不会被全局模型能力覆盖。formatter 和归一化逻辑均不查询模型能力；内部入口缺少元数据时保留媒体，原有媒体失败后剥离标记仍在每次格式化时生效。快照只影响消息格式，模型授权与预算仍由网关逐次校验，不添加 TTL 授权缓存。

### 修复 checklist

- [x] 普通成员使用 `admin-test` 请求受限／禁用模型返回 403，上游未收到请求。
- [x] 管理员测试仍可调用禁用模型；成员显式内部测试上下文和管理员角色撤销均被拒绝。
- [x] 请求体无法开启管理员测试，旧 capability 在准入时被拒绝。
- [x] Hub 图像／文本模型均使用自身能力；格式化无目录请求，心跳约 21ms。
- [x] 既有 Python 回归 950 passed、2 skipped；仓库外定向验证 7 passed，包含同名 runtime 正常授权仍可调用；不提交新增测试文件。

### CI 归属与接口收敛

Python override 用例在 upstream `eccd66eaa` 为 30 passed，本 PR 修复前为 17 failed、13 passed。更新既有 Provider／formatter mock 的 `ModelInfo` 契约，以及思考级别上下文的 patch 位置；不为 mock 在业务代码中添加兼容分支。

前端 non-QwenPaw 提交用例及其生产路径与 upstream 相同。仅在临时 upstream worktree 延迟发送锁回调即可复现相同失败，属于既有测试时序问题。既有用例改为显式取得发送所有权再验证 query 保持不变，不修改生产提交逻辑。

模型 ID、显示名称和上游模型 ID 分开处理：Runtime `ModelInfo.id` 使用 Hub 稳定 ID，`name` 为显示名称；网关内部的 `upstream_model` 才用于供应商调用。能力通过选中的 `ModelInfo` 传递，不从显示名称推断。

本轮验证：Python Agent／Provider／Hub 回归 4002 passed、5 skipped；前端全量 3843 passed；仓库外安全与能力验证 7 passed；TypeScript、格式和 pre-commit 检查通过。现有归一化测试删除过期的全局能力 mock，能力剥离断言仍保留，未新增测试文件。

## feat/fix_hub：默认值和邀请注册

合并 upstream main `ee0c08e7e`，保留本分支的本地虚拟环境和 PawApp 会话隔离。

模型上下文通过现有 `Provider.get_context_size()` 解析，最终兜底为
`DEFAULT_CONTEXT_WINDOW = 131072`。输出能力沿用 `ModelInfo.max_output_length`：
未知时为 `None`，不恢复已移除的 `ModelInfo.max_tokens = 8192`，也不沿用
Hub 原先的 4096。界面明确区分未知能力和已知上限，输出限制允许留空。
保存显式空值后，Hub 目录和 Runtime 保留该空值；若请求也未指定输出限制，
网关不发送 `max_tokens`／`max_completion_tokens`，由现有供应商默认行为决定。

预算模块仅预留明确的输出边界；有限总预算下，缺少输出边界的请求会被拒绝，
请求本身可提供边界。不启用有限预算时允许输出限制为空，并按返回 usage 结算。
无 usage 的失败请求仍按预留估算记账，不能将该估算解释为供应商确认的实际消耗。

邀请模式保持“创建账号／注册”入口，在注册表单填写邀请码，不改变兑换事务。

### 本轮 checklist

- [x] checkout `feat/fix_hub` 并合并 upstream main。
- [x] 复用 Provider 上下文解析和 ModelInfo 输出能力，未知输出可留空。
- [x] 保存接口、目录、网关和模型表格支持空值，不发送伪造的默认输出限制。
- [x] 注册入口保留原名称，邀请码仍在注册表单填写。
- [x] 仓库外验证已知／未知默认值、空值保存、网关请求参数及预算边界：9 passed。
- [x] Python 回归 870 passed、2 skipped；既有前端回归 247 passed，临时前端验证通过；TypeScript、pre-commit 检查通过。
- [x] 临时测试移至仓库外，不提交新增测试文件。
