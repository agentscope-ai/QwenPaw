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
