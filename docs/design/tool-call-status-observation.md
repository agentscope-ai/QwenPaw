# Tool Call 状态观察优化方案

## 1. 结论

当前请求频繁的根因不是输出 SSE，而是状态查询按 tool call 独立轮询：

- 前台调用：每个 `useToolCallControl` 每 2 秒请求一次 `getInfo`。
- 后台调用：每个后台任务每 3 秒请求一次 `getInfo`。
- 前后台交接期间，两套观察器可能短暂同时存在。

推荐分两阶段实施：

1. 先将状态查询改为 session 级批量轮询，复用现有 list API，把请求量从
   `O(tool calls)` 降到 `O(sessions)`。
2. 再增加 session 级生命周期 SSE，最终取消周期性状态轮询；每个任务的
   输出 SSE 继续保持按需连接。

## 2. 当前调用模型

设前台任务数为 N，后台任务数为 M：

```text
current_requests_per_second = N / 2 + M / 3
```

例如 10 个并发前台任务、9 个后台任务：

```text
10 / 2 + 9 / 3 = 8 requests/second
```

120 秒理论上最多产生约 960 个状态请求。浏览器截图中两分钟出现数百个
`GET /tool-calls/{session}/{call_id}`，与该模型一致。

以下定时器不产生网络请求，不是本次优化对象：

- 前台倒计时的 1 秒本地 tick。
- 后台面板运行时长的 1 秒本地 tick。

## 3. 方案对比

| 方案 | 请求复杂度 | 后端改动 | 断线恢复 | 实施成本 | 建议 |
|---|---:|---:|---:|---:|---|
| 延长每任务轮询间隔 | O(N) | 无 | 一般 | 低 | 不推荐，只缓解常数 |
| session 级批量轮询 | O(S) | 无 | 好 | 中 | 第一阶段 |
| session 级生命周期 SSE | 事件驱动 | 有 | 需设计回放 | 中高 | 最终方案 |
| 每任务常驻 SSE | O(N) 连接 | 小 | 一般 | 中 | 不推荐 |
| WebSocket | 事件驱动 | 大 | 需设计协议 | 高 | 单向通知没有必要 |

S 表示当前打开的 session 数，通常为 1。

## 4. 第一阶段：session 级批量轮询

### 4.1 目标结构

新增前端 `toolCallStatusHub`，按 session 维护唯一观察器：

```text
sessionId -> {
  subscribers: Map<toolCallId, Subscriber>,
  timer,
  inFlight,
  lastSnapshot
}
```

所有前台工具卡和后台任务只订阅状态，不再各自创建 interval。

Hub 每轮只调用一次：

```http
GET /tool-calls/{session_id}
```

将结果构造成 `Map<toolCallId, ToolCallInfo>`，再分发给对应订阅者。

### 4.2 订阅者类型

```ts
type ToolCallStatusSubscriber = {
  mode: "foreground" | "background";
  seen: boolean;
  onInfo: (info: ToolCallInfo) => void;
  onMissing?: () => void;
};
```

- `foreground`：刷新 deadline、elapsed，识别 auto-offload。
- `background`：识别完成或取消，然后调用 `/output` 收敛最终结果。
- `seen`：防止组件先挂载、后端 entry 尚未创建时把首次缺失误判为完成。

### 4.3 自适应周期

| 状态 | 建议周期 |
|---|---:|
| 存在前台运行任务 | 2 秒 |
| 只有后台任务 | 5 秒 |
| 无订阅者 | 停止 |

一个 session 只允许一个 in-flight 请求。请求完成后再安排下一次 timeout，
禁止使用会重叠的 `setInterval(async ...)`。

### 4.4 完成判定

当前 list API 只返回活跃 entry，不包含 completed cache。因此：

1. 已经 `seen` 的后台任务从 snapshot 消失。
2. Hub 通知后台 watcher。
3. 后台 watcher调用 `/output` 获取最终内容和 `final_state`。
4. `/output` 成功后标记 done/cancelled，并取消订阅。
5. `/output` 临时失败时不立即结束，保留订阅并在下一轮重试。

该流程必须在 coordinator 的 completed cache TTL 内完成。第一阶段轮询周期为
5 秒，正常前台页面下有足够余量；页面长时间冻结属于第二阶段断线恢复要解决的
问题。

### 4.5 前后台交接

tool call 转后台时只改变订阅模式：

```text
foreground subscriber
        -> background subscriber
```

Hub 和 timer 不重建，不出现 2 秒轮询与 3 秒轮询短暂重叠。

输出观察仍保持现有行为：

- 展开任务：连接该任务 `/stream`。
- 收起任务：abort 该任务 `/stream`。
- 输出流不承担后台状态常驻观察。

### 4.6 第一阶段请求收益

以 10 个前台任务为例：

| 场景 | 当前 | 批量轮询 |
|---|---:|---:|
| 10 个前台任务，1 分钟 | 约 300 次 | 约 30 次 |
| 9 个后台任务，1 分钟 | 约 180 次 | 约 12 次 |
| 前台转后台 | 两套轮询可能重叠 | 同一 Hub 切换模式 |

## 5. 第二阶段：session 生命周期 SSE

新增接口：

```http
GET /tool-calls/{session_id}/events
```

每个 session 只建立一个生命周期连接。事件仅描述状态，不传输大体积工具输出：

```text
snapshot
started
deadline_changed
offloaded
completed
cancelled
```

`ToolCoordinator` 已具备 offloaded 和 completion callback，可作为事件源基础；
started 与 deadline_changed 需要补充发布点。

### 5.1 断线恢复

连接建立时先发送 snapshot，再发送增量事件。协议应包含单调递增的 sequence：

```json
{
  "seq": 42,
  "type": "completed",
  "tool_call_id": "call_xxx",
  "status": "completed",
  "final_state": "success"
}
```

服务端保留有界事件 ring buffer。重连携带最后 sequence：

```http
Last-Event-ID: 42
```

- sequence 仍在 buffer：回放缺失事件。
- sequence 已过期：发送新的 snapshot，并对前端已知后台 ID 返回终态摘要。

### 5.2 背压

- 每个 session subscriber 使用有界队列。
- deadline/elapsed 更新允许按 tool call 合并，只保留最新值。
- completed/cancelled 等终态事件不可丢弃。
- 慢消费者超限时断开，由客户端重连并恢复。

### 5.3 降级

生命周期 SSE 失败时启用第一阶段的 session 批量轮询，而不是退回每任务轮询。

## 6. 推荐实施顺序

### Phase 1：批量轮询

- 新增 `toolCallStatusHub`。
- 为 Hub 编写请求聚合与生命周期单元测试。
- `useToolCallControl` 改为订阅 Hub。
- 后台 watcher 改为订阅 Hub。
- 删除两处 per-tool interval。
- 保留按需输出 SSE。

### Phase 2：生命周期 SSE

- 增加后端 session event broker。
- 增加 `/events` 路由与 snapshot/replay。
- Hub 优先消费 SSE，失败时降级为批量轮询。
- 增加断线、回放、慢消费者和 session 隔离测试。

## 7. 第一阶段测试门禁

- 10 个同 session 前台任务在一个周期内只发送 1 个 list 请求。
- 10 个同 session 后台任务在一个周期内只发送 1 个 list 请求。
- 两个 session 分别只有一个观察器，互不串数据。
- 前台转后台不新增第二个 timer，也不产生重叠请求。
- 慢请求跨多个周期仍只有一个 in-flight。
- 首次 snapshot 缺失且 `seen=false` 时不判定完成。
- 已 seen 后消失才触发 `/output`。
- `/output` 临时失败时继续观察，不误标完成。
- 最后一个订阅者离开后停止 timer。
- session 切换、取消、组件卸载均释放订阅。
- 展开和收起输出不影响 status Hub。

## 8. 验收指标

- 10 个并发工具时，tool-call 状态请求从约 5 RPS 降至不超过 0.5 RPS。
- 仅后台任务时，状态请求不超过 0.2 RPS/session。
- 单 session 任意时刻最多一个状态请求 in-flight。
- 状态收敛延迟：前台不超过 2 秒，后台不超过 5 秒。
- 不新增后台常驻 per-tool SSE。
- 完成、取消、自动转后台、session 切换行为保持不变。
