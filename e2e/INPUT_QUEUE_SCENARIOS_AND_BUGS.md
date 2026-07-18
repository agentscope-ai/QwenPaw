# 输入队列测试用例

> 语雀参考文档在当前环境返回 BUC SSO 登录页，无法读取正文。以下用例基于当前输入队列实现、组件配置项以及已知业务场景整理。

## 自动化覆盖

| ID     | 场景                       | 前置条件                                          | 操作                               | 预期                                                   |
| ------ | -------------------------- | ------------------------------------------------- | ---------------------------------- | ------------------------------------------------------ |
| IQ-A01 | FIFO 入队和出队            | 空队列                                            | 连续加入 first、second，再出队两次 | 出队顺序为 first、second                               |
| IQ-A02 | 直接发送条件               | loading=false、队列为空、未 drain                 | 判断是否可直接发送                 | 返回 true                                              |
| IQ-A03 | loading 时不直接发送       | loading=true                                      | 判断是否可直接发送                 | 返回 false，应进入入队路径                             |
| IQ-A04 | 队列已有任务时不直接发送   | queueLength>0                                     | 判断是否可直接发送                 | 返回 false，后续输入排到队尾                           |
| IQ-A05 | 队列暂停时不直接发送       | paused=true                                       | 判断是否可直接发送                 | 返回 false                                             |
| IQ-A06 | 非 owner tab 不直接发送    | canExecute=false                                  | 判断是否可直接发送                 | 返回 false，仅允许编辑/排序                            |
| IQ-A07 | 队列满                     | maxSize=1 且已有 1 条                             | 再入队 1 条                        | 返回 full，原队列不变                                  |
| IQ-A08 | 附件消息别名               | 输入包含 fileList                                 | 创建 queued item                   | text/query、attachments/fileList 保持可发送结构        |
| IQ-A09 | 发送失败恢复               | 任务发送失败                                      | restore failed item                | 任务回到队首，状态 failed，自动 drain 被阻塞           |
| IQ-A10 | 重试失败任务               | failed item                                       | retry                              | 状态变回 pending，可再次出队                           |
| IQ-A11 | 删除任务                   | 队列含 q1、q2                                     | 删除 q1                            | 仅剩 q2；删除不存在 id 不影响队列                      |
| IQ-A12 | 拖拽排序                   | 队列含 q1、q2、q3                                 | q3 移到 q1 前                      | 顺序变为 q3、q1、q2                                    |
| IQ-A13 | 编辑 queued query          | failed item                                       | 修改 query                         | query/text 同步更新，状态回 pending                    |
| IQ-A14 | 空队列可清理存储           | 队列为空/非空                                     | 判断 empty                         | 空队列为 true，非空为 false                            |
| IQ-A15 | send-now 命令              | 指定 itemId 和 sourceTabId                        | 创建命令                           | 命令携带 itemId、sourceTabId、createdAt                |
| IQ-A16 | 无 session 不入队          | current/pending/active 均为空                     | 解析 queue session                 | 返回 undefined，用于触发 session-not-ready 提示        |
| IQ-A17 | 初始化会话 route 未回填    | currentSessionId 为空，pendingRouteSessionId 有值 | 解析 route queue session           | 使用 pendingRouteSessionId 作为队列 key                |
| IQ-A18 | active request 兜底        | current/pending 为空，activeSessionId 有值        | 解析 visible queue session         | visible queue 使用 activeSessionId；route queue 仍为空 |
| IQ-A19 | session 优先级             | current、pending、active 同时存在                 | 解析 visible session               | current 优先，其次 pending，再次 active                |
| IQ-A20 | CoPaw temp/realId 稳定 key | tempId 和 realId 都映射到同一 backend session_id  | 分别解析 queue session             | 两者得到同一个 queue key                               |
| IQ-A21 | 切换 session 存储隔离      | session-a 和 session-b 各有队列                   | 分别读写 localStorage key          | 两个 session 的队列互不污染                            |
| IQ-A22 | 多 tab 同 session          | tab-a/tab-b 打开同一 session                      | 比较 storage key 和 owner          | storage key 相同；仅 owner tab 可发送                  |
| IQ-A23 | Agent 维度队列 key 隔离    | Agent A/B 可拥有相同 backend sessionId            | 分别解析并读写 queue session key   | key 包含 agentId；两个 Agent 的队列互不污染            |
| IQ-A24 | 队列请求上下文固定         | 入队后切换 Agent/session                          | 发送原队列项                       | 使用入队时保存的 agentId、sessionId、userId、channel   |
| IQ-A25 | accepted 项精确清理        | 队首两项 query 相同但 requestId 不同              | 接受并发送第一项                   | 仅按 requestId 删除已接受项，后一项仍保留              |
| IQ-A26 | Agent 切换恢复防重复       | 已接受项发送中切换 Agent，旧 SDK 随后恢复队列     | 切回原 Agent 并等待 settle         | 已接受项不会重复发送；未接受项继续按顺序 drain         |

## 浏览器回归用例

| ID     | 场景                       | 前置条件                                        | 操作                       | 预期                                                |
| ------ | -------------------------- | ----------------------------------------------- | -------------------------- | --------------------------------------------------- |
| IQ-M01 | 初始化对话首条消息         | `/chat` 无 sessionId，队列开启                  | 输入首条消息并发送         | 直接创建会话并发送，不出现队列项                    |
| IQ-M02 | 初始化会话生成中再次输入   | 首条消息已发送，外部受控 sessionId 尚未稳定     | 再次尝试入队               | 不发起入队，出现“当前会话生成中”提示，输入不被清空  |
| IQ-M03 | 初始化会话 pending id 可用 | createSession 已返回 id，但外部受控 sessionId 还未回填 | 再次输入                   | 队列绑定 pending id，不落到空 key                   |
| IQ-M04 | sessionId alias 变化后队列不丢 | 新会话已有队列，随后受控 sessionId 从临时 id 更新为同一会话的真实 id | 查看队列                   | 队列仍展示在同一会话，不丢失、不串到其他会话        |
| IQ-M04b | sessionId alias 变化不打断 drain | 新会话首条消息 SSE 中已有队列，随后受控 sessionId 从临时 id 更新为同一会话的真实 id | 等待首条 SSE 完成          | SSE 不被误判为切会话而中断；finish 后自动 drain 下一条 |
| IQ-M05 | 切换 session 隔离          | session A 有队列，session B 无队列              | 从 A 切到 B，再切回 A      | B 不显示 A 队列；切回 A 队列仍在                    |
| IQ-M06 | 切换时队列任务不写入新会话 | A 正在 drain 队列，用户切到 B                   | 等待队列发送               | A 的任务不渲染到 B；若检测到切换，任务恢复到 A 队列 |
| IQ-M07 | 多 tab 同 session 同步     | 两个标签页打开同一 session                      | tab-a 入队，tab-b 观察     | tab-b 同步显示队列                                  |
| IQ-M08 | 多 tab owner 限制          | tab-a 是 owner，tab-b 同 session                | tab-b 点击发送/立即发送    | tab-b 只能编辑/排序；真实发送由 owner tab 执行      |
| IQ-M09 | owner tab 关闭             | tab-a owner，tab-b 同 session                   | 关闭 tab-a，等待 owner TTL | tab-b 可接管发送                                    |
| IQ-M10 | 暂停/恢复跨 tab 同步       | 同 session 两个 tab                             | tab-a 暂停/恢复            | tab-b 状态同步；暂停时不自动 drain                  |
| IQ-M11 | 队列满提示                 | maxSize 设小                                    | 连续入队到超过上限         | 超限输入不入队，提示 queue full，原队列不变         |
| IQ-M12 | 附件队列                   | 上传成功附件但文本为空                          | 入队并发送                 | 队列显示附件消息，发送体保留 attachments/fileList   |
| IQ-M13 | 失败任务重试               | 模拟请求失败                                    | 点击重试                   | 任务回到 pending 并重新发送                         |
| IQ-M14 | 立即发送                   | owner tab 队列中有多条任务，当前没有 active streaming | 对第二条点击立即发送       | 该任务优先发送，其他任务顺序保持                    |
| IQ-M15 | 清空队列                   | 队列非空                                        | 点击清空                   | 队列清空，localStorage 对应 key 被移除              |
| IQ-M16 | streaming 中立即发送       | owner tab 正在生成回复，队列中有至少 1 条任务，宿主 `isSessionRunning` 会返回 true | 对队列项点击立即发送       | `send-now` 优先级高于 running guard；当前回复被取消/标记 interrupted，目标队列项被移除并立即提交 |
| IQ-M17 | 新增项自动滚动             | 队列项数量足够多，列表区域已出现纵向滚动条      | 再新增 1 条队列项          | 队列列表自动滚动到底部，最新新增项可见；编辑、删除、重试、拖拽排序不应触发强制滚动 |
| IQ-M18 | Agent 切换队列隔离         | Agent B 长任务执行中且队列有 2 项，Agent A 无队列 | B -> A -> B                 | A 不展示 B 的队列；切回 B 后原 session 和 2 项队列完整恢复 |
| IQ-M19 | Agent 切换并刷新后自动 drain | Agent B 长任务执行中且队列有 2 项               | B -> A -> B，刷新 B，等待长任务结束 | 刷新后队列仍在；长任务结束后两项按 FIFO 自动发送且队列清空，不重复 |
| IQ-M20 | Agent 往返切换消息完整性   | Agent A/B 都有历史消息                           | 连续执行 3 轮 A -> B -> A  | 每次切回后用户消息和回复即时完整，延迟请求不能覆盖当前 Agent 消息列表 |
| IQ-M21 | Agent 切换后新建对话复位   | 已切换 Agent，当前路由为 `/chat/<id>`            | 点击 Create New Chat       | 路由立即变为 `/chat`，标题为 New Chat，欢迎页出现，旧会话不被重新选中 |

## 已知修复回归

| ID       | 问题                         | 回归检查                                         | 预期                                                   |
| -------- | ---------------------------- | ------------------------------------------------ | ------------------------------------------------------ |
| IQ-BUG01 | `send-now` 被 `isSessionRunning` 阻断 | streaming 期间点击队列项的立即发送              | SDK command handler 不先调用/等待宿主 running 检查，而是按用户显式打断处理：清 command、移除目标项、`handleCancel`、`submitNow` |
| IQ-BUG02 | Agent 切换后第一个 Agent 的用户消息偶发不展示 | 连续执行 A -> B -> A，并在切换后即时和稳定态检查消息 | 用户消息与最终列表一致，旧 Agent/旧请求不能覆盖当前消息列表 |
| IQ-BUG03 | 第二个 Agent 长任务完成后队列不自动发送，刷新也不恢复 | B 长任务中入队 2 项，切换 Agent、切回并刷新，等待任务完成 | 队列归属 B 的原 session；任务结束后按顺序自动发送并清空，刷新不造成丢失或重复 |
| IQ-BUG04 | Agent 切换后 Create New Chat 未清理旧路由和标题 | 从 `/chat/<id>` 点击 Create New Chat             | 路由、标题和欢迎页同时复位，initializer 不重新选中旧会话 |
| IQ-BUG05 | 失败任务点击重试后队列项恢复并卡住 | 首次 queued 请求失败后解除故障并点击重试 | 重试请求只发送一次；队列项移除并收到回复，不得恢复为 `Next` 卡住 |


## 2026-07-17 输入队列全量回归结果

前置条件：隔离环境已配置 `qwen3.7-max`，模型连接测试成功。浏览器用例均在可见 Chrome/Chromium 中执行，不使用全站 E2E 结果替代。

### 结果摘要

- 自动化场景 `IQ-A01 ~ IQ-A26`：通过。SDK 输入队列核心脚本 32/32 通过；CoPaw 队列、session、Agent 作用域相关 Vitest 85/85 通过。
- 浏览器场景 `IQ-M01 ~ IQ-M21`（含 `IQ-M04b`）：20 通过，2 失败。
- 已知 Bug：`IQ-BUG02 ~ IQ-BUG04` 通过；`IQ-BUG01`、`IQ-BUG05` 失败。
- 本轮只回归输入队列及其 Agent 切换关联问题，没有执行或引用全站 E2E 作为通过依据。

### 自动化结果

| 范围 | 结果 | 证据 |
| ---- | ---- | ---- |
| IQ-A01 ~ IQ-A22 | 通过 | SDK `inputQueue.test.ts` 实际执行 32 条断言脚本，32/32 通过。 |
| IQ-A23 | 通过 | `chatSessionIds.test.ts`、`sessionApiAgentScope.test.ts` 覆盖 Agent 维度 queue key。 |
| IQ-A24 | 通过 | `chatRequestContext.test.ts` 验证发送使用入队时保存的 Agent/session/user/channel。 |
| IQ-A25 | 通过 | `inputQueueStorage.test.ts` 验证按 requestId 精确清理，同文本后一项保留。 |
| IQ-A26 | 通过 | `agentSwitchScope.test.ts`、`inputQueueStorage.test.ts` 与 Agent/session 相关用例共同覆盖切换恢复防重复。 |
| CoPaw 队列相关回归集 | 通过 | 10 个 Vitest 文件、85 条用例全部通过。 |

### 可见浏览器结果

| ID | 结果 | 实际证据 |
| -- | ---- | -------- |
| IQ-M01 | 通过 | 从 `/chat` 发送首条消息时直接创建会话；首条发送后没有生成队列项。 |
| IQ-M02 | 通过 | URL 仍为 `/chat` 且 session 未就绪时再次入队，没有创建空 key 队列；输入内容保留在输入框。 |
| IQ-M03 | 通过 | 在 pending id 窗口成功入队；入队时 URL 仍是 `/chat`。 |
| IQ-M04 | 通过 | URL 更新为 `/chat/29175479-e720-4bf0-ae11-6f030b0da16d` 后，pending 队列仍完整展示。 |
| IQ-M04b | 通过 | pending/真实 id 切换没有打断首条 SSE；首条结束后 queued item 自动发送并收到 `PENDING_ALIAS_DONE`。 |
| IQ-M05 | 通过 | session A 的暂停队列切到新 session B 后不显示；返回 A 后原队列恢复。 |
| IQ-M06 | 通过 | A 正在 drain 时切到新 session B；B 只显示欢迎页且没有 A 的用户消息，返回 A 可见 queued user 与 `M06_DONE`。 |
| IQ-M07 | 通过 | 同 session 第二个标签页同步显示 3 个队列项。 |
| IQ-M08 | 通过 | 非 owner 标签页显示“Sent by original tab. Edit and reorder only”，无发送/清空控制；编辑和拖拽排序同步到 owner。 |
| IQ-M09 | 通过 | 关闭已确认的 owner 标签页后，peer 在 TTL 内接管；队列和 paused 状态保留。 |
| IQ-M10 | 通过 | owner 暂停时不自动 drain；恢复后两个标签页同步清空，并按顺序收到三条回复。 |
| IQ-M11 | 通过 | 队列最多保留 50 项；第 51 项未入队，输入保留并出现 queue full 提示。 |
| IQ-M12 | 通过 | 纯附件消息成功入队，队列展示附件名 `截屏2026-07-17 15.07.59.png`。 |
| IQ-M13 | **失败** | 浏览器拦截一次 queued 请求后能出现 failed/retry；解除拦截并点击重试后，用户消息已追加，但队列项恢复成 `Next`，60 秒内无精确助手回复且队列未清空。 |
| IQ-M14 | 通过 | 空闲且暂停的 3 项队列中立即发送第 2 项；目标项优先提交，另外两项顺序和内容保留。 |
| IQ-M15 | 通过 | 清空后面板消失；刷新后队列没有恢复，确认持久化状态已清理。 |
| IQ-M16 | **失败** | streaming 中点击立即发送后，目标项从队列移除并追加为用户消息，但旧长回复没有立即停止；约 83 秒后旧回复自然结束才收到 `M16_DONE`，也没有 interrupted 标记。 |
| IQ-M17 | 通过 | 连续加入到第 50 项后，列表自动滚到底部，`Q047 ~ Q050` 可见；第 51 项仍留在输入框。 |
| IQ-M18 | 通过 | Agent B 队列为 2 项；切到 Agent A 后未显示 B 队列；切回 B 恢复原 session 与 2 项队列。 |
| IQ-M19 | 通过 | 切换 Agent 并刷新后 2 项仍在；长任务结束后依次收到 `QUEUE_1_DONE`、`QUEUE_2_DONE`，队列自动清空且无重复。 |
| IQ-M20 | 通过 | 连续 3 轮 A -> B -> A；两个 Agent 的路由、标题、用户消息、回复在即时态和稳定态均完整。 |
| IQ-M21 | 通过 | `/chat/<id>` 点击 Create New Chat 后即时变为 `/chat`；标题 `New Chat`、欢迎页正确，旧标题未残留。 |

### 已知 Bug 结论

| ID | 结果 | 结论 |
| -- | ---- | ---- |
| IQ-BUG01 | **失败** | `send-now` 仍未在 streaming 中及时打断当前请求；需要继续修复。 |
| IQ-BUG02 | 通过 | Agent 往返切换未再出现首个 Agent 用户消息暂时缺失。 |
| IQ-BUG03 | 通过 | 第二个 Agent 长任务完成后队列可自动发送；Agent 切换和刷新不再阻断。 |
| IQ-BUG04 | 通过 | Agent 切换后 Create New Chat 的路由、标题和欢迎页均正确复位。 |
| IQ-BUG05 | **失败** | 失败项重试后被重新恢复到队列并卡住；用户消息已渲染，但没有完成回复和队列清理。 |

回归规则：任何失败项不得因构建成功、单测成功或全站 E2E 结果而标记为通过；修复 `IQ-BUG01`、`IQ-BUG05` 后必须分别重新执行 `IQ-M16` 的真实 streaming 打断流程和 `IQ-M13` 的失败重试流程。
