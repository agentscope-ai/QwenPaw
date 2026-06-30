# Chat 页面性能优化 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 优化 Chat 页面会话列表的渲染性能和轮询开销，减少不必要的 re-render 和网络请求。

**Architecture:** 通过 4 个独立优化点逐步改善：1) SidebarSessionList 虚拟化 2) 轮询结果去重避免无效 re-render 3) renderItem 稳定化 4) formatCreatedAt 缓存。每个优化点独立可验证。

**Tech Stack:** React, react-window (FixedSizeList), Zustand, TypeScript

---

### Task 1: SidebarSessionList 虚拟化

**问题：** `SidebarSessionList.tsx` 使用 `filteredSessions.map(renderItem)` 渲染所有会话项，当会话数量多时（100+），DOM 节点过多导致滚动卡顿。而 `ChatSessionDrawer` 已经使用了 `FixedSizeList`（react-window），SidebarSessionList 应该保持一致。

**Files:**
- Modify: `console/src/layouts/SidebarSessionList.tsx`
- Modify: `console/src/layouts/sidebarSessionList.module.less`

- [ ] **Step 1: 引入 react-window 并替换 map 渲染为 FixedSizeList**

在 `SidebarSessionList.tsx` 中：

```tsx
// 新增 import
import { FixedSizeList, type ListChildComponentProps } from "react-window";
```

将 `renderItem` 函数改为 `React.memo` 包裹的 row renderer：

```tsx
/** Data passed to each row via FixedSizeList's itemData prop */
interface SessionRowData {
  sessions: ExtendedChatSession[];
  currentSessionId: string | undefined;
  editingSessionId: string | null;
  editValue: string;
  t: ReturnType<typeof useTranslation>["t"];
  handleSessionClick: (sessionId: string) => void;
  handleEditStart: (sessionId: string, currentName: string) => void;
  handleDelete: (sessionId: string) => void;
  handlePinToggle: (sessionId: string) => void;
  handleEditChange: (value: string) => void;
  handleEditSubmit: () => void;
  handleEditCancel: () => void;
}

const SESSION_ITEM_HEIGHT = 38; // SidebarSessionItem: padding 8+8 + line-height 20 + margin-bottom 2 = 38px

const SessionRow = React.memo(function SessionRow({
  index,
  style,
  data,
}: ListChildComponentProps<SessionRowData>) {
  const session = data.sessions[index];
  if (!session) return null;

  const channelKey = session.channel?.trim() || "";
  const channelLabel = channelKey
    ? getChannelLabel(channelKey, data.t)
    : undefined;
  const isEditing = data.editingSessionId === session.id;

  return (
    <div style={style}>
      <SidebarSessionItem
        sessionId={session.id!}
        name={session.name || "New Chat"}
        channelKey={channelKey || undefined}
        channelLabel={channelLabel}
        chatStatus={session.status}
        generating={session.generating}
        pinned={session.pinned}
        active={
          session.id === data.currentSessionId ||
          (!!data.currentSessionId && session.realId === data.currentSessionId)
        }
        disabled={false}
        editing={isEditing}
        editValue={isEditing ? data.editValue : undefined}
        onClick={data.handleSessionClick}
        onEdit={data.handleEditStart}
        onDelete={data.handleDelete}
        onPin={data.handlePinToggle}
        onEditChange={data.handleEditChange}
        onEditSubmit={data.handleEditSubmit}
        onEditCancel={data.handleEditCancel}
      />
    </div>
  );
});
```

- [ ] **Step 2: 用 useMemo 构建稳定的 itemData，替换 renderItem 调用**

```tsx
const itemData = useMemo<SessionRowData>(
  () => ({
    sessions: searchQuery.trim() ? filteredSessions : sortedSessions,
    currentSessionId,
    editingSessionId,
    editValue,
    t,
    handleSessionClick,
    handleEditStart,
    handleDelete,
    handlePinToggle,
    handleEditChange,
    handleEditSubmit,
    handleEditCancel,
  }),
  [
    searchQuery, filteredSessions, sortedSessions, currentSessionId,
    editingSessionId, editValue, t, handleSessionClick, handleEditStart,
    handleDelete, handlePinToggle, handleEditChange, handleEditSubmit,
    handleEditCancel,
  ],
);
```

- [ ] **Step 3: 添加 ResizeObserver 测量列表容器高度**

```tsx
const [listHeight, setListHeight] = useState(300);
const listWrapperRef = useCallback((node: HTMLDivElement | null) => {
  if (!node) return;
  const observer = new ResizeObserver((entries) => {
    for (const entry of entries) {
      if (entry.contentRect.height > 0) {
        setListHeight(entry.contentRect.height);
      }
    }
  });
  observer.observe(node);
  return () => observer.disconnect();
}, []);
```

- [ ] **Step 4: 定义 displaySessions 并替换渲染区域**

在组件内添加 `displaySessions`（搜索时用 `filteredSessions`，否则用 `sortedSessions`）：

```tsx
const displaySessions = searchQuery.trim() ? filteredSessions : sortedSessions;
```

将原来的 `filteredSessions.map(renderItem)` 和 `groups?.map(...)` 替换为：

```tsx
{/* Session list */}
{!historyCollapsed && (
  <div className={styles.scroll} ref={listWrapperRef}>
    {loading && displaySessions.length === 0 && (
      <div className={styles.loadingState}>
        <Spin size="small" />
      </div>
    )}
    {!loading && displaySessions.length === 0 && (
      <div className={styles.emptyState}>
        {t("chat.sessionPanel.noConversations", "No conversations")}
      </div>
    )}
    {displaySessions.length > 0 && (
      <FixedSizeList
        height={listHeight}
        width="100%"
        itemCount={displaySessions.length}
        itemSize={SESSION_ITEM_HEIGHT}
        overscanCount={10}
        itemData={itemData}
      >
        {SessionRow}
      </FixedSizeList>
    )}
  </div>
)}
```

> **日期分组决策：** 虚拟化后去掉 Today/Week/Month 分组，改为扁平列表。原因：`FixedSizeList` 要求所有行等高，分组标题行高度不同需要 `VariableSizeList` + 复杂的行类型判断，收益不大（sidebar 空间有限，分组标题占用宝贵可视面积）。`ChatSessionDrawer` 也没有分组，保持一致。

- [ ] **Step 5: 删除不再需要的代码**

删除以下内容：
- `renderItem` 函数
- `groupSessions` 函数及其类型 `DateGroup`、`SessionGroup`
- `getDateGroup` 函数
- `groups` 的 `useMemo`
- `filteredSessions` 的 `useMemo`（合并到 `displaySessions`）

- [ ] **Step 6: 修改 `.scroll` CSS 以支持虚拟化**

在 `sidebarSessionList.module.less` 中，`.scroll` 类需要移除 `overflow-y: auto`（由 `FixedSizeList` 内部管理滚动），并添加 `position: relative`：

```less
/* Scrollable session area — FixedSizeList manages its own scroll */
.scroll {
  flex: 1;
  min-height: 0;
  padding: 0 4px 8px;
  position: relative;
  overflow: hidden; /* FixedSizeList handles scrolling internally */
}
```

- [ ] **Step 7: 运行 lint 检查**

Run: `cd console && npx tsc --noEmit`
Expected: 无类型错误

- [ ] **Step 8: 运行 format**

Run: `cd console && npm run format`

- [ ] **Step 9: Commit**

```bash
git add console/src/layouts/SidebarSessionList.tsx console/src/layouts/sidebarSessionList.module.less
git commit -m "perf: virtualize SidebarSessionList with react-window"
```

---

### Task 2: 轮询结果去重，避免无效 re-render

**问题：** `useSessionListData` 每 3 秒轮询 `sessionApi.getSessionList()`，即使返回的数据完全相同，`setSessions(extended)` 也会创建新的数组引用，触发 `sortedSessions` 的 `useMemo` 重新计算，进而导致整个列表 re-render。

**Files:**
- Modify: `console/src/pages/Chat/components/ChatSessionDrawer/useSessionListData.ts`

- [ ] **Step 1: 添加浅比较函数**

在 `useSessionListData.ts` 顶部添加：

```tsx
/**
 * Shallow-compare two session arrays by id + updatedAt + pinned + generating.
 * Returns true when the visible list would be identical, so we can skip
 * the state update and avoid a full re-render cascade.
 */
function sessionsEqual(
  prev: ExtendedChatSession[],
  next: ExtendedChatSession[],
): boolean {
  if (prev.length !== next.length) return false;
  for (let i = 0; i < prev.length; i++) {
    const a = prev[i];
    const b = next[i];
    if (
      a.id !== b.id ||
      a.updatedAt !== b.updatedAt ||
      a.pinned !== b.pinned ||
      a.generating !== b.generating ||
      a.name !== b.name ||
      a.status !== b.status
    ) {
      return false;
    }
  }
  return true;
}
```

- [ ] **Step 2: 在轮询回调中使用去重（ref 方案）**

`setSessions` 是外部传入的自定义回调（`useCallback((s) => syncSessionsGlobal(s))`），**不支持函数式更新**。必须用 ref 缓存上一次的值。

在 `useSessionListData` hook 内添加 ref：

```tsx
const lastSessionsRef = useRef<ExtendedChatSession[]>([]);
```

将 `useSessionListData` 中的轮询 `setInterval` 回调修改为：

```tsx
const timer = setInterval(async () => {
  if (sessionApi.isSessionSwitching) return;
  try {
    const list = await sessionApi.getSessionList();
    if (!cancelled) {
      const extended = list as ExtendedChatSession[];
      if (!sessionsEqual(lastSessionsRef.current, extended)) {
        lastSessionsRef.current = extended;
        setSessions(extended);
        syncSessionsGlobal(extended);
      }
    }
  } catch {
    // ignore polling errors
  }
}, 3000);
```

- [ ] **Step 3: 对初始 fetch 也应用去重**

```tsx
const fetchSessions = async () => {
  setLoading(true);
  try {
    const list = await sessionApi.getSessionList();
    if (!cancelled) {
      const extended = list as ExtendedChatSession[];
      if (!sessionsEqual(lastSessionsRef.current, extended)) {
        lastSessionsRef.current = extended;
        setSessions(extended);
        syncSessionsGlobal(extended);
      }
    }
  } catch (err) {
    console.error("useSessionListData: failed to fetch sessions", err);
  } finally {
    if (!cancelled) setLoading(false);
  }
};
```

- [ ] **Step 4: 运行 lint 检查**

Run: `cd console && npx tsc --noEmit`
Expected: 无类型错误

- [ ] **Step 5: 运行 format**

Run: `cd console && npm run format`

- [ ] **Step 6: Commit**

```bash
git add console/src/pages/Chat/components/ChatSessionDrawer/useSessionListData.ts
git commit -m "perf: skip re-render when polling returns unchanged session data"
```

---

### Task 3: ChatSessionDrawer 轮询去重

**问题：** `ChatSessionDrawer/index.tsx` 中也有独立的 3 秒轮询逻辑（`useEffect` 中的 `setInterval`），与 `useSessionListData` 的轮询重复，且同样没有去重。

**Files:**
- Modify: `console/src/pages/Chat/components/ChatSessionDrawer/index.tsx`

- [ ] **Step 1: 在 ChatSessionDrawer 的轮询中添加去重**

在 `ChatSessionDrawer` 的 `useEffect` 轮询中，添加 ref 缓存和浅比较：

```tsx
const lastPolledSessionsRef = useRef<IAgentScopeRuntimeWebUISession[]>([]);

// 在 useEffect 中的 fetchSessions 和 setInterval 回调中：
const list = await sessionApi.getSessionList();
if (!isCancelled) {
  // Shallow compare to avoid unnecessary state updates
  const changed =
    list.length !== lastPolledSessionsRef.current.length ||
    list.some((s, i) => {
      const prev = lastPolledSessionsRef.current[i];
      return (
        !prev ||
        s.id !== prev.id ||
        (s as ExtendedChatSession).updatedAt !==
          (prev as ExtendedChatSession).updatedAt ||
        (s as ExtendedChatSession).generating !==
          (prev as ExtendedChatSession).generating
      );
    });
  if (changed) {
    lastPolledSessionsRef.current = list;
    setSessions(list);
  }
}
```

- [ ] **Step 2: 运行 lint 检查**

Run: `cd console && npx tsc --noEmit`
Expected: 无类型错误

- [ ] **Step 3: 运行 format**

Run: `cd console && npm run format`

- [ ] **Step 4: Commit**

```bash
git add console/src/pages/Chat/components/ChatSessionDrawer/index.tsx
git commit -m "perf: deduplicate polling updates in ChatSessionDrawer"
```

---

### Task 4: formatCreatedAt 缓存

**问题：** `formatCreatedAt` 在 `ChatSessionDrawer` 的 `SessionRow` 中每次渲染都被调用，且对同一个 session 重复计算。虽然单个计算很快，但在虚拟列表滚动时会频繁触发。

**Files:**
- Modify: `console/src/pages/Chat/components/ChatSessionDrawer/index.tsx`

- [ ] **Step 1: 添加简单的 LRU 缓存**

在 `ChatSessionDrawer/index.tsx` 中，将 `formatCreatedAt` 替换为带缓存的版本：

```tsx
/** Simple cache for formatCreatedAt to avoid re-parsing the same timestamp */
const formatCache = new Map<string, string>();
const FORMAT_CACHE_MAX = 200;

const formatCreatedAtCached = (raw: string | null | undefined): string => {
  if (!raw) return "";
  const cached = formatCache.get(raw);
  if (cached !== undefined) return cached;
  const result = formatCreatedAt(raw);
  if (formatCache.size >= FORMAT_CACHE_MAX) {
    // Evict oldest entry
    const firstKey = formatCache.keys().next().value;
    if (firstKey !== undefined) formatCache.delete(firstKey);
  }
  formatCache.set(raw, result);
  return result;
};
```

然后在 `SessionRow` 中使用 `formatCreatedAtCached` 替换 `formatCreatedAt`。

- [ ] **Step 2: 运行 lint 检查**

Run: `cd console && npx tsc --noEmit`
Expected: 无类型错误

- [ ] **Step 3: 运行 format**

Run: `cd console && npm run format`

- [ ] **Step 4: Commit**

```bash
git add console/src/pages/Chat/components/ChatSessionDrawer/index.tsx
git commit -m "perf: cache formatCreatedAt results in ChatSessionDrawer"
```

---

## 优化效果预估

| 优化项 | 影响范围 | 预期效果 |
|--------|---------|---------|
| **Task 1: 虚拟化** | SidebarSessionList | 100+ 会话时 DOM 节点从 N 降到 ~20，滚动流畅 |
| **Task 2: 轮询去重** | useSessionListData | 数据不变时跳过 re-render，减少 ~90% 的无效渲染 |
| **Task 3: Drawer 轮询去重** | ChatSessionDrawer | 同上，避免 Drawer 模式下的无效渲染 |
| **Task 4: 时间格式化缓存** | SessionRow | 滚动时避免重复解析相同时间戳 |

## 不在本次范围内

- **消息列表虚拟化** — 由 `@agentscope-ai/chat` SDK 内部管理，不在本项目控制范围
- **SSE/WebSocket 替代轮询** — 需要后端配合，属于架构级变更
- **React.memo 包裹更多组件** — `ChatSessionItem` 已经 memo，其他组件当前不是瓶颈
