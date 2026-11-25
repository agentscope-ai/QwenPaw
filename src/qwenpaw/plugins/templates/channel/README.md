# 进程渠道 SDK 模板

这是可运行的本地信箱示例，不是外部聊天平台驱动。启用后，宿主在独立进程中运行 `MailboxDriver`；回复写入该插件当前工作区的私有 `outbox/`，不向其他人发送消息。默认关闭。

```sh
python -m qwenpaw.plugins.check --channel-template ./my-channel
python -m qwenpaw.plugins.check ./my-channel --runtime
```

`--runtime` 验证真实子进程中的导入和驱动签名，执行安装与清理，不连接平台。实际生命周期可用 `PluginTestHost(root, process_channels=("example-sdk-mailbox",))`、`install()`、`start_channel()`、`send_channel()`、`stop_channel()` 和 `uninstall()` 验证。

接入平台时，更改 plugin.json/channel.json 中的名称与入口，有第三方 SDK 时，在 plugin.json 的 sdk.capabilities 加入 `dependencies`，在 `optional_dependencies` 声明包组（如 `{"transport": ["example-sdk>=2"]}`），在 channel.json 设置 `"requires": ["transport"]`：

- `start(ch)` 建立平台连接，把任务、线程、连接登记到 `ch.resources`，按实际连接状态调用 `report_status()`。
- 平台收到消息后，构造公共 `ChannelMessage`，包含真实操作者、稳定消息编号和会话编号，调用 `await ch.receive(message)`。接受入队不等于模型处理完毕；重试继续使用原消息编号。
- `resolve_target()` 负责平台地址转换。`send()` 使用公共内容类型，宿主负责回复句柄、去重、投递记录和恢复。分步骤副作用必须先等待 `prepare_step()`，确认后等待 `record_progress()`。
- 通过 `ChannelDeliveryError` 区分确定失败与结果未知。不能确认是否发送成功时，必须保留未知状态，不能假装失败后直接重发。
- `stop(ch)` 等待平台结束，仍可写入最后状态。资源未结束或最后状态写入失败时，不得报告清理成功。

模板未演示平台验签、审批、扫码授权、HTTP 转发或独占账户；这些不能因模板可运行就认定验收通过。

### 目标策略与前缀

SDK 1.2.0 保留类属性 `response_policy = ResponsePolicy(...)` 作为默认值。需要按目标选择行为时，实现同步的 `response_policy_for(target: ReplyTarget) -> ResponsePolicy`，例如普通会话流式、线程会话非流式：

```python
def response_policy_for(self, target):
    return ResponsePolicy(
        streaming=not bool(target.metadata.get("thread_id")),
        configured_prefix=False,
    )
```

宿主在 `resolve_target()` 完成后、首次持久化路由前调用它。回调不做 I/O、不启动后台工作；不能启用描述符未声明的能力。策略随路由保存，重复入站和 worker 重启不会重新选择。已有但未保存策略的旧路由继续使用当前驱动的静态策略，不追溯调用新回调。新回复才采用新的目标策略。

`configured_prefix` 默认 `True`。设为 `False` 时，直接发送、内容块发送和流式发送都不添加渠道配置中的 `bot_prefix`；显式消息 metadata 中的 `bot_prefix` 仍然有效。这个选项不移除正文中的文字，不修改媒体或平台卡片排版，也不开放内部 `SendFormatPolicy`。它覆盖 MQTT 这类渠道不希望配置前缀进入 payload 的场景；旧驱动对显式 metadata 前缀有不同规则时仍需单独迁移验证。

`ResponsePolicy.text_merge_delay_ms`（1.2.0）复用宿主文本合并机制：`None` 关闭合并，`0` 在回复结束时统一发送，正整数还会在连续空闲指定毫秒后发送。启用时必须声明 `channel.text_merge.v1`。用户取消会丢弃尚未发送的缓冲文本；已经开始的平台请求不能因此撤回。

`ResponsePolicy.continue_on_delivery_error`（1.2.0，默认 `False`）决定一次发送失败后是否继续消费模型事件，不代表重试或忽略失败。最终回复仍标记失败；结果未知时仍禁止同一回复继续产生副作用。平台格式、卡片内容和业务规则留在驱动。

声明 `channel.run_events.v1` 后，`ChannelDriver.on_run(ch, event)`（1.2.0）接收已有的 `qwenpaw.plugins.channels.ChannelRunEvent`。`start/running` 在宿主接纳并准备处理后发出，`end` 提供 `completed/failed/cancelled`；主动发送与入队前拒绝不生成运行事件。`run_id` 是本渠道一次处理的编号，`target` 是公开回复目标的 `key`。群共享会话中，`user_id` 可以是共享身份，`sender_id/acl_sender_id` 仍表示平台操作者。

回调顺序由宿主管理，每次实际回调有五秒预算。开始回调未退出时，结束通知排在后面；结束通知未退出时，不能报告回复资源清理完成。停用等待超过宿主排空预算可以明确失败，不能把超时当作已清理。通知异常会记录诊断，不代替模型结果，也不会自动重放回调。这是当前 worker 的运行通知，不提供崩溃后的事件重放保证；`ch.delivery` 不在此回调中绑定投递事务。平台副作用使用 `send/on_stream/prepare_response/reaction`，回复资源由 `finish_response` 释放。

可选的管理与审批接口从 SDK 1.2.0 引入：

- `ChannelDriver.manage(request)` 必须是只有一个请求参数的静态异步方法，运行在临时 worker 中，不会构造 Driver 或调用 `start()`。请求的 `operation` 为 `qrcode.fetch`、`qrcode.poll` 或 `connection.verify`；分别返回 `ChannelQRCode`、`ChannelAuthorization` 或 `ChannelVerification`，失败返回 `ChannelManagementFailure`。配置只读；任务和连接登记在 `request.resources`，使用 `remaining_timeout()` 和 `check_cancelled()` 遵守宿主预算。
- `ChannelDefinition.authorization_fields` 是允许授权结果写回的字符串配置字段名元组，默认空。JSON 描述对应 `config_schema.x-qwenpaw-authorization-fields`。声明 `channel.management.qrcode.v1` 或 `channel.management.verify.v1` 后才能执行相应管理操作；声明 `channel.auth.qrcode.v1` 后，运行中的 `ch.auth.required(scan_url)` 可请求宿主展示扫码地址。
- `ChannelResponse.approval` 提供审批编号、工具名称和严重程度。验证平台按钮回调后，使用 `ChannelApprovalAction(request_id, decision, message)` 调用 `ch.approvals.resolve()`；`decision` 只能是 `approve` 或 `deny`，`message` 提供真实平台身份与路由，正文会被忽略。返回 `accepted` 仅表示动作入队，最终权限和结果由宿主决定。声明 `send.approval_resolution.v1` 后可通过 `ChannelResponse.approval_resolution` 展示最终结果。

静态渠道重载目前需要提供独立来源供宿主重新暂存和校验，例如 `host.reload(plugin_id, new_source=source)`。原地修改已安装代码后直接重载仍由宿主拒绝。

独占资源也从 SDK 1.2.0 引入。`ChannelDefinition.exclusive_resources` 接受 `ChannelExclusiveResource(namespace, fields, operations=("run",))` 元组，JSON 对应 `config_schema.x-qwenpaw-exclusive-resources` 数组。`fields` 是配置中字符串或整数的字段名元组，多个字段整体识别一个资源；例如服务器加账号，或监听地址加端口。宿主使用校验和规范化后的配置生成不含原始值的标识，在启动之前检查冲突，在真实退出之后释放。

`operations` 可声明 `run`、`qrcode.fetch`、`qrcode.poll`、`connection.verify`，默认只占用运行阶段。授权缓存可声明扫码操作，避免多个临时进程同时修改。不同插件要协调同一个资源，必须使用相同 namespace 和相同字段值顺序；命名空间、字段名本身不赋予文件或网络访问权限。空值会拒绝启动。此机制协调同一个宿主进程内的声明，不替代操作系统端口占用、文件锁或多个宿主之间的协调，也不会自动发现路径别名、符号链接或旧插件未声明的资源。

HTTP/WebSocket 回调从 SDK 1.2.0 使用 `qwenpaw.plugins.channel_ingress`：在 `ChannelDefinition.ingress_routes` 声明 `ChannelIngressRoute(method, path)`，并声明 `ingress_endpoint`。`path` 是本渠道命名空间下的固定相对路径，不支持任意宿主路由或通配符。监听服务使用 `ch.ingress.path` 作为路径前缀，并登记到 `ch.resources`。

`ch.ingress.register/update(ChannelIngressSpec(host, port, protocol, readiness, public_base_url))` 返回绑定；仅接受 loopback 转发目标。`binding.url(path)` 生成带工作区路由标识的已声明回调地址；`binding.verify(headers)` 校验当前宿主转发并返回原始 URL，随后必须由插件继续验证平台签名。旧绑定在更新或关闭后不能使用。`close()` 等待宿主在途转发结束，监听服务本身仍由插件资源作用域关闭。模板本身没有建立监听，因此不能当作这项能力的验收证据。

结构化内容从 SDK 1.2.0 引入：声明 `send.structured_parts.v1`，并设置 `ResponsePolicy(content_source="semantic")`。默认 `"rendered"` 保留现有宿主展示方式。`ChannelResponse.content` 的每项是继承 `ContentBlock` 的 `ChannelContent`，新增 `role`（`message/reasoning/refusal/rendered`）；嵌套 `output` 为字符串或 `tuple[ChannelContent, ...]`。

- 正文为 `type="text", role="message"`；思考为 `type="thinking", role="reasoning"`；拒绝为 `type="text", role="refusal"`；宿主已排版的工具进度为 `role="rendered"`。
- 工具调用和结果使用 `type="tool_call"/"tool_result"`，通过 `id/name` 对应；`arguments/output` 是经过显示设置过滤和长度限制的预览，不能当作完整执行参数。结果保留宿主提供的 `state`（例如 `success/error/interrupted/denied`）；缺少状态时为空字符串。
- 工具结果中的文本、图片、音频、视频和文件保持先后顺序，媒体使用 `attachment`。宿主先应用隐藏思考、工具调用、结果和详情的设置。隐藏工具结果时，外部工具允许展示的媒体仍可独立发送；宿主内部工具的媒体继续隐藏。
- 结构化事件不参与文本合并，避免把不同语义或工具边界拼平。`text_merge_delay_ms` 仍可用于普通直接发送和已格式化发送。完成事件中的无传输地址媒体引用不会变成任意宿主文件访问。

这是一套渠道展示内容类型，不是模型原始上下文导出；通用 `Message/ContentBlock` 的已有协议不因渠道拒绝标记而改变。媒体实际上传、卡片排版和平台业务规则仍由渠道实现。
