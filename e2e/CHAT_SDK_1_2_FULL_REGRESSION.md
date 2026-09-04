# Chat SDK 1.2 全量回归用例

## 1. 测试对象

- 宿主：CoPaw / QwenPaw Console Chat
- SDK：`@agentscope-ai/chat@1.2.0-beta.1788428294123`
- 重点变更：会话级消息与 Loading 隔离、受控会话加载、异步取消协议、响应卡 `messageId`、函数/组件调用渲染和新版请求数据结构
- 队列边界：不启用 AgentScopeRuntimeWebUI 延迟队列；继续使用 CoPaw 既有输入队列、后台发送和多标签页 ownership
- 执行原则：自动化、真实浏览器、真实后端/模型三层证据分开记录；未执行项不得标记为通过

## 2. 通过标准

1. P0 用例全部通过；P1 无阻断性失败。
2. TypeScript、Chat 定向单测、Console 全量单测和生产构建全部通过。
3. 页面无空白、无框架错误遮罩、无与本次升级相关的 console error。
4. 请求的 `session_id`、`user_id`、`channel`、`agent_id` 在直接发送及 CoPaw 既有队列的排队、重试、跨 Agent/会话切换后均保持入队/提交时快照。
5. 停止生成同时满足：本地 SSE 立即停止、后端收到正确会话 ID、重复点击不重复污染状态。
6. 多会话并行时，消息、Loading、重连和操作按钮均不串会话。

## 3. AgentScopeRuntimeWebUI 对话完整链路（非队列）

### 3.1 场景定义

| 字段     | 内容                                                                                                              |
| -------- | ----------------------------------------------------------------------------------------------------------------- |
| 用例 ID  | `SDK-E2E-CHAT-001`                                                                                                |
| 优先级   | P0                                                                                                                |
| 目标     | 在一个真实 Chat 内串联验证新会话、直接发送、SSE 流式渲染、工具卡、完成持久化、生成中刷新重连、Stop 以及上下文续问 |
| 排除范围 | CoPaw 延迟队列、后台 drain、队列重试、队列多标签页 ownership；这些仍由 `SDK-QUE-*` 覆盖                           |

这不是多个彼此独立的冒烟用例，而是一条必须使用同一 Agent、同一 Chat 串行完成的故事线。一旦中间变更 Agent、手工创建新 Chat 或转入队列发送，应当判定本轮证据无效并重新执行。

### 3.2 前置条件与标识

1. 选择一个已配置可用模型的测试 Agent；当前标签页已获得 CoPaw Web Lock ownership，当前会话队列为空。
2. 通过普通 Enter 或发送按钮直接提交；不使用 Ctrl/Cmd+Enter，不在非 owner 标签页操作。
3. 准备唯一标记 `CHAIN-<timestamp>`，所有轮次均使用该标记定位请求、SSE 事件和持久化消息。
4. 记录三类不可混用的标识：
   - `localId`：旧数据兼容场景中的临时 ID，形如 `^\d+-[a-z0-9]+$`；当前创建接口先返回后端 Chat UUID，再交给 SDK。
   - `chatUuid`：后端 `ChatSpec.id`，用于 URL、历史会话选中、`GET /api/chats/<chatUuid>` 和 Stop。
   - `runtimeSessionId`：`ChatSpec.session_id` / Runtime `session_id`，用于对话上下文和 reconnect；它不得被当作 Chat UUID。
5. 工具链路使用测试 Agent 已开启的一个只读、可重复执行工具，并在记录中写明工具名。协议细节可由单元测试覆盖；功能验收必须使用浏览器工具和真实模型，不以 Playwright 脚本、chat-mock 或伪造响应替代。

### 3.3 串行执行步骤

| 阶段              | 操作                                                                                    | 必须观察的结果                                                                                                                                                                              |
| ----------------- | --------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| A. 初始化         | 打开 `/chat`，确认输入区和欢迎页可用，新建空白会话                                      | 页面不自动选中旧 Chat；显式创建先调用 `POST /api/chats`，返回 Chat UUID 后 SDK 才接受该会话；无用户消息、无 `/api/console/chat` 请求                                                        |
| B. 首轮直发       | 输入“记住 `CHAIN-<timestamp>`，调用指定只读工具，最终回答原样返回标记”并普通发送        | 只出现一条用户卡，只发起一个 `POST /api/console/chat`；body 为 `stream:true`，仅包含本轮用户输入，`session_id/user_id/channel` 来自当前 Session 快照，`X-Agent-Id` 为当前 Agent             |
| C. ID 解析        | 在创建完成及首轮 SSE 进行时观察会话列表和 URL                                           | 后端列表返回 `chatUuid + runtimeSessionId`；URL 仅从 `/chat` 变为 `/chat/<chatUuid>` 一次，历史抽屉中该 Chat 为 active；正在流式生成的消息不闪空、不重挂载，不得请求 `/api/chats/<localId>` |
| D. SSE 与卡片     | 等待 reasoning/message 增量、工具调用及工具结果                                         | 文本只增长不重复；tool call/output 合并到同一工具卡，可展开查看，不出现 `Unknown type`；工具卡、Loading 和操作按钮只属于当前 `chatUuid`                                                     |
| E. 首轮完成       | 等待 completed response 和本轮 `turn_usage`                                             | 最终回答包含一次唯一标记；Loading 结束，回复操作区出现，`turn_usage` 不产生空卡；`GET /api/chats/<chatUuid>` 为 `idle`，持久化历史中用户输入和完成回复各一份                                |
| F. 生成中刷新     | 第二轮发送一个可稳定持续输出的请求；出现至少 3 段增量后刷新 `/chat/<chatUuid>`          | 刷新后先通过历史读取到 `status:running`，再且仅发起一个 `POST /api/console/chat`，body 为 `reconnect:true`、`session_id:runtimeSessionId`，不携带新用户 input，不开启第二个 run             |
| G. replay 转 live | 观察重连 SSE 的已回放部分、`replay_end` 边界和后续实时增量                              | 边界前内容快进渲染，不逐 token 重放；`replay_end` 不生成卡片、不中断 builder；边界后增量继续写入原回复，最终文本无重复、无缺口                                                              |
| H. Stop 与恢复    | 第三轮发送长输出，收到增量后点击 Stop，紧接着第四轮询问“我之前要你记住的校验码是什么？” | 本地 SSE 立即终止，仅有一个 `POST /api/console/chat/stop?chat_id=<chatUuid>`，Stop 后无新 token，历史状态回到 `idle`；第四轮可正常提交并在原 Chat 内回答唯一标记                            |
| I. 最终恢复       | 第四轮完成后直接重新打开 `/chat/<chatUuid>`                                             | URL、active 会话、`runtimeSessionId`、用户卡、工具卡、已完成回复和 Stop 后的可继续交互状态一致；无无限 reconnect、无永久 Loading、无 console error                                          |

### 3.4 通过标准与失败定位

- A～I 必须在同一 `chatUuid` 中全部通过，并且四次用户提交均未进入 CoPaw 队列，才可将 `SDK-E2E-CHAT-001` 标记为 Pass。
- `localId` 被用于 `GET /api/chats/*` 或 Stop：会话 ID 映射/迁移失败。
- URL 改为 `runtimeSessionId` 或两个 Chat 因共享 `runtimeSessionId` 而显示同一消息：Chat UUID 与 Runtime Session 身份被错误合并。
- 刷新后又出现含 input 的普通请求或后端返回 409：reconnect 被错分类为新运行。
- `replay_end` 后空白、报 builder error 或文本重复：replay 快进与 live 边界处理失败。
- Stop 请求使用 `runtimeSessionId`、返回后仍有 token，或下一轮不能发送：取消协议或 Runtime 状态清理失败。
- 唯一标记未出现时先比对原始 SSE：SSE 已有而 UI 未显示属于 WebUI 链路失败；SSE 本身未产生则属于模型/测试环境不稳定，应更换可确定执行的测试模型后重试。
- 只用 fixture、单测或构建结果不能标记本用例通过；至少需要一次真实浏览器 + 真实 Runtime/模型执行证据。

### 3.5 证据记录模板

| 证据项 | 记录内容                                                                    |
| ------ | --------------------------------------------------------------------------- |
| 环境   | commit SHA、SDK 版本、Agent ID、模型、浏览器及版本                          |
| 身份   | `localId`、`chatUuid`、`runtimeSessionId`，以及三者首次出现的时间点         |
| 请求   | 首轮直发、reconnect、Stop 的 URL、关键 body/header、HTTP 状态和请求次数     |
| 流事件 | 首轮事件类型顺序，reconnect 的 `replay_end` 位置，completed/错误事件        |
| 页面   | ID 迁移时、重连后、Stop 后和最终刷新后的截图；console error 记录            |
| 持久化 | `GET /api/chats/<chatUuid>` 在 running/idle 阶段的 status 和消息摘要        |
| 结果   | A～I 逐阶段 Pass/Fail；任一阶段未执行时整体为 Pending，不得写“完整链路通过” |

## 4. 依赖与静态契约

| ID          | 优先级 | 用例与步骤                                    | 预期结果                                                     | 建议层级      |
| ----------- | ------ | --------------------------------------------- | ------------------------------------------------------------ | ------------- |
| SDK-CON-001 | P0     | 检查 `package.json` 与 lockfile               | 两处均精确锁定目标 beta 版本                                 | 静态          |
| SDK-CON-002 | P0     | 校验 npm tarball SHA-1 / integrity            | 与 registry 元数据一致                                       | 安装          |
| SDK-CON-003 | P0     | 安装后读取实际包版本                          | `node_modules` 为目标版本，无旧版残留                        | 安装          |
| SDK-CON-004 | P0     | 运行 `tsc -b --noEmit`                        | 0 类型错误                                                   | 自动化        |
| SDK-CON-005 | P0     | 运行 Chat 兼容性定向测试                      | 请求快照、旧队列兼容、取消、卡片契约全部通过                 | 自动化        |
| SDK-CON-006 | P1     | 运行 Console 全量 Vitest                      | 无新增失败；若有既有失败需单列                               | 自动化        |
| SDK-CON-007 | P0     | 运行生产构建                                  | Vite、Monaco CSS、预压缩、首包检查均通过                     | 构建          |
| SDK-CON-008 | P1     | 检查 peer dependency / audit 输出             | 既有告警与本次新增风险分开记录，不做越界升级                 | 静态          |
| SDK-CON-009 | P0     | 直接传入 class singleton 形式的 `session.api` | SDK 正确保留原型方法及 this 绑定，不需要业务侧对象展开适配器 | 自动化/浏览器 |

## 5. 基础会话与流式响应

| ID           | 优先级 | 前置与步骤                        | 预期结果                                                                 | 建议层级      |
| ------------ | ------ | --------------------------------- | ------------------------------------------------------------------------ | ------------- |
| SDK-CHAT-001 | P0     | 打开 `/chat`                      | 欢迎页、输入框、主操作可见，无自动跳到历史会话                           | 浏览器        |
| SDK-CHAT-002 | P0     | 新会话发送短文本                  | 仅出现一条用户消息，请求只发送一次                                       | 浏览器/API    |
| SDK-CHAT-003 | P0     | 观察 SSE 增量输出                 | 文本连续增长，无重复 token、闪退或跨会话写入                             | 浏览器        |
| SDK-CHAT-004 | P0     | 等待完成事件                      | Loading 结束，响应状态完成，操作区出现                                   | 浏览器/API    |
| SDK-CHAT-005 | P0     | 连续三轮上下文问答                | 历史顺序正确，后续请求包含当前会话历史                                   | 浏览器/API    |
| SDK-CHAT-006 | P0     | 生成中点击 Stop                   | 本地流立即停止，后端 stop 使用真实会话 ID，状态变为 interrupted/canceled | 浏览器/API    |
| SDK-CHAT-007 | P1     | 快速重复点击 Stop                 | stop 只作用于当前请求，不重复结束后续请求                                | 浏览器/API    |
| SDK-CHAT-008 | P1     | 模拟后端 stop 失败                | 本地流仍终止，失败被记录但页面可继续发送                                 | 自动化/浏览器 |
| SDK-CHAT-009 | P0     | 对最后一条完成响应点击重新生成    | 使用正确 `messageId` 删除/重建目标回复，不影响其他轮次                   | 浏览器        |
| SDK-CHAT-010 | P1     | 复制回复                          | 复制内容与可见回复一致                                                   | 浏览器        |
| SDK-CHAT-011 | P1     | 输入中文、emoji、代码块、特殊字符 | 输入和渲染不丢字符、不注入 HTML                                          | 浏览器        |
| SDK-CHAT-012 | P1     | 模拟 HTTP 非 2xx / 非法 SSE chunk | 显示可理解错误，Loading 可恢复，可再次发送                               | 自动化/浏览器 |

## 6. 响应卡与扩展渲染

| ID          | 优先级 | 前置与步骤                                    | 预期结果                                      | 建议层级      |
| ----------- | ------ | --------------------------------------------- | --------------------------------------------- | ------------- |
| SDK-REN-001 | P0     | 返回普通 message + reasoning                  | Markdown、思考过程分别正确渲染                | 自动化/浏览器 |
| SDK-REN-002 | P0     | 返回 tool_call / tool_call_output             | 输入输出合并到同一工具卡，不显示 Unknown type | 自动化/浏览器 |
| SDK-REN-003 | P0     | 返回 function_call / output                   | 走工具卡路径，可展开查看                      | 自动化/浏览器 |
| SDK-REN-004 | P0     | 返回 component_call / output                  | 走工具卡路径，可展开查看                      | 自动化/浏览器 |
| SDK-REN-005 | P0     | 返回 MCP call / output / approval             | 工具卡和审批交互均可用                        | 自动化/浏览器 |
| SDK-REN-006 | P1     | 返回 error / refusal / heartbeat              | 错误和拒答可见，heartbeat 不产生空卡          | 自动化        |
| SDK-REN-007 | P0     | 最后一条响应显示操作区                        | `messageId` 正确透传，重新生成定位准确        | 自动化/浏览器 |
| SDK-REN-008 | P1     | 注册 request/response prepend、append、render | 插件内容位置正确，fallback 可回到默认卡片     | 自动化/浏览器 |
| SDK-REN-009 | P1     | 完成响应包含文件产物                          | Artifact 列表仅在完成后出现，文件可打开       | 浏览器        |

## 7. 会话与 Agent 隔离

| ID          | 优先级 | 前置与步骤                                               | 预期结果                                                                  | 建议层级      |
| ----------- | ------ | -------------------------------------------------------- | ------------------------------------------------------------------------- | ------------- |
| SDK-SES-001 | P0     | 直接访问 `/chat/<uuid>`                                  | 只加载目标会话，不短暂展示第一条历史会话                                  | 浏览器/API    |
| SDK-SES-002 | P0     | 从历史会话返回 `/chat`                                   | 新会话页为空，不复用旧消息/Loading                                        | 浏览器        |
| SDK-SES-003 | P0     | A、B 会话来回切换                                        | 每个会话只显示自己的消息和操作状态                                        | 浏览器        |
| SDK-SES-004 | P0     | A 流式生成时切到 B                                       | A 的后续 token 不写入 B；B 输入可用                                       | 浏览器/API    |
| SDK-SES-005 | P0     | A 生成中执行 A→B→A                                       | A 状态可正确恢复/重连，无重复回复                                         | 浏览器/API    |
| SDK-SES-006 | P0     | 快速连续点击 A/B/C                                       | 最后一次选择生效，旧请求结果被丢弃                                        | 自动化/浏览器 |
| SDK-SES-007 | P0     | 刷新仍在生成的会话                                       | 通过 reconnect 恢复，已回放部分不重复动画                                 | 自动化/浏览器 |
| SDK-SES-008 | P1     | 刷新已完成会话                                           | 历史完整、时间与卡片状态正确                                              | 浏览器        |
| SDK-SES-009 | P0     | 新会话首条消息触发本地 ID→UUID                           | URL、消息、CoPaw 队列、项目目录一次迁移，无整页消息闪空                   | 自动化/浏览器 |
| SDK-SES-010 | P0     | Agent A→B→A 切换                                         | 会话列表、草稿、身份、消息按 Agent 隔离                                   | 自动化/浏览器 |
| SDK-SES-011 | P0     | 切换不同 user/channel 来源会话                           | 请求沿用目标会话身份，不继承旧 window 全局值                              | 自动化/API    |
| SDK-SES-012 | P1     | 删除当前/非当前会话                                      | 列表、缓存、队列、审批级别与文件工作区同步清理                            | 自动化/浏览器 |
| SDK-SES-013 | P0     | A、B 使用不同 `id` 但共享 `sessionId`，先打开 A 再点击 B | URL 切到 B，调用 B 的详情接口，只显示 B 消息，不能把共享别名当作同一 Chat | 浏览器/API    |
| SDK-SES-014 | P0     | 历史会话→新建→返回历史→再次新建                          | 两次均单击一次即进入空白页，旧消息不因 URL/会话列表竞态重新出现           | 浏览器        |
| SDK-SES-015 | P0     | 深链中的 Runtime `session_id` 也具有 UUID 外形           | 唯一匹配时加载真实 Chat UUID 并规范化 URL；重复别名时不猜测、不串 Chat    | 自动化/浏览器 |

## 8. CoPaw 既有输入队列、后台发送与多标签页

> 本节验证宿主原有队列在 SDK 1.2 下没有回归，不代表接入 AgentScopeRuntimeWebUI 的 `sender.queue` 延迟队列。

| ID          | 优先级 | 前置与步骤                                                   | 预期结果                                                                         | 建议层级      |
| ----------- | ------ | ------------------------------------------------------------ | -------------------------------------------------------------------------------- | ------------- |
| SDK-QUE-001 | P0     | 空闲时 Ctrl/Cmd+Enter                                        | 消息先入队，再按自动发送策略处理；不得绕过队列或重复提交                         | 浏览器/API    |
| SDK-QUE-002 | P0     | 生成中按 Enter                                               | 新输入入队，当前流不中断                                                         | 浏览器        |
| SDK-QUE-003 | P0     | 连续入队 3 条                                                | 严格 FIFO，任一条只发送一次                                                      | 自动化/浏览器 |
| SDK-QUE-004 | P0     | 带附件/mention/quote 入队                                    | 序列化后内容完整，刷新后仍可恢复                                                 | 自动化/浏览器 |
| SDK-QUE-005 | P0     | 入队后检查请求                                               | 固化 session/user/channel/agent/context/submission identity                      | 自动化/API    |
| SDK-QUE-006 | P0     | Agent A 入队后切 B                                           | 条目仍发送给 A，不污染 B                                                         | 自动化/浏览器 |
| SDK-QUE-007 | P0     | 会话 A 入队后切 B                                            | 条目仍发送给 A，会话 B 无新增消息                                                | 自动化/浏览器 |
| SDK-QUE-008 | P0     | 当前回复完成                                                 | 自动发送队首，完成后继续下一条                                                   | 浏览器/API    |
| SDK-QUE-009 | P1     | 暂停/恢复队列                                                | 暂停不出队；恢复从队首继续                                                       | 自动化/浏览器 |
| SDK-QUE-010 | P1     | 编辑待发送条目                                               | 仅文本更新，身份和附件快照保留                                                   | 自动化/浏览器 |
| SDK-QUE-011 | P1     | 删除待发送条目                                               | 目标删除，其他顺序不变                                                           | 自动化/浏览器 |
| SDK-QUE-012 | P1     | 拖拽重排                                                     | 新顺序持久化并按新顺序发送                                                       | 自动化/浏览器 |
| SDK-QUE-013 | P0     | 点击“立即发送”                                               | 当前流被正确停止，目标仍存在校验后再发送                                         | 浏览器/API    |
| SDK-QUE-014 | P0     | 模拟发送失败后重试                                           | 同一条目 retryCount 更新，不复制用户消息                                         | 自动化/浏览器 |
| SDK-QUE-015 | P1     | 跳过失败项                                                   | 失败项移除，下一条继续                                                           | 自动化/浏览器 |
| SDK-QUE-016 | P1     | 入队达到上限再加一条                                         | 明确提示队列已满，原队列不变                                                     | 自动化/浏览器 |
| SDK-QUE-017 | P0     | `new` 队列在首发后迁移 UUID                                  | 无丢失、无重复、FIFO 不变                                                        | 自动化        |
| SDK-QUE-018 | P0     | 两标签页打开同一会话                                         | 单一 owner；非 owner 显示只入队提示                                              | 浏览器        |
| SDK-QUE-019 | P0     | 关闭 owner 标签页                                            | 另一标签页接管后续发送，不重复当前项                                             | 浏览器        |
| SDK-QUE-020 | P0     | ChatPage 卸载但队列未空                                      | 后台 drain 使用快照继续，不读取当前页面 Agent                                    | 自动化/API    |
| SDK-QUE-021 | P0     | 后端已 accepted 后页面切换/卸载                              | 条目不恢复、不重复提交                                                           | 自动化/API    |
| SDK-QUE-022 | P1     | 后端运行态 unknown / 查询失败                                | 不越过正在执行项；按策略退避重试                                                 | 自动化/API    |
| SDK-QUE-023 | P0     | 两标签页分别使用 Agent A/B，各自在流式中追加队列消息         | 两边流均持续增量渲染并各自排空队列；消息、响应和 Agent 身份不串页                | 浏览器/API    |
| SDK-QUE-024 | P0     | Runtime ID 深链已有失败队列，另一个 Agent 标签页也有独立队列 | URL 规范化时队列与会话资源迁移到 Chat UUID；恢复后 FIFO 排空，另一标签页不受影响 | 自动化/浏览器 |

## 9. 输入、附件与快捷交互

| ID          | 优先级 | 前置与步骤                           | 预期结果                                         | 建议层级      |
| ----------- | ------ | ------------------------------------ | ------------------------------------------------ | ------------- |
| SDK-INP-001 | P0     | 点击发送按钮                         | 提交一次，输入框按策略清空                       | 浏览器        |
| SDK-INP-002 | P0     | Enter / Shift+Enter                  | Enter 发送；Shift+Enter 换行                     | 浏览器        |
| SDK-INP-003 | P0     | 中文 IME composition 中按 Enter      | 不误发送，composition end 后可发送               | 浏览器        |
| SDK-INP-004 | P1     | 配置可提及项后输入 `@` 并等待 1.5 秒 | mention 列表稳定存在，可选中路径                 | 浏览器        |
| SDK-INP-005 | P1     | 输入 `/` 并选择命令                  | suggestions 展示，选择后内容正确                 | 浏览器        |
| SDK-INP-006 | P0     | 上传普通附件并发送                   | 上传成功、预览与请求内容一致                     | 浏览器/API    |
| SDK-INP-007 | P1     | 粘贴超长文本                         | 自动转 txt 附件且 prompt 正确                    | 浏览器/API    |
| SDK-INP-008 | P1     | 空输入、全空格、超上限               | 不提交并给出合理反馈                             | 浏览器        |
| SDK-INP-009 | P1     | 图片/音频/视频/文件组合              | 能力开关、预览和请求类型正确                     | 浏览器/API    |
| SDK-INP-010 | P1     | Agent 间切换草稿                     | 草稿按 Agent 隔离，直接发送后仅清当前 Agent 草稿 | 自动化/浏览器 |

## 10. 稳定性、性能与兼容性

| ID          | 优先级 | 前置与步骤                            | 预期结果                                           | 建议层级      |
| ----------- | ------ | ------------------------------------- | -------------------------------------------------- | ------------- |
| SDK-NFR-001 | P0     | 页面加载并完成一次交互                | 无框架错误遮罩、无相关 console error               | 浏览器        |
| SDK-NFR-002 | P1     | 1920×1080 / 1440×900 / 移动宽度       | 输入区、操作区、队列面板不裁切重叠                 | 浏览器        |
| SDK-NFR-003 | P1     | 仅键盘操作发送、Stop、会话切换        | 焦点顺序合理，按钮有可访问名称                     | 浏览器        |
| SDK-NFR-004 | P1     | 加载超长历史并滚动                    | 首屏可交互，无明显卡死，历史加载指示仅请求时动画   | 自动化/浏览器 |
| SDK-NFR-005 | P1     | 后台/前台切换标签页                   | 不重复 reconnect 或 submit，Loading 与真实状态一致 | 浏览器        |
| SDK-NFR-006 | P1     | localStorage 中放入旧 schema/损坏队列 | 安全回退为空队列，不阻断 Chat                      | 自动化/浏览器 |
| SDK-NFR-007 | P1     | Chrome 与 Safari/WebKit 核心冒烟      | 核心发送、Stop、切会话一致                         | E2E           |
| SDK-NFR-008 | P2     | 慢网/高延迟/离线恢复                  | 提示清晰，重试不重复提交                           | E2E           |

## 11. AgentScopeRuntimeWebUI 公共能力补充

> 本节补齐原用例未独立覆盖的公开能力。CoPaw 当前未配置 `sender.mentions`，且明确不启用 SDK 内置 `sender.queue`；这两类用例必须在 SDK fixture/demo 中验证，不能用 CoPaw 生产页面的结果代替。CoPaw 自维护队列仍由第 8 节验证。

### 11.1 文件上传与附件生命周期

| ID           | 优先级 | 前置与步骤                                            | 预期结果                                                              | 建议层级           |
| ------------ | ------ | ----------------------------------------------------- | --------------------------------------------------------------------- | ------------------ |
| SDK-FILE-001 | P0     | 点击附件按钮，选择一个允许类型的小文件并等待上传完成  | 上传中状态可见；完成后出现预览；发送体保留 URL、名称、大小和类型      | CoPaw 浏览器/API   |
| SDK-FILE-002 | P1     | 分别通过拖拽和剪贴板粘贴上传文件                      | 两种入口均走同一上传校验和 `customRequest`，不会生成重复附件          | SDK fixture/浏览器 |
| SDK-FILE-003 | P0     | 上传完成后删除附件，再发送剩余文本                    | 被删除附件不进入请求；预览和内部 `fileList/attachments` 同步清理      | CoPaw 浏览器/API   |
| SDK-FILE-004 | P0     | 模拟上传 4xx/5xx、超时或 `customRequest` reject       | 显示失败状态/提示；失败文件不能提交；移除或重试后输入区可继续使用     | 自动化/浏览器      |
| SDK-FILE-005 | P1     | 上传超过大小限制、不支持的媒体类型和超过数量上限      | 上传前阻止或明确报错；已成功附件不丢失；不会发起无效聊天请求          | CoPaw 浏览器       |
| SDK-FILE-006 | P0     | 附件仍在上传时点击发送或按 Enter                      | 不提交半成品附件；上传完成后可正常发送且只发送一次                    | SDK fixture/浏览器 |
| SDK-FILE-007 | P1     | 多文件部分成功、部分失败后删除失败项并发送            | 请求只包含成功项，顺序和预览一致                                      | SDK fixture/API    |
| SDK-FILE-008 | P1     | 超长文本自动转 txt；上传中切换语言，再手工编辑 prompt | 自动 prompt 可随语言更新；手工编辑后不被覆盖；最终仅包含一个 txt 附件 | SDK fixture/浏览器 |
| SDK-FILE-009 | P0     | 仅附件、无文本直接发送，并在历史刷新后查看用户卡      | 允许发送；用户卡附件可恢复；不会生成空文本请求或丢失附件              | CoPaw 浏览器/API   |
| SDK-FILE-010 | P1     | 点击历史消息中的文件、图片、音频和视频                | `replaceMediaURL` 生效；文件走 `onFileCardClick`；媒体预览/下载可用   | CoPaw 浏览器       |

### 11.2 Mentions 完整交互

| ID          | 优先级 | 前置与步骤                                               | 预期结果                                                                    | 建议层级           |
| ----------- | ------ | -------------------------------------------------------- | --------------------------------------------------------------------------- | ------------------ |
| SDK-MEN-001 | P0     | 配置静态 items，输入 trigger 并键盘选择一个 mention      | 候选出现；上下键/Enter 可选；输入区和 `mentions` 数据同步                   | SDK fixture/浏览器 |
| SDK-MEN-002 | P1     | 分别验证 `header` 与 `inline` displayMode                | header 显示胶囊；inline 插入指定文本；提交 query 与 mention 数据符合配置    | SDK fixture/浏览器 |
| SDK-MEN-003 | P0     | inline mention 前后插入、删除、粘贴文本                  | range 正确重映射；被破坏的 mention 自动移除，未受影响项继续保留             | 自动化/浏览器      |
| SDK-MEN-004 | P1     | 异步加载 items，先慢请求再关闭/重新打开候选              | 旧请求可 abort；loading/empty 文案正确；过期结果不覆盖新结果                | 自动化/浏览器      |
| SDK-MEN-005 | P1     | 验证 cacheItems、maxOptions、disabled 和 allowDuplicates | 缓存、数量限制、禁用项和去重策略分别生效                                    | 自动化/浏览器      |
| SDK-MEN-006 | P1     | 自定义 trigger 和 getInsertText                          | 候选匹配、插入文本和光标位置正确                                            | SDK fixture/浏览器 |
| SDK-MEN-007 | P0     | mention-only、mention+文本直接发送                       | 允许 mention-only 提交；`api.fetch.mentions` 为可序列化 `{value,type}` 快照 | SDK fixture/API    |
| SDK-MEN-008 | P0     | mention 入 CoPaw 自维护队列，刷新、编辑、重试后发送      | mention 快照不丢失、不重复，不随当前输入或 Agent 改变                       | 自动化/CoPaw API   |
| SDK-MEN-009 | P1     | mention 候选打开时按 Enter/Shift+Enter/Escape/Tab        | 不误发送；选择、换行、关闭和焦点行为符合键盘约定                            | SDK fixture/浏览器 |
| SDK-MEN-010 | P1     | disabled/loading/切换 session 后检查 mention 状态        | 禁用时不可选择；提交或切会话后清理正确，不串到其他会话                      | SDK fixture/浏览器 |

### 11.3 用户消息定位与长历史分页

| ID          | 优先级 | 前置与步骤                                         | 预期结果                                                       | 建议层级           |
| ----------- | ------ | -------------------------------------------------- | -------------------------------------------------------------- | ------------------ |
| SDK-ANC-001 | P0     | 用户消息少于/达到 `minCount`                       | 少于阈值不展示；达到阈值后展示定位控件                         | 自动化/浏览器      |
| SDK-ANC-002 | P0     | navigator 模式点击上一条、下一条和目录中的目标消息 | 目标用户消息滚动到可视顶部并短暂高亮；active 项同步            | CoPaw 浏览器       |
| SDK-ANC-003 | P1     | 打开目录后点击“定位当前消息”                       | 目录滚动到 active 项，不改变对话主滚动位置                     | 浏览器             |
| SDK-ANC-004 | P1     | minimap 模式加载密集用户消息                       | 位置按历史比例显示；小于 `minGap` 的锚点聚合；tooltip 显示正确 | SDK fixture/浏览器 |
| SDK-ANC-005 | P1     | 用户消息超过 `badgeMaxCount`                       | 数量徽标按上限显示，例如 `99+`                                 | 自动化/浏览器      |
| SDK-ANC-006 | P0     | 点击尚未挂载、位于分页窗口外的远端用户消息         | 先扩展历史窗口，再定位目标；不得跳错消息、卡死或抛出未处理异常 | 自动化/浏览器      |
| SDK-ANC-007 | P1     | 用户消息包含附件、时间戳和空文本                   | tooltip/目录显示时间、预览和附件类型数量；空文本仍有可识别预览 | 自动化/浏览器      |
| SDK-ANC-008 | P0     | 流式回复增长、窗口缩放和历史增量加载期间保持锚点   | 锚点位置重新计算；当前 active 不无故跳动；定位后稳定在目标顶部 | CoPaw 浏览器       |
| SDK-ANC-009 | P1     | 配置 `enabled:false`，随后切换 Session             | 完全不展示锚点；切会话不残留旧 Session 的 active/目录状态      | 自动化/浏览器      |

### 11.4 主题、欢迎页、发送器和公开控制接口

| ID          | 优先级 | 前置与步骤                                                    | 预期结果                                                                 | 建议层级           |
| ----------- | ------ | ------------------------------------------------------------- | ------------------------------------------------------------------------ | ------------------ |
| SDK-UI-001  | P1     | 切换亮/暗主题、窄屏、locale 和 typography                     | 颜色、排版、文案和布局响应配置，无不可读文本或溢出                       | SDK fixture/浏览器 |
| SDK-UI-002  | P1     | 验证 welcome 字段、prompt 点击和自定义 render                 | 默认字段正确；prompt 只提交一次；自定义 render 可调用 onSubmit           | SDK fixture/浏览器 |
| SDK-UI-003  | P1     | 验证 placeholder、字符计数、actionAffix、前后/前缀 UI         | 所有插槽位置正确；字符上限、禁用和 loading 信息一致                      | SDK fixture/浏览器 |
| SDK-UI-004  | P1     | 验证 disclaimer、suggestions、speech 和自定义 input component | 文案/建议/语音/自定义输入均可操作；键盘发送约定不回归                    | SDK fixture/浏览器 |
| SDK-API-001 | P0     | beforeSubmit 返回 false 或 `{proceed,clear,query,...}`        | 中止、清空、文本替换、session/context/biz_params 覆盖分别按契约生效      | 自动化/API         |
| SDK-API-002 | P1     | 验证默认 baseURL/token/history 与自定义 parser/media/file     | 请求头和历史开关正确；解析、URL 替换、文件点击回调各执行一次             | SDK fixture/API    |
| SDK-REF-001 | P0     | 调用 ref.input 的 get/set content、loading、disabled、submit  | 状态可读写；submit 完整透传输入且返回可等待结果                          | 自动化/fixture     |
| SDK-REF-002 | P1     | 调用 ref.messages、ref.sessions 的公开读写/刷新接口           | 消息和会话状态一致；不存在的会话安全返回；不会绕过受控路由               | 自动化/fixture     |
| SDK-REF-003 | P0     | execution execute/subscribe/getActiveRun/cancel/resume        | 生命周期顺序、活动 Run、幂等 clientRequestId、取消与同 Run 重连符合契约  | 自动化/fixture     |
| SDK-EXT-001 | P1     | 验证 cards、customToolRenderConfig、actions/requestActions    | 自定义卡、工具和左右操作区正确调用；默认/替换行为和 messageId 均正确     | 自动化/浏览器      |
| SDK-SES-013 | P1     | SDK fixture 验证单会话、内置多会话列表和默认 localStorage API | multiple/hideBuiltInSessionList/default API 三种模式均可创建、切换和删除 | SDK fixture/浏览器 |

### 11.5 SDK 内置延迟队列独立回归

- SDK 源码 `InputQueue/__tests__/inputQueue.scenarios.zh-CN.md` 中 `IQ-A01～IQ-A22`、`IQ-M01～IQ-M17` 和 `IQ-BUG01` 全部纳入回归。
- 自动化用例验证 reducer、存储、route/visible key、失败恢复和 ownership；浏览器用例验证首发、临时 ID 迁移、跨 Session/Tab、立即发送、附件、重试、清空与自动滚动。
- CoPaw 页面必须继续断言 `sender.queue` 未配置；SDK 内置队列通过独立 fixture/demo 回归，不得同时开启两套队列进行混合测试。

## 12. 本分支执行状态

- 自动化、浏览器、真实后端/模型三类证据分别记录；未执行项保持 Pending。
- 本分支不启用 AgentScopeRuntimeWebUI 内置延迟队列，继续运行 CoPaw 既有输入队列；自动化必须断言 `sender.queue` 未配置。
- 非队列完整链路 `SDK-E2E-CHAT-001` 已在同一真实 Chat 串行执行：A～G 与 I 通过，H 的 Stop 后端取消失败，因此整体状态为 Fail。
- 已通过：TypeScript、格式检查、Chat/API 与 CoPaw 队列兼容定向测试，以及 Console 全量 Vitest（293 文件 / 2446 用例）。
- 已通过：生产构建（19348 modules）、Monaco CSS、368 个静态资源预压缩及首包门禁（9.51 MiB raw / 2.39 MiB Brotli）。
- 已通过：SDK 源码侧 Response/Execution 生命周期、Chat submission、Session 创建与身份、InputQueue reducer/持久化/ownership 等 25 条 Node 测试；`IQ-A*` 覆盖的 FIFO、失败恢复、编辑/删除/重排、临时 ID→真实 ID、附件-only 和多标签页 key 隔离均无失败。
- 已通过：当前运行中的 Chromium 只读回归；`/chat` 欢迎页与输入区正常，输入 `/` 展示 `/skills` 等快捷命令，恢复 `/chat/<uuid>` 后历史内容完整且对应历史项带 active 样式；当前会话只有 2 条用户消息，验证了默认 `minCount=3` 以下不展示用户消息定位器。
- 已通过：`1.2.0-beta.1788428294123` + 隔离后端 Chromium 新会话首发回归；首次点击新建即清空上一会话，URL 从 `/chat` 写入真实 UUID，历史抽屉对应会话带 active 选中态，深链刷新后仍恢复正确会话且无相关 console error。
- 已通过：`1.2.0-beta.1788428294123` + 隔离后端 Chromium 双标签页双 Agent 回归；tab1/scwD8P 与 tab2/PeXFEB 均处于真实模型运行态且各有 1 条 CoPaw 队列，tab1 切换到 PeXFEB 后恢复 tab2 的 URL、会话、Loading 与队列，切回 scwD8P 后也恢复原会话；两边队列均自动出队且各发送一次，没有跨 Agent 串消息。
- 本轮真实 Chromium 完整链路：同一 Chat `4680db77-696b-4b00-8cc8-172843acd5d2` 的新会话首发、真实 UUID 路由、流式完成、生成中刷新、同 Run reconnect、历史 active、上下文续问均通过；重连前后用户消息、工具卡和最终回复没有重复。
- 本轮真实 Chromium 用户消息定位：第 4 条用户消息后 navigator 出现；上一条/下一条、目录 4/5 条计数、点击目录项定位及首尾 disabled 状态均通过；少于 3 条时保持隐藏。
- 本轮真实 Chromium 文件：上传、预览、删除、重新上传、文本+附件发送及刷新恢复通过；超过 10000 字符自动生成 `prompt-*.txt` 并替换为上传提示通过。
- 本轮真实 Chromium CoPaw 队列：三条 FIFO、暂停/恢复、编辑、删除、清空、同会话双 Tab 同步、非 owner 提示、关闭 owner 后接管、切离会话后台 drain 与切回恢复均通过，所有成功场景只提交一次。
- **失败 P0：Stop/立即发送取消不闭环。** 点击 Stop 后本地 Loading 立即结束，但旧 `sleep 30` 工具继续运行并最终写入 `STOP-SHOULD-NOT-APPEAR`；随后续问期间出现多次 HTTP 409。流式中对队列项点击“立即发送”时目标项优先完成，但被打断的旧 `sleep 20` 仍随后完成并写入 `BASE-SHOULD-STOP`。因此 `SDK-CHAT-006`、`SDK-QUE-013` 和取消相关的完整链路 H 判 Fail。
- **失败 P0：仅附件发送未持久化。** 上传完成且输入为空时发送按钮可用，点击后本地出现用户附件卡，但没有流式回复；刷新同一深链后附件卡消失，用户消息定位计数从 5 回到 4。文本+同一附件的对照用例可以回复并在刷新后恢复，因此 `SDK-FILE-009` 判 Fail。
- CoPaw 页面确认未配置 `sender.mentions`：输入 `@` 等待 1.6 秒没有候选，这是接入边界而不是 SDK mentions Pass/Fail；`SDK-MEN-*` 仍须 SDK fixture。
- 质量门禁未全绿：仓库全量 ESLint 仍为既有基线 368 个问题（273 errors / 95 warnings）；本次没有为回归任务扩张范围清理历史 lint。
- 用例完整性结论：原 82 条不是 RuntimeWebUI 全功能覆盖；合并 PR #7382 已有场景后主文档共 125 个唯一 `SDK-*` 用例，并独立纳入 SDK 队列文档的 40 个 `IQ-*` 场景。是否“覆盖完全”仍以 SDK 公开类型新增能力审计为准，不能只看数量。
- Pending：失败任务重试、附件入 CoPaw 队列、拖拽重排、队列上限、SDK 内置队列 `IQ-M01～M17` fixture、mentions fixture、用户消息定位器远端分页/minimap/badgeMaxCount、Safari/WebKit 和全量 Python E2E。本次未修改 Python 文件，按回归约定不执行 pytest E2E；P0 失败修复并重跑前，整体回归结论为 Fail。

### PR #7382 历史证据与本次同步边界

- 保留原 PR 在 SDK `1.2.0-beta.1788236202658` 下记录的 `SDK-SES-013`、`SDK-SES-014`、`SDK-QUE-023` 隔离 Chromium 验证结果；这些是旧版本的历史证据，不代表当前 SDK 已重新通过这三个浏览器场景。
- 本次同步到 SDK `1.2.0-beta.1788428294123`，保留 CoPaw 后台队列的 foreground ownership 门禁及其 3 个单元测试；移除已由新 SDK 接管的 session API 原型转接和新建会话定时器补丁。
- 前述 Fail/Pending 为此前全量场景执行记录，不能由单元测试或构建通过自动改成 Pass；本次 PR 同步没有执行完整真实模型对话/队列 E2E。
- 2026-09-02 本次同步验证：Console 全量 Vitest 327 文件 / 3107 用例通过，类型与格式检查通过，生产构建、Monaco CSS、369 资源预压缩及首包门禁通过。Python 源码、测试和依赖声明与已全量验证的 `47c72331` 完全一致，复用该版本的单元 10271、契约 406、集成 1885 项通过记录，本次未重复运行 Python 测试。

## 2026-09-03 接入边界补充

- `/chat` 是独立的新草稿，不回退到 `lastActiveChatId`。新草稿队列/锁 key 为 `draft:<Agent>`，已创建会话使用 Chat UUID；这些 key 不能替代 Runtime `session_id`。
- CoPaw 的 `createSession` 返回 `{ sessions, session }`，其中 `session.id` 已经是后端 Chat UUID。普通创建不再依赖发送后从列表猜测 UUID；临时 ID 迁移只用于旧数据兼容。
- SDK 会话加载就绪由 Session API 适配层观测。SDK 内部输入桥接组件订阅就绪状态，队列调度读取状态，宿主不能因就绪变化重建整个 SDK options 而反复触发加载。
- SDK 管理发送接受后的输入快照清理。宿主不在请求前清空输入；失败保留草稿，成功也不能删除用户期间新写入的草稿或新上传的附件。
- 审批设置只随确认的创建/ID 解析迁移；普通 Agent/历史会话切换不能迁移，也不能覆盖目标已有设置。

| ID          | 前置与操作                                                    | 必须满足                                                              |
| ----------- | ------------------------------------------------------------- | --------------------------------------------------------------------- |
| SDK-INT-001 | 暂停历史加载，在输入区尝试直接发送、Ctrl/Cmd+Enter 和队列发送 | 加载完成前不提交、不丢草稿；完成后可发送，不重复加载、不出现渲染循环  |
| SDK-INT-002 | 两个标签页分别打开不同 Agent 的 `/chat` 并入队                | draft key、ownership、FIFO 各自独立；任一方创建 UUID 不带走另一方条目 |
| SDK-INT-003 | 恢复包含两个 Agent、附件及暂停状态的旧 `new` 队列             | 迁移串行且可重复执行，保留各方条目、顺序和暂停状态                    |
| SDK-INT-004 | 模型未配置或请求拒绝；发送途中继续编辑/上传                   | 原请求未接受时保留输入；接受后仅清理其对应快照                        |
| SDK-INT-005 | transport 输入为空                                            | 在模型查找及 POST 之前拒绝，不创建空请求、不清空草稿                  |
| SDK-INT-006 | 新草稿设置审批级别，随后打开历史/切换 Agent/真正创建会话      | 普通切换不迁移；确认创建只迁移当前 Agent 的设置，保留目标已有设置     |
| SDK-INT-007 | 对历史会话打开重命名并键盘提交                                | 输入框可访问、可编辑；提交不触发会话误选，名称正确保存                |

这些条目是验收要求，不表示已全部执行。报告必须分别记录单元测试、真实浏览器及真实模型的完成情况。

## 2026-09-04 Runtime ID 深链队列修复回归

- 本节记录上述历史执行状态之后的修复结果；第 12 节中的早期 Fail/Pending 是修复前证据，当前最终结果以本节为准。
- 根因：QA Chat 的后端 `id` 为 `33b8b00e-012e-448d-ba12-5563952c45ba`，Runtime `session_id` 为 `9a8f4757-69c8-4179-b8a4-f02471bba385`。旧深链把后者当作 Chat UUID 请求状态，得到 404 后将队列置为失败。
- 修复后 Session API 对任意外形的 Runtime ID 做唯一匹配；历史、状态与项目目录使用 Chat UUID；Runtime 身份继续用于模型上下文。重复 Runtime ID 不自动选择，避免串 Chat。
- URL 从 Runtime ID 规范化到 Chat UUID 前，CoPaw 会迁移该 Agent 的队列、项目目录、文件作用域和会话偏好；SDK readiness 同时确认请求 ID、会话 ID 与 Chat UUID，迁移后输入和队列不会停在禁用状态。
- Chrome CUA + 真实 Kilo `kilo-auto/free`：QA 标签页保留原失败队列 `a/b/c/d/e`，恢复后按 `a → b → c → d → e` 自动发送并逐条收到回复，队列 `5 → 3 → 0`；Default 标签页保持自己的 Agent、Chat UUID 和历史，不串页。
- 后端证据：五轮均进入 `QwenPaw_QA_Agent_0.2` 工作区的 Runtime session；状态查询持续使用 Chat UUID，Chat 最终为 `idle`，服务端每轮均记录 `console stream done` 且 `has_response=True`。
- 自动化：Runtime 别名聚焦套件 4 文件 / 179 用例通过；Console 全量 Vitest 328 文件 / 3141 用例通过；生产构建、Monaco CSS、370 个资源预压缩和首包检查通过。
