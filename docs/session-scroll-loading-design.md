# 聊天历史滚动加载：设计文档（可读版 v3.2）

> **一句话版本**：聊天历史被"上下文压缩"藏起来之后，用户仍然可以在**原会话里向上滚动**把它们翻回来看——就像从仓库里把旧货取回柜台。整个过程不需要用户进任何"归档"页面。

- 版本：v3.2（对照当前代码逐项核实修订：扩页预算常量、大内容防护实现状态、有界窗口只按条数不按字节；v3.1 → v3.2 的具体改动见附录 B）
- 日期：2026-09-03
- 前置评估：`docs/session-scroll-loading-assessment.md`
- **Phase 1 已实施并做了真实环境验证，见 §9**；历史版本见附录 B

---

## 怎么读这篇文档

| 你的身份 | 建议路径 |
|---|---|
| 只想快速了解方案 | 读 §1 → §2 → §3，约 5 分钟 |
| 要动手实现（或者接着往下做剩下的活） | §4 后端 + §5 前端 + §6 边界 + §7 验收，边写边查附录 A 速查表；**§9 列了已验证的部分和还没做完的部分，别重复造轮子** |
| 想复核某个技术断言 | 直接看附录 A 的代码事实表（含文件路径与行号） |
| 好奇设计为什么反复改 | 附录 B 有一段压缩版历程 |

**阅读约定**：正文尽量用大白话讲"为什么"；凡是写着 `code` 或"速查"的地方，都是给实现者看的细节，普通读者可以直接跳过。

---

## 1. 问题：聊天记录为什么"消失了"

### 1.1 用户看到的现象

- 聊了很久（几百条消息），突然触发了一次**上下文压缩**；
- 压缩后刷新页面、或切去别的会话再回来；
- 结果：**早期聊天不见了**，只剩压缩后的最近一段。

### 1.2 为什么会这样（三个概念，用比喻讲）

系统里有两处存聊天数据的地方，外加一个"搬移动作"：

| 概念 | 正式名 | 比喻 | 它存什么 |
|---|---|---|---|
| 会话 JSON | `AgentState.context` | **柜台桌面** | 当前正在用的消息。前端只读它 |
| 历史数据库 | `history.db`（`conversation_history` 表） | **仓库** | 每一句话的流水账，**全部**记录都在，带唯一货架号 `seq` |
| 上下文压缩 | scroll compaction / `/compact` | **收桌子** | 把早期消息从桌面撤下、只留一段摘要——但**仓库里的记录一条没删** |

问题就出在这：**前端只认桌面**。压缩只是把旧消息从桌面移走了，仓库里明明还有，前端却从不去取。

> 关键事实：Scroll 是默认的上下文管理模式，`history.db` 是全量记录（写入即落库，压缩不删行）。所以"仓库"天然完整——缺的只是一条从仓库取货的路。

### 1.3 本期要做什么、不做什么

**做**：
- 默认 Scroll 模式下，无论自动压缩还是手动 `/compact`，用户刷新/切换会话后，都能在原会话向上滚动，看到保留期内的**完整用户消息与助手回复**；
- 用户不需要知道消息来自桌面还是仓库——前端无缝衔接；
- 超过保留期的**工具执行详情**可以显示"已过期"，但聊天正文不能跟着消失。

**不做（诚实声明）**：
- 旧版本写的 `dialog/*.jsonl` 归档不带会话 ID，无法可靠合并回原会话（Phase 3 只做工作区级查看/导出）；
- 会话本身已被删除/未出现在列表里的，不属本期范围；
- 已经被旧版本删除的历史数据无法自动找回。

### 1.4 验收测试（一句话记住目标）

> 造 200 条消息 → 触发 `/compact` → 刷新页面 → 切换会话再回来 → **向上滚动后仍能看到压缩前的第 1 条消息**。

再加一条 OOM 验收：历史加载再多，浏览器内存和 DOM 节点**必须有上限**，"能翻到底但把 Chrome 翻崩"不算通过。

---

## 2. 总体思路：桌面不够就从仓库取

```
┌─ 首屏：先看桌面 ──────────────────────────────┐
│  GET /api/chats/{id}/messages?limit=50        │
│  从会话 JSON 取最近一页 → 转成聊天卡片 → 返回    │
│  顺手记下"这一页最早一条"的仓库货架号 seq        │
└──────────────────────────────────────────────┘
                  │ 用户向上滚动
                  ▼
┌─ 翻页：去仓库往前取 ───────────────────────────┐
│  GET /api/chats/{id}/messages?before_seq=123  │
│  查 history.db 中 seq < 123 的更早记录         │
│  → 还原成聊天卡片 → 插到消息列表顶部             │
└──────────────────────────────────────────────┘
```

三条铁律，全程不破：

1. **一个统一端点**。不区分"聊天分页接口"和"归档接口"，前端只认一套返回结构；
2. **游标只用 `seq`**。`seq` 是仓库货架号，只增不减，压缩不动它，清理过期工具结果也只形成空隙不断号——所以**游标永不因压缩失效**（曾经想用消息 id 当游标，被证明每次请求都会重新生成随机 id，必坏，已废弃）；
3. **不改数据库表结构、不改任何写入路径**。所有改动只发生在"读"的一侧。

### 三个最容易踩的坑（先记住，后面细讲）

| 坑 | 一句话 | 对策 |
|---|---|---|
| 分页把"一次问答"切成两半 | 助手一条回复可能带思考+工具调用+工具结果，切开就碎了 | 所有分页都**按"用户问题"对齐**，宁可多返回几条，不切半个回合 |
| 翻页翻出内存问题 | SDK 会把加载过的消息全渲染，翻得越深浏览器越卡 | 前端**有界窗口 + 虚拟列表**（§5.2），后端限制单页体积（§4.4） |
| 出问题时把现有消息也搞丢 | 异常降级若只返回最近 50 条，比现状还糟 | 降级返回"受保护的安全窗口"，明确提示并提供重试/下载（§4.5） |

---

## 3. 关键概念小词典

先读懂这些词，后面全是它们。

| 词 | 大白话 | 为什么重要 |
|---|---|---|
| **seq** | 仓库里每条记录的**货架号**，自增、永不复用 | 拿它当前后翻页的"书签"，压缩不影响它 |
| **回合** | 一次完整的问答 = 用户提问 → 助手思考/调工具/最终回复 | 分页的**最小不可切单位** |
| **卡片合并** | 前端把"用户问题"和"助手一整套回复"各自渲染成一张大卡片 | 分页切错位置会把卡片从中间劈开 |
| **dedup_key** | 仓库行上盖的"来源戳"：存的就是原始消息的 Msg.id | 用来把桌面消息和仓库记录对上号（锚定） |
| **锚定** | 首屏返回时，拿"窗口最早一条用户消息"去仓库查它的货架号 | 拿到货架号，下一页才知道从哪儿继续取 |
| **占位符/合成消息** | 压缩时系统塞进桌面的"伪消息"，从不进仓库 | 不能拿它们当锚点，否则必失败 |
| **ResponseCard** | 前端聊天里一张完整的助手回复卡片 | 它跨了多条仓库记录，是分页最难伺候的对象 |

---

## 4. 后端改动

### 4.1 新接口长什么样

新增一个端点（旧接口 `GET /api/chats/{id}` 原样保留，老客户端不受影响）：

```
GET /api/chats/{chat_id}/messages?limit=50            ← 首屏（最近一页）
GET /api/chats/{chat_id}/messages?before_seq=123&limit=50   ← 向上翻页（更早一页）
```

返回结构（统一，前端只认这个）：

```jsonc
{
  "messages": [ /* 聊天卡片，按时间从旧到新排好 */ ],
  "next_cursor": 123,        // 下一页从哪个货架号往前取；null = 没有下一页
  "has_more": true,          // 还有没有更早的
  "history_status": "available", // 历史处于什么状态（§4.5）
  "status": "idle",          // 会话是否正在生成（原样透传，见附录 A-2）
  "truncated": false,        // 是否因超长回合被截断（§4.4）
  "fallback_limited": false  // 是否因异常只给了安全窗口（§4.5）
}
```

> ⚠️ `limit` 是"目标大小"，不是"严格条数"。它数的是**原始消息/记录条数**，不是最终卡片数——因为要保证回合完整，返回的卡片数可能多也可能少。**禁止**先把整个会话转成卡片再切片（既切坏回合，又白费转换开销）。

### 4.2 首屏：从桌面拿最近一页（4 步）

1. **读桌面**：从会话 JSON 取出当前消息列表（复用现有读取逻辑）；
2. **按回合取窗**：从尾部往回数 `limit` 条左右，然后**继续向前走到最近一条真实的用户提问**，窗口从那里开始——绝不从半句回复/半张工具卡开始。`limit` 不够 50 没关系，回合完整优先；
3. **转卡片 + 锚定**：把窗口转成聊天卡片；拿窗口最早那条用户提问的 Msg.id 去仓库查货架号 → 得到 `next_cursor`；
4. **回答三个问题**：`has_more`（仓库里还有没有更早的）、`history_status`（历史状态）、`status`（会话在不在生成）。

**为什么这么麻烦？** 因为如果简单截"最后 50 条"，很可能从助手回复中间或一张工具卡中间开始——用户看不到自己的问题，只看到半截回答；而且若拿系统占位符当锚点，它从不进仓库，锚定必失败。

### 4.3 翻页：去仓库往前取（8 步）

1. **取一页**：`WHERE session_id=? AND seq<? ORDER BY seq DESC LIMIT limit+1`（多取 1 条用来判断"还有没有更早"）；
2. **补齐回合**：如果这一页最老的一头切在了某个回合中间，就继续往前查，直到把那回合开头的用户提问也收进来——**绝不切开一次完整问答**；
3. **还原成卡片**：仓库行 → 聊天卡片（核心转换层，见 §4.6）；
4. **排好序再返回**：仓库查出来是从新到旧，返回前翻成**从旧到新**（跟 prepend 语义一致）；
5. **记录书签**：`next_cursor` = 本页最老那条的货架号；下一页从它往前查，天然不重叠、无缺口；
6. **重算 has_more**：因为补齐回合可能吃掉了预取的那条，得再查一次仓库确认；
7. **孤儿工具结果不丢**：某条工具结果在本页找不到它对应的工具调用（调用在更早的一页）→ 降级成独立卡片展示，信息保留；
8. **给超长回合上保险**：连续补齐最多补 `DEFAULT_MAX_EXPANSION_ROWS`（固定 600 行，不是 `3 × limit`——早期设计想按 `limit` 动态算，实现时简化成一个不随请求变化的定值；`limit` 上限本身是 200，`max(limit, 600)` 在当前参数范围内恒等于 600）。真遇到病态超长回合，就停手返回、标记 `truncated=true`，前端在两段之间显示"该历史回合过长，已截断显示"——这是全设计**唯一**允许回合被切开的情况，后续页从断点继续，内容不丢、也不会无限查询。

> **技术细节**：仓库是 SQLite，同步查询不能阻塞异步服务——分页/补齐查询用 `asyncio.to_thread` 丢到工作线程执行；只读连接（`mode=ro` + WAL）在同一线程里建、查、关，不跨线程传递。

### 4.4 最难的点：为什么"回合不能切开"

前端会把一次问答渲染成一张大卡片，而它在仓库里其实占**好几行**：

```
一次完整问答在仓库里长这样：
seq 100  用户提问            ← 回合开始
seq 101  助手思考
seq 102  助手调用工具A
seq 103  工具A 返回结果
seq 104  助手最终回复        ← 回合结束
```

如果分页切在 seq 102 和 103 之间，前端就会拿到"半张卡片"：有工具调用没结果、有思考没回答。所以前后端定下两条规矩：

- **后端**：任何一页都必须从"用户提问"那一条开始（§4.3 步骤 2）；
- **前端**：翻页请求只带着 `next_cursor`（货架号）去要"更早的一页"，不参与判断边界——边界问题后端全包了。

这条是全设计唯一的实现难点，测试里专门给它排了最高优先级（§7）。

### 4.5 历史到底处于什么状态（`history_status`）

一页翻到底时，要分清五种截然不同的情况，不能让"数据库坏了"和"真翻到头了"显示成同一个结果：

| 值 | 人话 | 前端显示 |
|---|---|---|
| `available` | 正常，还有更早的 | 继续翻页 |
| `complete` | 真翻到最早一条了 | "已到最早消息" |
| `expired` | 早期**正文**被旧版本策略/人工清理删过（新版本不会再发生） | "部分早期聊天已被旧版保留策略清理" |
| `unavailable` | 这个会话本来就没有历史库（非 Scroll 模式） | 不显示翻页入口（不是故障） |
| `degraded` | 本该有历史库，但库坏了/查不动/锚定失败 | **绝不装成"翻到头"**：给重试入口 + 记日志 |

判断"是否被旧版清理"用的是压缩索引里的归档货架号范围（具体规则见附录 A-3），没有可靠证据时**默认按正常到底处理，不瞎猜**。

**注意区分**：工具详情过期 ≠ 页面到头。如果只是某个工具的执行结果超过保留期被清了，那只是那一张工具卡显示"工具详情已过期"，聊天正文和翻页照常。

### 4.6 核心转换层：仓库行 → 聊天卡片（`history_rows_to_messages`）

这是全项目**唯一需要新写的主要函数**，单独立项。它负责：

- 仓库里的"用户提问行"还原成用户消息、"助手回合行"还原成助手消息；
- 把工具结果行**合并回**对应的工具调用卡片（按 `tool_call_id` 对上号）；
- 过滤系统占位符/合成消息；
- 页边界对齐（见 §4.4）；
- 孤儿工具结果独立成卡；工具结果缺失时按是否过期显示"已过期"或"暂不可用"（两者都不删正文）；
- 输出按时间从旧到新排列；
- **给每条还原的消息一个稳定且唯一的 ID**：`metadata.original_id` 记原始消息 ID，`Message.id` 用 `"{原始ID}:{序号}"`（如 `abc123:0 文本 / abc123:1 思考 / abc123:2 工具调用 / abc123:3 工具结果`）。理由：一条助手回复会拆成多条卡片消息，ID 全一样会让前端列表 key 打架。

### 4.7 前端还需要防重吗

**不需要。** 曾经的方案让前端按 `original_id` 去重——但同一条原始消息拆出的思考/工具调用/工具结果共享同一个 `original_id`，一去重就把它们误删了。正确的保证是**数学上的**：首屏拿 `seq >= 书签` 的部分，翻页拿 `seq < 书签` 的部分，两边天然没有交集。加一条"相邻两页连续且不重叠"的断言单测兜底即可。

### 4.8 安全防护：上限（防浏览器 OOM，Phase 1 必做）

| 防线 | 数值 | 人话 | 状态 |
|---|---|---|---|
| 超长回合扩页预算 | `DEFAULT_MAX_EXPANSION_ROWS` = 600（§4.3 步骤 8） | 补齐回合最多补这么多行，超了就 `truncated=true` 停手 | **已实现** |
| 单页响应体积 / 单条超大内容预览 | 设计里的 `MAX_PAGE_CONTENT_BYTES`（4 MiB）+ 超大块 64 KiB 预览、`large_content=true` | 一页/一条内容太大时只给预览，完整原文走只读下载 | **未实现**（后端没有任何体积上限或 `large_content` 标记，见 §9.4；不是"后端做了前端没接"，是两边都没做） |
| 翻页总额（前端） | `LOAD_MORE_MAX_MESSAGES` = 300 条（消息**数量**上限，SDK patch 里实现，见 §5.2） | 消息数超过 300 时从较新一端裁掉 | **已实现，但只按条数封顶，没有独立的字节数（如"约 8 MiB"）上限**——之前几处提到的"约 8 MiB"是设计阶段的预估值，代码里没有对应的字节统计逻辑 |

只改"读"，不动表结构和写入格式。

### 4.9 保留策略：30 天只清"工具结果"，正文永久保留

**这是 v2.6 的一个重大纠偏**——此前设计"30 天后清理全部历史"，等于聊天正文也只有 30 天，与用户预期不符。现在：

- `history_retention_days`（默认 30）语义改为：**工具结果保留天数**；
- 自动清理**只删除 30 天前的工具结果行**；用户消息、助手回复（含思考与工具调用）**永久保留**；
- **两处调用点都要改，漏一处就白修**：`ScrollContextManager.purge_old()`（运行中定期清理）和 `sync.py` 的 `_purge_old_history()`（**启动时**的兜底清理，容易漏掉）都要传 `kinds=("tool_result",)`，只改前者的话，每次重启/新建 agent 时仍会把全部历史清空；
- 设 `0` = 工具结果也永久保留（什么都不清）；
- 配置说明和 release note 同步改措辞，别让用户误以为聊天正文只有 30 天；
- 已被旧版本删掉的正文**无法自动恢复**——升级只是阻止以后继续删。

> 为什么敢让正文永久保留？翻页时正文行就是聊天本身，体积小；真正占地方的是工具结果（可能含大段日志/截图数据），那才是需要定期清理的。

### 4.10 数据库索引需要加吗

**暂不需要。** `seq` 是 SQLite 自增主键（本身就是 rowid），现有单列索引 `ch_session(session_id)` 已能让查询高效执行。是否补复合索引由 5k/20k 行压测决定，不作为本期必做项。

---

## 5. 前端改动

### 5.1 怎么接上翻页（**与最初设想不同，实为改 SDK 源码**）

最初以为 SDK 本来就内置了"加载更早消息"的回调钩子，只是 console 没传——**这个判断是错的**，实施时才核实清楚：console 实际用的是 `@jsfund/agent-chat`（`package.json` 依赖名，本仓库内部维护的 fork，不是公开的 `@agentscope-ai/chat`）里的 `AgentScopeRuntimeWebUI` 组件树；它内部真正挂载消息列表的 `MessageList`/`ChatAnywhereSessionsContext` 只有"模拟分页"——把已经加载进内存的数组多显示一截，从未真正按需请求后端。`onLoadMore` 这个网络驱动的回调**根本不存在**，得自己加。

因为 `@jsfund/agent-chat` 是内部 fork，改源码是被允许的，做法是：

1. **`patch-package`**：直接改 `node_modules/@jsfund/agent-chat` 源码，生成 diff 存在 `console/patches/@jsfund+agent-chat+<version>.patch`，`package.json` 加 `postinstall: patch-package` 自动应用。改动需要走内网 npm 合并回 SDK 本体，本仓库这份 patch 只是过渡；
2. 在 `ChatAnywhereSessionsContext.js` 新增 `useChatAnywhereLoadMoreHistory` hook：真正调用 `options.session.onLoadMore(sessionId)`，返回的更早消息 `prepend` 进消息数组，并在 hook 内部做**竞态守卫**（用 ref 而非闭包变量比对当前会话 id，否则请求期间切换会话时守卫形同虚设）；
3. `MessageList/index.js` 里，`hasRealLoadMore` 为真时优先用这个真实 hook，否则回退到原有的模拟分页——不影响 SDK 其他不传 `onLoadMore` 的调用方；
4. console 侧：首屏改走新端点，返回的 `next_cursor` 存好；**用返回的 `status` 驱动"正在生成"和 pending 消息补回**；`sessionApi.loadOlderMessages` 解析 `sessionId`（可能是显示 id 也可能是后端 UUID）、调新端点、转卡片、合并回 `convertedSessionCache`（SDK 的 prepend 不会自动同步这个缓存）。

### 5.2 内存三道防线（防 OOM，Phase 1 必做，**虚拟化技术选型有变**）

前面说过 SDK 会把所有加载过的消息全量渲染。所以前端必须主动设限：

1. **有界窗口**：`useChatAnywhereLoadMoreHistory` 里维护，聊天里最多保留 300 条消息（`LOAD_MORE_MAX_MESSAGES`），超限时从数组"较新"一端裁掉——这条和最初设想一致，已实现。
2. **虚拟渲染**：**没有用 `react-window`**。原计划复用项目已装的 `react-window`，但它自己接管一个独立视口做虚拟滚动，而 `Bubble.List` 的滚动容器是 `flex-direction: column-reverse` 的原生 `overflow:auto` div，`scrollToBottom`/"是否到底"等逻辑直接读写这个 div 的原生 `scrollTop`——两者的滚动模型不兼容，硬塞会跟 SDK 自己的滚动追踪打架。改用 **`@tanstack/react-virtual`**（新依赖，需要走内网 npm）：它的 `getScrollElement` 允许指向任意已存在的滚动元素，不抢滚动权，正好适配这个约束。新写了 `WindowedBubbleList.js`，作为 `children` 传给 `Bubble.List`（利用它内部本来就有的 `children ? children : items.map(...)` 分支），只在 `hasRealLoadMore` 为真时启用，模拟分页路径保持原样不变。
   - **一个不写代码看不出来的坑**：`column-reverse` 容器在 Chrome 里 `scrollTop` 是**负数**（从 0 一路负到最老消息，`Bubble.List` 自己的 `checkShowScrollToBottom` 判断用的就是 `scrollTop <= -10`）。`@tanstack/react-virtual` 默认假设 0→正的坐标系，直接接会把所有负偏移钳成 0——表现为无论往上滚多深，虚拟化都以为自己停在最新消息那，只渲染最前面几条，深处一片空白。修法是自定义 `observeElementOffset`/`scrollToFn` 做正负号转换。
   - 效果（真实浏览器验证，见 §9）：单次 prepend 的主线程长任务从约 2.9 秒降到 300ms 以内，且不随已加载消息总数增长。
3. **大内容预览**：设计目标是标了 `large_content=true` 的只显示预览 + "下载完整内容"，不在聊天页里渲染完整 Markdown/代码高亮。**（整个机制——后端标记和前端 UI——都还没做，见 §9.4 未完成项）**

> 结论：后端一页一页读 + 前端限制消息数/字节数/DOM 数——三道闸一起，深翻时浏览器内存进入平台期，而不是靠减小页大小拖延崩溃。

### 5.3 两个必须处理的竞态

| 场景 | 问题 | 对策 |
|---|---|---|
| 翻页途中切换会话 | 旧请求返回后把旧会话消息插进新会话 | 回调里快照"当前会话 + 书签"，返回时对不上就**整包丢弃**，并且返回 `{messages: [], noMore: false}`——`noMore` 必须 false，否则会误把新会话标成"没有更多历史" |
| 切走再切回 | 缓存只存了首屏，翻过页丢了 | 翻页结果**先合并进该会话的缓存**（SDK 的 prepend 不会自动同步缓存），LRU 缓存整个有界窗口 |

### 5.4 各种状态提示长什么样

| 后端状态 | 前端文案/行为 |
|---|---|
| `available` | 正常翻页 |
| `complete` | "已到最早消息" |
| `expired` | "部分早期聊天已被旧版保留策略清理" |
| `degraded` | 重试入口（不显示"已到最早"） |
| `unavailable` | 不显示翻页入口 |
| `truncated` | "该历史回合过长，已截断显示" |
| `fallback_limited` | "为避免浏览器内存不足，仅显示最近消息"+ 重试/下载（**不能**显示"已到最早"） |
| 工具卡 `tool_result_expired` | 只显示工具名、调用时间、"工具详情已过期"，不提供重试；不影响继续看更早聊天 |

PC 与移动端共用同一套窗口策略。

---

## 6. 各种情况下会发生什么（速查表）

| 场景 | 结果 |
|---|---|
| 压缩后翻页 | 仓库行不受压缩影响，正常翻到底 |
| 翻页途中切会话 | 旧响应被守卫丢弃，新会话不受污染 |
| 非 Scroll 会话 | 返回最近安全窗口；超限则 `fallback_limited=true, history_status=unavailable` + 原始会话下载 |
| Scroll 下锚定失败/库坏了 | 返回最近安全窗口；`fallback_limited=true, history_status=degraded` + 重试/下载，**不装成正常到头** |
| 会话仍在生成 | 响应 `status="running"`，前端照常补回 pending 消息 |
| 超 30 天的工具结果 | 正文照常显示，该工具卡显示"工具详情已过期"；页面状态不变 |
| 旧版本已删正文 | `history_status=expired`，提示旧版清理 |
| 真翻到最早 | `history_status=complete`，"已到最早消息" |
| 超长回合超预算 | `truncated=true` + 截断标记，后续页从断点继续 |
| 旧客户端调旧接口 | 旧端点不动，行为不变 |

---

## 7. 怎么验收

**主验收（集成级，最高优先级）**：200 条消息 → `/compact` → 重进会话 → 连续上翻到第 1 条可见。

**OOM 验收**：造 ≥ 10,000 条历史（混入长文本和超大工具结果）连续翻页——任一时刻内存消息 ≤ 300 条（当前只有条数上限，无独立字节数上限，见 §4.8）、DOM 只渲染视口项；翻过第 20 页后 Chrome heap 不再随页数线性增长；"返回最新"、动态高度、prepend 后滚动锚点都正常。

**单测重点**（建议按序补）：
1. 转换层（先行）：kind 还原、工具合并、边界对齐、孤儿工具结果、占位符过滤、输出升序、ID 唯一；
2. 分页：游标、扩页、空表、清理后、5k/20k 行压测（p95 < 50ms）；
3. 锚定：命中/未命中；失败 → 安全窗口 + `fallback_limited`，原始会话仍可下载；
4. 首屏对齐：不从半截回复开始；占位符不做锚点；
5. `history_status` 五值 + `expired` 四条判定规则；
6. 分类型保留：30 天自动清理只删工具结果，正文数量不变；`=0` 全不清；
7. 工具过期展示：过期 → 占位；未过期 → "暂不可用"+warning；两者都不动游标和正文顺序；
8. 页边界断言：相邻两页连续且不重叠；
9. 扩页预算：超长回合触发 `truncated`，连续翻不无限循环；
10. status 透传、缓存合并（切走切回）、竞态守卫（含 `noMore:false`）。

**受影响既有测试**：`tests/unit/app/chats/test_session.py`、`tests/integration/test_chats_global.py`、`test_chats_agent_scoped.py`。

**新增测试文件**：`tests/unit/app/chats/test_history_pagination.py`（转换层单测）、`tests/unit/app/chats/test_messages_endpoint.py`（端点级，走真实 `TestClient` + 真实 `HistoryStore`，workspace/session/task_tracker 走 mock；含验收测试"200 条消息压缩后连续翻页到第 1 条"）。

---

## 8. 分期计划

| 阶段 | 内容 | 工作量 |
|---|---|---|
| **Phase 1（本期）** | 统一 messages 端点 + 转换层 + 分类型保留 + 大内容保护 + 前端有界窗口/虚拟列表 + 竞态守卫 + 完整验收（含 OOM） | **7–9 人日**（新增部分是 SDK 列表适配与 OOM 压测） |
| Phase 2 | 历史浏览体验优化、导出/诊断抽屉、保留期设置 UI | 2–3 人日 |
| Phase 3 | 旧 dialog 工作区级查看/搜索、可确认归属的迁移、新 dialog 写入补 session_id | 2 人日 |

> Phase 1 不碰数据库表结构和写入路径。OOM 防护**必须在 Phase 1 做掉**——否则只是把"看不到"换成"看得到但翻崩浏览器"，问题原地打转。

---

## 9. 实施记录（2026-09-02～03，代码/真实环境核实）

Phase 1 已经写完并做了三层验证，跟纯看代码/单测不一样，记一下都验了什么、怎么验的，以及还差什么。

### 9.1 后端：单测 + 真实服务器双重验证

193 个后端单测全过（`test_history_store.py`、`test_scroll_manager.py`、`test_sync.py`、`test_utils.py`、`test_messages_endpoint.py`）。但只做到这一步不够——`test_messages_endpoint.py` 的 `workspace` 是 `MagicMock`，`workspace.config.light_context_config` 这种**路径写错了 mock 也不会报错**（`MagicMock` 对任意属性访问来者不拒）。于是又额外起了一个真实的本地 `qwenpaw app` 服务器（真实 config 加载、真实 `AgentProfileConfig`、真实 SQLite 文件），跑通两件事：

1. **200 条种子数据（无需真实模型）**：直接写 `history.db` + 精简会话 JSON 模拟"压缩后"状态，40 次真实 HTTP 分页请求连续翻到第 1 条，零重复零缺口，`history_status` 正确落到 `complete`。这一步就撞见了事实表 #20 的 bug（`light_context_config` 路径），是 mock 测试完全没暴露、真实服务器一启动就 500 的问题。
2. **真实模型触发的真实压缩**（复用本机已配置的火山引擎 coding plan key，未写入任何新密钥、未改用户真实数据目录）：临时把模型的 `max_input_length` 调到 40000，20 轮真实对话后 `ScrollContextManager` 真的触发了一次压缩（`prompt_tokens` 从 29653 掉到 19671），再翻页验证——17 条留在实时会话 JSON，翻一页拿回 70 条，零重复，正确落到 `complete`，这次读的是真实 `EvictionIndex`（事实表 #13 的 `agent_raw["scroll"]["index"]`），不是种子脚本从没写过的字段。

### 9.2 前端：SDK 补丁两轮踩坑，都是真实浏览器验证出来的

§5.1/5.2 已经记录了两个"实施后才发现设计假设是错的"的地方（SDK 无真实 `onLoadMore`、`react-window` 与 `column-reverse` 冲突）。除此之外，虚拟化补丁本身在真实浏览器里连续踩了两个只有跑起来才看得出来的坑：

1. **`_toConsumableArray is not defined`**：手写补丁代码里用了一个这个文件从来没定义过的 babel 辅助函数（其他函数如 `_objectSpread`/`_slicedToArray` 是原文件自带的，`_toConsumableArray` 不是），Vite 预打包时不报错，只有真的触发 `loadMore` 那条代码路径才在浏览器里抛出。改成 `.concat()`（两个操作数本来就是真数组，不需要展开语法）就不需要这个辅助函数了。
2. **深滚动整屏空白**：接入 `@tanstack/react-virtual` 第一版直接用默认的 `observeElementOffset`，负数 `scrollTop` 被钳成 0，虚拟化一直以为自己停在最新消息——这就是事实表 #19 的坑，改自定义 `observeElementOffset`/`scrollToFn` 做符号转换后解决。
3. **Vite 依赖预打包缓存**：改完 SDK 源码后不清 `node_modules/.vite` 缓存，浏览器加载的还是旧 bundle——中间调试时被这个坑晃点过一次，往`node_modules`里手改文件后必须清缓存重启才能验证到最新代码。

修复后真实测得：单次 prepend 的主线程长任务从 2870ms 降到 300ms 以内（`PerformanceObserver('longtask')` 实测），DOM 节点数不再随已加载消息总数线性增长。

### 9.3 新增依赖与产物

- `console/patches/@jsfund+agent-chat+1.1.73-beta.1786415183789.patch` + `package.json` 新增 `patch-package` devDependency + `postinstall` 脚本；
- `console/package.json` 新增 `@tanstack/react-virtual` 依赖；
- 以上两项都需要在能访问内网 npm 源的环境里跑一次 `npm install` 来同步 `package-lock.json`（本次实施环境访问不到内网源，只能单独拉包验证，没法生成锁文件）。

### 9.4 还没做完的（诚实列一下，别让人以为 Phase 1 100% 完工）

- **前端测试基建仍是空的**：vitest 没装，`sessionApi.loadOlderMessages`/竞态守卫等逻辑目前只有真实浏览器手工验证，没有自动化前端单测兜底；
- **`history_status` 驱动的尾部文案没接**（§5.4 那张表还只是设计，没写进组件）：`available`/`complete`/`expired`/`degraded`/`unavailable`/`truncated`/`fallback_limited` 对应的提示文案和"返回最新消息"按钮都还没做；
- **富内容（图片/思维链/工具调用/文件）虚拟化只做过一轮轻量验证**：336 条混合类型种子数据滚动测试里最长主线程任务到过 457ms（比纯文本的 116~300ms 高，符合预期——工具卡/思维链渲染更重），还没有专门针对这类重内容做过大规模 OOM 压测；
- **`large_content=true` 超大内容预览/下载完全没做**（§4.8）：核对代码时发现之前"后端已支持，前端 UI 还没接"的说法是错的——`MAX_PAGE_CONTENT_BYTES`、单条内容 64 KiB 预览、`large_content` 标记，在 `chats/api.py`/`chats/utils.py`/`scroll/history.py` 里都没有任何实现，是后端和前端都还没做的一整块；
- **有界窗口只按消息条数封顶（300 条），没有独立的字节数上限**：`useChatAnywhereLoadMoreHistory` 里的 `LOAD_MORE_MAX_MESSAGES` 只数消息个数，代码里没有统计过已加载内容的字节数——之前文档里出现的"约 8 MiB"是设计阶段的预估，不是已实现的另一道独立防线；

---

## 附录 A：实现者速查

### A-1 代码事实表（全部经代码核实，设计的地基）

| # | 事实 | 出处 | 设计推论 |
|---|---|---|---|
| 1 | `GET /api/chats/{id}` 读会话 JSON 全量返回 | `chats/api.py:333-413` | 首屏数据源；压缩后只剩最近消息 |
| 2 | 后端转换每次生成随机 Message.id（uuid4），原始 Msg.id 仅存 `metadata.original_id` | `chats/utils.py:557-565`、`schemas.py:202` | ~~before_id 游标~~ 废案；游标必须用 db 的 `seq` |
| 3 | **实施后核实为误判**：console 实际用的 `@jsfund/agent-chat`（内部 fork）里，`AgentScopeRuntimeWebUI` 组件树的 `onLoadMore` 从未真正接到网络请求，只有"模拟分页"（多显示一截已加载数组）；此前引用的 `hooks/types.d.ts:308`/`Chat/index.js` 是另一个同包内、未被 console 使用的通用 `ChatAnywhere` 组件树的代码 | `node_modules/@jsfund/agent-chat/lib/AgentScopeRuntimeWebUI/core/Context/ChatAnywhereSessionsContext.js`、`.../Chat/MessageList/index.js` | 真实 `onLoadMore` 要靠 `patch-package` 改 SDK 源码新增，见 §5.1 |
| 4 | 因为 #3 是误判，"互斥"这条不适用于实际用到的组件树；`useSimulatedMessagePagination` 与新增的真实分页 hook 通过 `hasRealLoadMore` 显式二选一，互不干扰 | `.../Chat/MessageList/index.js` | 不需要处理"互斥"问题，但两套逻辑要显式切换避免同时生效 |
| 5 | 新增的 `useChatAnywhereLoadMoreHistory` hook 若用闭包变量比对当前会话 id 做竞态守卫，请求期间会话切换后闭包值不变，守卫形同虚设——已知的一个实现坑，用 ref 存最新会话 id 才能生效 | `.../Context/ChatAnywhereSessionsContext.js` | 竞态守卫必须用 ref，不能用闭包捕获的普通变量 |
| 6 | scroll 默认启用；history.db 带 session_id + 自增 seq 主键 + ch_session 索引，全量 write-through（压缩不删行） | `config/config.py:1118`、`scroll/history.py:150-176` | 压缩前历史与当前历史同库同表，单数据源即可恢复 |
| 7 | db 行 `dedup_key` = Msg.id（model turn）/ tool_call_id（工具调用） | `scroll/manager.py:1610-1660` | `metadata.original_id` 可锚定 db seq |
| 8 | db 行按 kind 区分：context_msg / model_turn / tool_result 等，一次助手回复 = 多行 | `scroll/history.py:154`、`scroll/manager.py` | 需要专门 `history_rows_to_messages` 转换层（核心难点） |
| 9 | `purge(before, kinds=...)` 支持按 kind 行级删除，表/文件从不删除 | `scroll/history.py:613-631,661-707` | 自动清理只删 tool_result 即可，无需改表结构 |
| 10 | 现有转换已过滤占位符与合成 user 消息 | `chats/utils.py:547-550` | 转换层复用这些过滤 |
| 11 | 旧 dialog jsonl per-workspace、按日期分文件、不带 session_id | `agent_context.py:46-130` | 旧 dialog 无法归属会话，只能工作区级查看（Phase 3） |
| 12 | 前端 `isGenerating()` = `status === "running"`，getChat 返回后立即用于 pending 补丁 | `pages/Chat/sessionApi/index.ts:363-365,1372-1391` | 新端点必须带 status |
| 13 | 压缩证据在 EvictionIndex `_index._tiers`，Block 带归档 (seq_lo, seq_hi) | `eviction_index.py:150,185`、`manager.py:140` | expired 判定依据 |
| 14 | 一条 Msg 转换拆多条 Message，共享同一 original_id | `chats/utils.py:557-613` | 不能按 original_id 去重扁平消息 |
| 15 | 会话运行状态唯一来源是 `workspace.task_tracker.get_status(chat_id)`，get_chat 直接透传 | `chats/api.py:388` | 新端点复用同一调用，不从 agent state 推断 |
| 16 | `Bubble.List` 的 `BubbleListContent` 对 `items` 无条件 `.map()` 全量挂载，且支持 `children ? children : items.map(...)` 这个逃生舱——可以从外部注入自定义渲染而不用碰 `Bubble.List` 自身的滚动/"加载更多"逻辑 | `Bubble/BubbleList.js:49`（`BubbleListContent` 函数） | Phase 1 必须有界窗口 + 虚拟渲染；虚拟化实现走 `children` 注入，不改 `Bubble.List` 本体 |
| 17 | **实施后改判**：`react-window` 自己接管一个独立视口做虚拟滚动，与 `Bubble.List` 的原生 `overflow:auto` + `flex-direction:column-reverse` 滚动容器模型冲突；改用 `@tanstack/react-virtual`（`getScrollElement` 可指向任意已有滚动元素，不抢滚动权），新增依赖需要走内网 npm | `Bubble/style/list.js`（`column-reverse` 样式来源） | 不复用 `react-window`；改用 `@tanstack/react-virtual` + 手写 `WindowedBubbleList.js` |
| 18 | model_turn.blocks 保留工具调用及 tool_call_id，工具输出单独存 tool_result 行 | `scroll/serialize.py:250-345` | 删过期工具结果后仍能保留正文与调用位置 |
| 19 | `column-reverse` 容器下 Chrome 的 `scrollTop` 是负数（从 0 一路负到最老消息），`checkShowScrollToBottom` 判断用 `scrollTop <= -10` | `Bubble/BubbleList.js`（`checkIsAtBottom`/`checkShowScrollToBottom`） | 接第三方虚拟化库时必须做坐标系正负号转换，否则深滚会渲染空白 |
| 20 | 后端 `AgentProfileConfig` 的 `light_context_config` 挂在 `.running` 下（`config.running.light_context_config`），不是直接挂在 `config` 上——只有真实 `AgentProfileConfig` 才会暴露这个层级，`MagicMock` 单测对错误路径没有防御力 | `config/config.py`（`AgentsRunningConfig.light_context_config`）；`app/chats/api.py` 的 `_light_context_config` 辅助函数 | 单测必须配合真实服务器验证，纯 mock 测试会漏掉这类路径错误 |
| 21 | 分类型保留策略有两处调用点都要传 `kinds=("tool_result",)`，不只 `ScrollContextManager.purge_old`：启动时的兜底清理 `sync.py` 的 `_purge_old_history` 也要改，否则新建 agent 或重启后仍会清空全部历史 | `agents/context/scroll/manager.py`（`purge_old`）、`agents/context/scroll/sync.py`（`_purge_old_history`） | §4.9 的保留策略修复要覆盖两处调用点 |

### A-2 响应模型与关键来源

```python
class ChatMessagesPage(BaseModel):  # chats/models.py 新增
    messages: list[Message]
    next_cursor: int | None          # 下一页 from-seq；null = 无更多
    has_more: bool
    history_status: Literal["available","complete","expired","unavailable","degraded"]
    status: Literal["idle","running"] = "idle"   # 来源：workspace.task_tracker.get_status(chat_id)
    truncated: bool = False
    fallback_limited: bool = False
```

- `expired` 判定（仅旧版/人工清理）：①索引空 → complete；②db 最小剩余 seq ≤ 索引最小 seq_lo → complete；③db 最小 seq > 索引最小 seq_lo → expired；④索引不可读 → complete（不猜）。
- `tool_result_expired`（单卡片）：model_turn 有工具调用但同回合找不到 tool_result，且调用早于 `history_retention_days` 截止 → 过期占位；未过期 → "暂不可用"+warning。
- 常量（已实现）：`DEFAULT_MAX_EXPANSION_ROWS = 600`（固定值，不随 `limit` 变化）；有界窗口 `LOAD_MORE_MAX_MESSAGES = 300` 条（仅条数，无字节上限）；`limit` 用 `Query(ge=1, le=200)`。
- 常量（设计中，未实现，见 §9.4）：`MAX_PAGE_CONTENT_BYTES = 4 MiB`；超大块预览 64 KiB。
- 保留策略：`purge(before=cutoff, kinds=("tool_result",))`；`history_retention_days=0` 不清；人工路径可显式传 kinds，但须 `estimate_purge()` 预览 + 二次确认。

### A-3 术语 → 实现对照

| 文档用语 | 代码/数据对应 |
|---|---|
| 桌面 | `AgentState.context`（会话 JSON） |
| 仓库 | `conversation_history` 表（history.db） |
| 货架号 seq | 自增主键，rowid 别名（history.py:151） |
| 占位符/合成消息 | `_is_scroll_memory_placeholder` / `_is_synthetic_user_message`（utils.py:61/92，从不落盘 db：manager.py:1585） |
| 真实用户行判定 | 复用 `memoryspace.py:1108 _real_user_conditions` 同款条件 |
| 旧 dialog | `dialog/*.jsonl`（agent_context.py:46-130） |

---

## 附录 B：为什么改了这么多版（评审历程压缩版）

v3 之前，文档先后经 **Claude 一轮 + ChatGPT 四轮** 外部评审，22 条意见全部闭合。主线的几次大转向：

1. **v1 → v2（推翻重写）**：原方案只做"当前上下文分页"，评审指出用户主诉是"压缩后历史消失"，分页解决不了——目标纠偏，`history.db` 接回滚动流提为 Phase 1；
2. **游标换血**：曾用消息 id 当游标（before_id），评审核实每次请求都重新生成随机 id，必坏 → 改用仓库 `seq`；
3. **两处行为纠错**：SDK 两层分页其实互斥（不能两层同开）；前端不能按 `original_id` 去重（一条消息拆多条会误删）；
4. **降级策略两次翻转**：v2.1"降级返回全量"（防丢消息）→ v2.5 因 OOM 约束改为"返回受保护的安全窗口 + `fallback_limited` 明示 + 重试/下载"；
5. **保留策略纠偏（v2.6）**：从"30 天后全清"改为"只清工具结果，正文永久保留"；
6. **OOM 从"以后再说"升级为 Phase 1 阻断项（v2.5）**：SDK 无界渲染被核实后，三道内存防线进入本期。

> 工程教训写在附录里：这份文档的反复，大多不是方案写错，而是**评审揪出了代码事实与假设的偏差**（随机 id、占位符不落盘、SDK 互斥、无界渲染……）。每一条都先核实代码、再改文档——这也是为什么事实表（附录 A-1）必须跟着文档一起维护。

7. **v3 → v3.1（实施完成，真实环境核实）**：写代码、跑真实服务器、跑真实浏览器，暴露出评审阶段没查到的偏差——不是又一轮"看代码假设哪里错"，是"代码写完、真的跑起来才知道设计里哪几句站不住"：
   - **SDK 里根本没有真实 `onLoadMore`**：v2.6/v3 都以为 SDK 已经内置了这个钩子，只是 console 没接上；实施时核实发现 console 实际用的组件树里这个钩子从来没连过网络，得靠 `patch-package` 改 SDK 源码新增（§5.1）；
   - **`react-window` 装不进去**：v3 §5.2 写的是复用已装的 `react-window`，实施时发现它跟 `Bubble.List` 的 `column-reverse` 原生滚动容器模型冲突，换成了 `@tanstack/react-virtual`（新依赖，§9.3）；
   - **`column-reverse` 下 `scrollTop` 为负**这个坑评审阶段完全没人提过，真机滚动测试才炸出来（事实表 #19）；
   - **`light_context_config` 配置路径写错**（事实表 #20）：全部单测用 `MagicMock` 走过，起一个真实服务器才 500 报错；
   - **分类型保留策略有两处调用点**（事实表 #21），文档此前只提到 `ScrollContextManager.purge_old`，漏了启动时的 `sync.py` 兜底清理。
   
   详见 §9。这条印证了 v2 那条教训的延伸版：**代码核实能挡住"假设与已有代码不符"，但挡不住"假设与运行时行为不符"——后者只能靠真的跑起来验证**。

8. **v3.1 → v3.2（逐项核对代码后的修订）**：v3.1 写完之后，把文档里每条数值/状态断言重新对照当前代码核实了一遍，改了三处站不住的地方：
   - **扩页预算不是 `3 × limit`**：§4.3/§4.9/附录 A-2 之前写的公式是设计阶段的想法，实际代码里 `DEFAULT_MAX_EXPANSION_ROWS` 是固定的 600，不随 `limit` 变化（`scroll/history.py:29`）；
   - **"大内容预览后端已支持，前端没接"是错的**：核实 `chats/api.py`/`chats/utils.py`/`scroll/history.py` 全文没有 `MAX_PAGE_CONTENT_BYTES`、`large_content` 或任何字节级截断逻辑——这一整块（不只是前端 UI）都还没做，§4.8/§9.4 已改口径；
   - **"约 8 MiB" 不是已实现的独立防线**：有界窗口（`LOAD_MORE_MAX_MESSAGES=300`）只统计消息条数，代码里没有字节数估算——之前几处提到的"约 8 MiB"只是设计阶段的预估值，混进了"已实现"的表述里，容易让人以为字节上限也做了。
