# 历史消息列表会话切换性能优化设计

## 背景

聊天页面在 sidebarMode simple（精简模式）和 full（非精简模式）下切换对话时存在两个性能问题：

1. **切换对话时卡顿** — 尤其是长对话（100+ 条消息）时感知明显
2. **快速切换对话时卡在 loading 状态** — 无法点击其他对话，必须等待超时释放

## 根因分析

### 卡顿原因

- `preloadSession` 阻塞式网络请求：每次切换等待 `api.getChat()` 返回全部历史消息
- `convertMessages` 同步计算：O(n) 遍历所有消息构建卡片对象
- 3 秒轮询 `getSessionList` 在切换期间仍然运行，与切换请求竞争带宽，且触发不必要的 re-render
- 轮询每次返回新数组引用 → sortedSessions 重算 → itemData 重建 → FixedSizeList 全量 re-render

### Loading 卡死原因

- `isSessionSwitching` 全局锁：切换中所有后续点击被 `return` 丢弃
- 锁释放延迟：需等 2-rAF + 2000ms 降级超时
- 无请求取消机制：旧 fetch 不能 abort，必须等待完成

## 设计方案

### 方案 A：可打断式会话切换（P0）

将"阻塞式锁"改为"取消式锁" — 新点击不被丢弃，而是取消旧切换、发起新切换。

#### 核心改动

**1. sessionApi 新增 AbortController 管理**

```typescript
class SessionApi {
  private switchAbortController: AbortController | null = null;

  startNewSwitch(): AbortController {
    this.switchAbortController?.abort();
    const controller = new AbortController();
    this.switchAbortController = controller;
    this.isSessionSwitching = true;
    return controller;
  }

  finishSessionSwitch(): void {
    this.isSessionSwitching = false;
    this.switchAbortController = null;
  }
}
```

**2. preloadSession 支持 signal**

```typescript
async preloadSession(sessionId: string, signal?: AbortSignal) {
  const session = await this.getSession(sessionId, signal);
  // ... cache logic unchanged
}

private async fetchAndBuildSession(..., signal?: AbortSignal) {
  const chatHistory = await api.getChat(backendId, { signal });
  if (signal?.aborted) throw new DOMException('Aborted', 'AbortError');
  // ...
}
```

**3. api.getChat 支持 signal**

```typescript
getChat: (chatId: string, options?: { signal?: AbortSignal }) =>
  request<ChatHistory>(`/chats/${encodeURIComponent(chatId)}`, { signal: options?.signal }),
```

**4. handleSessionClick 重构（非 embedded 模式）**

```typescript
const handleSessionClick = (sessionId: string) => {
  if (sessionId === currentSessionId) return;

  const controller = sessionApi.startNewSwitch();
  setSwitchingSessionId(sessionId);

  sessionApi
    .preloadSession(sessionId, controller.signal)
    .then(({ realId }) => {
      if (controller.signal.aborted) return;
      const effectiveId = sessionApi.getEffectiveSessionId(sessionId, realId);
      navigate(buildSessionPath("chat", effectiveId), { replace: true });
      sessionApi.trackNavigatedSession(effectiveId, setLastChatId, selectedAgent);
      setCurrentSessionId(sessionId);
    })
    .catch((err) => {
      if (err.name === 'AbortError') return;
      setCurrentSessionId(sessionId);
    })
    .finally(() => {
      if (!controller.signal.aborted) {
        sessionApi.finishSessionSwitch();
        setSwitchingSessionId(null);
      }
    });
};
```

**5. ChatSessionInitializer handleSelectSession 同样改为可打断式**

embedded 模式通过 DOM 事件通信，handleSelectSession 中同样使用 startNewSwitch + signal。

**6. 移除 2000ms 降级超时和 2-rAF 等待**

安全前提（已验证）：
- `isSessionSwitching` 守卫 onSessionSelected
- `lastNavigatedChatId` 守卫 ChatSessionInitializer
- `lastSelectedIds` 防重复 onSessionSelected
- `sessionResultCache` 命中后 getSession 不触发 onSessionSelected

#### 涉及文件

- `console/src/pages/Chat/sessionApi/index.ts`
- `console/src/api/modules/chat.ts`
- `console/src/pages/Chat/components/ChatSessionDrawer/index.tsx`
- `console/src/pages/Chat/components/ChatSessionInitializer/index.tsx`

---

### 方案 B：轮询策略 + 渲染减负（P0）

#### 核心改动

**1. 切换期间暂停轮询**

在 3 秒 setInterval 回调中增加 `if (sessionApi.isSessionSwitching) return;`。

**2. sessions 浅比较避免无效 re-render**

在 `sessionApi.applyChatsToSessionList` 末尾，对比新旧列表（id + name + status + updatedAt + pinned + generating），相同则返回旧引用。

**3. sortedSessions 排序优化**

ISO 8601 字符串直接使用 `localeCompare` 替代 `new Date().getTime()` 比较。

**4. FixedSizeList itemData 稳定化**

将 `sortedSessions` 通过 ref 传递给 SessionRow，使 itemData 不因列表内容变化而重建：

```typescript
const sortedSessionsRef = useRef(sortedSessions);
sortedSessionsRef.current = sortedSessions;

const itemData = useMemo(() => ({
  sortedSessionsRef,
  currentSessionId,
  switchingSessionId,
  editingSessionId,
  editValue,
  // ... handlers (stable via useCallback)
}), [currentSessionId, switchingSessionId, editingSessionId, editValue]);
```

SessionRow 通过 `data.sortedSessionsRef.current[index]` 取会话数据。

#### 涉及文件

- `console/src/pages/Chat/sessionApi/index.ts`
- `console/src/pages/Chat/components/ChatSessionDrawer/index.tsx`
- `console/src/pages/Chat/components/ChatSessionDrawer/useSessionListData.ts`

---

### 方案 C：消息加载优化（P1）

#### 核心改动

**1. 已转换会话 LRU 缓存**

- 最多缓存 10 个会话，TTL 5 分钟
- 非 generating 状态的会话在 `fetchAndBuildSession` 完成后写入缓存
- 切回已看过的对话时直接返回缓存（0 网络请求）
- 失效时机：用户发送消息、会话删除、TTL 过期

```typescript
private convertedSessionCache = new Map<string, {
  session: ExtendedSession;
  timestamp: number;
}>();
```

**2. convertMessages 优化**

- 使用 `messages.slice(startIdx, i).map(toOutputMessage)` 替代逐个 push 到临时数组
- ISO 字符串排序替代 Date 对象创建

**3. 骨架屏过渡（可选）**

切换时立即设置 `setChatLoading('switching')`，展示消息骨架占位符。SDK 渲染完成后通过 RuntimeLoadingBridge 自动清除。

#### 涉及文件

- `console/src/pages/Chat/sessionApi/index.ts`
- `console/src/pages/Chat/index.tsx`（骨架屏，可选）

---

## 实施顺序

1. **方案 A** — 解决 loading 卡死，最高优先级
2. **方案 B** — 减少切换卡顿和 CPU 竞争
3. **方案 C** — 长对话性能优化

## 风险与注意事项

- 方案 A：AbortController abort 时需确保不残留中间态（URL / currentSessionId 不一致）
- 方案 B：sortedSessionsRef 的 ref 传递模式需确保 React.memo 仍然有效
- 方案 C：缓存 generating 状态的会话会导致消息不一致，仅缓存 idle 会话
