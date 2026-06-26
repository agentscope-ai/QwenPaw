# Session Switch Performance Optimization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix session switching performance — eliminate loading deadlock on rapid switching, reduce stuttering, and cache previously-viewed sessions.

**Architecture:** Three-phase optimization: (A) Replace blocking switch lock with AbortController-based cancellable switching, (B) Stabilize polling and virtual list rendering to reduce CPU contention, (C) Add LRU session cache to avoid redundant network requests.

**Tech Stack:** React, TypeScript, AbortController, react-window (FixedSizeList), Zustand

---

## File Structure

| File | Role |
|------|------|
| `console/src/api/request.ts` | Generic fetch wrapper — already accepts `RequestInit` (signal passthrough) |
| `console/src/api/modules/chat.ts` | Chat API — `getChat` needs signal support |
| `console/src/pages/Chat/sessionApi/index.ts` | Core session management — AbortController, LRU cache, shallow compare |
| `console/src/pages/Chat/components/ChatSessionDrawer/index.tsx` | Non-embedded session click handler |
| `console/src/pages/Chat/components/ChatSessionDrawer/useSessionListData.ts` | Shared polling + itemData logic |
| `console/src/pages/Chat/components/ChatSessionInitializer/index.tsx` | Embedded-mode session switch handler |

---

## Task 1: api.getChat — Add AbortSignal Support

**Files:**
- Modify: `console/src/api/modules/chat.ts:71-72`

- [ ] **Step 1: Update `getChat` to accept options with signal**

```typescript
// In console/src/api/modules/chat.ts, replace:
getChat: (chatId: string) =>
  request<ChatHistory>(`/chats/${encodeURIComponent(chatId)}`),

// With:
getChat: (chatId: string, options?: { signal?: AbortSignal }) =>
  request<ChatHistory>(`/chats/${encodeURIComponent(chatId)}`, {
    signal: options?.signal,
  }),
```

- [ ] **Step 2: Verify TypeScript compiles**

Run: `cd console && npx tsc --noEmit --pretty 2>&1 | head -30`
Expected: No errors related to chat.ts

- [ ] **Step 3: Commit**

```bash
git add console/src/api/modules/chat.ts
git commit -m "feat(api): add AbortSignal support to getChat"
```

---

## Task 2: sessionApi — Add AbortController Management + startNewSwitch

**Files:**
- Modify: `console/src/pages/Chat/sessionApi/index.ts:437-490`

- [ ] **Step 1: Add switchAbortController field and startNewSwitch method**

After the `isSessionSwitching` field (line ~438), add:

```typescript
/** AbortController for the current switch — aborted when a new switch starts. */
private switchAbortController: AbortController | null = null;

/**
 * Start a new session switch. Aborts any in-flight switch and returns a
 * fresh AbortController whose signal should be threaded through all async ops.
 */
startNewSwitch(): AbortController {
  // Cancel previous in-flight switch
  this.switchAbortController?.abort();
  const controller = new AbortController();
  this.switchAbortController = controller;
  this.isSessionSwitching = true;
  return controller;
}
```

- [ ] **Step 2: Update finishSessionSwitch to clear the controller**

Replace existing `finishSessionSwitch`:

```typescript
/** Called when a switch completes (or is superseded). */
finishSessionSwitch(): void {
  this.isSessionSwitching = false;
  this.switchAbortController = null;
}
```

- [ ] **Step 3: Update preloadSession to accept and forward signal**

Replace the existing `preloadSession` method:

```typescript
async preloadSession(
  sessionId: string,
  signal?: AbortSignal,
): Promise<{
  session: IAgentScopeRuntimeWebUISession;
  realId: string | null;
}> {
  try {
    const session = await this.getSession(sessionId, signal);
    const extendedSession = session as ExtendedSession;
    const realId = extendedSession.realId || null;

    // Cache the result so subsequent getSession calls return immediately.
    this.sessionResultCache.set(sessionId, session);
    if (realId) {
      this.sessionResultCache.set(realId, session);
    }
    // Clear cache after 3s (enough for the library's useAsyncEffect to fire).
    setTimeout(() => {
      this.sessionResultCache.delete(sessionId);
      if (realId) this.sessionResultCache.delete(realId);
    }, 3000);

    return { session, realId };
  } catch (error) {
    // Don't reset switching state on abort — the new switch owns the lock
    if (error instanceof DOMException && error.name === "AbortError") {
      throw error;
    }
    this.isSessionSwitching = false;
    throw error;
  }
}
```

- [ ] **Step 4: Update getSession to accept and forward signal**

Update the `getSession` method signature and pass signal to `_doGetSession`:

```typescript
async getSession(sessionId: string, signal?: AbortSignal) {
  // Check short-lived result cache first (populated by preloadSession).
  const cached = this.sessionResultCache.get(sessionId);
  if (cached) return cached;

  const existingRequest = this.sessionRequests.get(sessionId);
  if (existingRequest) return existingRequest;

  const requestPromise = this._doGetSession(sessionId, signal);
  this.sessionRequests.set(sessionId, requestPromise);

  try {
    const session = await requestPromise;
    const extendedSession = session as ExtendedSession;
    const realId = extendedSession.realId || null;

    if (!this.lastSelectedIds.has(sessionId)) {
      this.lastSelectedIds.clear();
      this.lastSelectedIds.add(sessionId);
      if (realId) this.lastSelectedIds.add(realId);
      this.onSessionSelected?.(sessionId, realId);
    }
    return session;
  } finally {
    this.sessionRequests.delete(sessionId);
  }
}
```

- [ ] **Step 5: Update _doGetSession and fetchAndBuildSession to accept signal**

Update `_doGetSession` signature:

```typescript
private async _doGetSession(
  sessionId: string,
  signal?: AbortSignal,
): Promise<IAgentScopeRuntimeWebUISession> {
```

In each branch that calls `fetchAndBuildSession`, pass `signal`:

```typescript
return await this.fetchAndBuildSession(sessionId, fromList.realId, fromList, signal);
// ... and similarly for other branches
return await this.fetchAndBuildSession(sessionId, sessionId, this.findSession(sessionId), signal);
```

Update `fetchAndBuildSession`:

```typescript
private async fetchAndBuildSession(
  displayId: string,
  backendId: string,
  listEntry: ExtendedSession | undefined,
  signal?: AbortSignal,
): Promise<ExtendedSession> {
  const chatHistory = await api.getChat(backendId, { signal });
  if (signal?.aborted) throw new DOMException("Aborted", "AbortError");
  const generating = isGenerating(chatHistory);
  const messages = convertMessages(chatHistory.messages || []);
  this.patchLastUserMessage(messages, generating, backendId);

  const session: ExtendedSession = {
    id: displayId,
    name: listEntry?.name || DEFAULT_SESSION_NAME,
    sessionId: listEntry?.sessionId || displayId,
    userId: listEntry?.userId || DEFAULT_USER_ID,
    channel: listEntry?.channel || DEFAULT_CHANNEL,
    messages,
    meta: listEntry?.meta || {},
    realId: listEntry?.realId,
    generating,
  };
  this.updateWindowVariables(session);
  return session;
}
```

- [ ] **Step 6: Verify TypeScript compiles**

Run: `cd console && npx tsc --noEmit --pretty 2>&1 | head -30`
Expected: No errors

- [ ] **Step 7: Commit**

```bash
git add console/src/pages/Chat/sessionApi/index.ts
git commit -m "feat(sessionApi): add AbortController-based cancellable session switching"
```

---

## Task 3: ChatSessionDrawer — Refactor handleSessionClick to Cancellable Switch

**Files:**
- Modify: `console/src/pages/Chat/components/ChatSessionDrawer/index.tsx:317-413`

- [ ] **Step 1: Replace handleSessionClick with cancellable version**

Replace the existing `handleSessionClick` useCallback (lines ~317-390):

```typescript
const handleSessionClick = useCallback(
  (sessionId: string) => {
    if (sessionId === currentSessionId) {
      return;
    }

    if (props.embedded) {
      setSwitchingSessionId(sessionId);
      window.dispatchEvent(
        new CustomEvent("qwenpaw:sidebar-select-session", {
          detail: { sessionId },
        }),
      );
      return;
    }

    // Start a new cancellable switch (aborts any in-flight switch)
    const controller = sessionApi.startNewSwitch();
    setSwitchingSessionId(sessionId);

    sessionApi
      .preloadSession(sessionId, controller.signal)
      .then(({ realId }) => {
        if (controller.signal.aborted) return;
        const effectiveId = sessionApi.getEffectiveSessionId(
          sessionId,
          realId,
        );
        if (!codingMode) {
          const targetUrl = buildSessionPath("chat", effectiveId);
          navigate(targetUrl, { replace: true });
        }
        sessionApi.trackNavigatedSession(
          effectiveId,
          setLastChatId,
          selectedAgent,
        );
        setCurrentSessionId(sessionId);
      })
      .catch((err) => {
        if (err?.name === "AbortError") return;
        // On non-abort error, still try to switch normally.
        setCurrentSessionId(sessionId);
      })
      .finally(() => {
        // Only clean up if this switch was NOT superseded by a newer one
        if (!controller.signal.aborted) {
          sessionApi.finishSessionSwitch();
          setSwitchingSessionId(null);
        }
      });
  },
  [
    currentSessionId,
    setCurrentSessionId,
    navigate,
    codingMode,
    selectedAgent,
    setLastChatId,
    props.embedded,
  ],
);
```

- [ ] **Step 2: Remove the 2-rAF + 2000ms timeout logic**

The old `.then(() => { return new Promise<void>((resolve) => { requestAnimationFrame(...) setTimeout(...) }) })` block is removed — replaced by the simpler `.finally()` above.

- [ ] **Step 3: Remove the 500ms fallback interval useEffect**

Delete the useEffect that polls `sessionApi.isSessionSwitching` every 500ms (lines ~405-413):

```typescript
// DELETE this entire useEffect:
useEffect(() => {
  if (!switchingSessionId) return;
  const id = setInterval(() => {
    if (!sessionApi.isSessionSwitching) {
      setSwitchingSessionId(null);
    }
  }, 500);
  return () => clearInterval(id);
}, [switchingSessionId]);
```

- [ ] **Step 4: Verify TypeScript compiles**

Run: `cd console && npx tsc --noEmit --pretty 2>&1 | head -30`
Expected: No errors

- [ ] **Step 5: Commit**

```bash
git add console/src/pages/Chat/components/ChatSessionDrawer/index.tsx
git commit -m "feat(ChatSessionDrawer): cancellable session switch, remove timeout fallbacks"
```

---

## Task 4: ChatSessionInitializer — Refactor Embedded Mode to Cancellable Switch

**Files:**
- Modify: `console/src/pages/Chat/components/ChatSessionInitializer/index.tsx:135-218`

- [ ] **Step 1: Add a controller ref for managing ongoing embedded switches**

After the existing refs (line ~71), add:

```typescript
const switchControllerRef = useRef<AbortController | null>(null);
```

- [ ] **Step 2: Replace handleSelectSession with cancellable version**

Replace the existing `handleSelectSession` function (lines ~142-186):

```typescript
const handleSelectSession = (e: Event) => {
  const sessionId = (e as CustomEvent<{ sessionId: string }>).detail
    .sessionId;
  if (!sessionId) return;

  const mode = codingModeRef.current ? "coding" : "chat";
  const currentSessions = sessionsRef.current;
  const matching = currentSessions.find((s) => s.id === sessionId);

  if (matching) {
    // Abort any previous embedded switch
    switchControllerRef.current?.abort();
    const controller = new AbortController();
    switchControllerRef.current = controller;

    sessionApi.isSessionSwitching = true;
    sessionApi
      .preloadSession(sessionId, controller.signal)
      .then(({ realId }) => {
        if (controller.signal.aborted) return;
        const effectiveId = sessionApi.getEffectiveSessionId(
          sessionId,
          realId,
        );
        const targetUrl = buildSessionPath(mode, effectiveId);
        sessionApi.trackNavigatedSession(effectiveId);
        navigate(targetUrl, { replace: true });
        setCurrentSessionId(sessionId);
      })
      .catch((err) => {
        if (err?.name === "AbortError") return;
        setCurrentSessionId(sessionId);
      })
      .finally(() => {
        if (!controller.signal.aborted) {
          sessionApi.finishSessionSwitch();
          window.dispatchEvent(
            new CustomEvent("qwenpaw:sidebar-switch-done"),
          );
        }
      });
  }
};
```

- [ ] **Step 3: Remove the old 2000ms fallback Promise in finally**

The old `return new Promise<void>(() => { requestAnimationFrame(...) setTimeout(...) })` block is gone — no longer needed.

- [ ] **Step 4: Verify TypeScript compiles**

Run: `cd console && npx tsc --noEmit --pretty 2>&1 | head -30`
Expected: No errors

- [ ] **Step 5: Commit**

```bash
git add console/src/pages/Chat/components/ChatSessionInitializer/index.tsx
git commit -m "feat(ChatSessionInitializer): cancellable embedded session switch"
```

---

## Task 5: Polling — Pause During Session Switch

**Files:**
- Modify: `console/src/pages/Chat/components/ChatSessionDrawer/index.tsx:295-304`
- Modify: `console/src/pages/Chat/components/ChatSessionDrawer/useSessionListData.ts:146-157`

- [ ] **Step 1: Add isSessionSwitching guard in ChatSessionDrawer polling**

In the setInterval callback (line ~295):

```typescript
const timer = setInterval(async () => {
  // Pause polling during session switch to avoid bandwidth contention
  if (sessionApi.isSessionSwitching) return;
  try {
    const list = await sessionApi.getSessionList();
    if (!isCancelled) {
      setSessions(list);
    }
  } catch {
    // ignore polling errors
  }
}, 3000);
```

- [ ] **Step 2: Add same guard in useSessionListData polling**

In `useSessionListData.ts`, inside the setInterval callback (line ~146):

```typescript
const timer = setInterval(async () => {
  // Pause polling during session switch to avoid bandwidth contention
  if (sessionApi.isSessionSwitching) return;
  try {
    const list = await sessionApi.getSessionList();
    if (!cancelled) {
      const extended = list as ExtendedChatSession[];
      setSessions(extended);
      syncSessionsGlobal(extended);
    }
  } catch {
    // ignore polling errors
  }
}, 3000);
```

- [ ] **Step 3: Commit**

```bash
git add console/src/pages/Chat/components/ChatSessionDrawer/index.tsx \
        console/src/pages/Chat/components/ChatSessionDrawer/useSessionListData.ts
git commit -m "perf(polling): pause session list polling during switch"
```

---

## Task 6: Session List Shallow Compare — Prevent Unnecessary Re-renders

**Files:**
- Modify: `console/src/pages/Chat/sessionApi/index.ts:718-814`

- [ ] **Step 1: Add `isSessionListEqual` private method**

Before `applyChatsToSessionList`, add:

```typescript
/**
 * Shallow-compare two session lists by key fields.
 * Returns true if lists are structurally identical (no re-render needed).
 */
private isSessionListEqual(
  prev: IAgentScopeRuntimeWebUISession[],
  next: IAgentScopeRuntimeWebUISession[],
): boolean {
  if (prev.length !== next.length) return false;
  for (let i = 0; i < prev.length; i++) {
    const a = prev[i] as ExtendedSession;
    const b = next[i] as ExtendedSession;
    if (
      a.id !== b.id ||
      a.name !== b.name ||
      a.status !== b.status ||
      a.updatedAt !== b.updatedAt ||
      a.pinned !== b.pinned ||
      a.generating !== b.generating ||
      a.realId !== b.realId
    ) {
      return false;
    }
  }
  return true;
}
```

- [ ] **Step 2: Use shallow compare at end of applyChatsToSessionList**

At the very end of `applyChatsToSessionList`, before the final `return`, replace:

```typescript
// Old:
return [...this.sessionList];

// New:
// If the list hasn't changed substantively, return the previous array reference
// to prevent downstream useMemo / React re-renders.
const previousList = this._prevReturnedList;
if (previousList && this.isSessionListEqual(previousList as IAgentScopeRuntimeWebUISession[], this.sessionList)) {
  return previousList;
}
const result = [...this.sessionList];
this._prevReturnedList = result;
return result;
```

Add a private field to the class:

```typescript
/** Previous returned list reference for shallow-compare optimisation. */
private _prevReturnedList: IAgentScopeRuntimeWebUISession[] | null = null;
```

- [ ] **Step 3: Verify TypeScript compiles**

Run: `cd console && npx tsc --noEmit --pretty 2>&1 | head -30`
Expected: No errors

- [ ] **Step 4: Commit**

```bash
git add console/src/pages/Chat/sessionApi/index.ts
git commit -m "perf(sessionApi): shallow-compare session list to prevent unnecessary re-renders"
```

---

## Task 7: Sort Optimization + itemData Stabilization

**Files:**
- Modify: `console/src/pages/Chat/components/ChatSessionDrawer/index.tsx:248-263, 577-611`
- Modify: `console/src/pages/Chat/components/ChatSessionDrawer/useSessionListData.ts:165-182`

- [ ] **Step 1: Optimize sortedSessions — use string comparison**

In `ChatSessionDrawer/index.tsx` (lines ~248-263), replace Date comparison:

```typescript
const sortedSessions = useMemo(() => {
  return [...sessions].sort((a, b) => {
    const extA = a as ExtendedChatSession;
    const extB = b as ExtendedChatSession;

    if (extA.pinned && !extB.pinned) return -1;
    if (!extA.pinned && extB.pinned) return 1;

    // ISO 8601 strings are lexicographically sortable — avoid new Date()
    const aTime = extA.updatedAt ?? extA.createdAt ?? "";
    const bTime = extB.updatedAt ?? extB.createdAt ?? "";
    if (!aTime && !bTime) return 0;
    if (!aTime) return 1;
    if (!bTime) return -1;
    return bTime < aTime ? -1 : bTime > aTime ? 1 : 0;
  });
}, [sessions]);
```

Apply the same change in `useSessionListData.ts` (lines ~165-182):

```typescript
const sortedSessions = useMemo(() => {
  return [...sessions]
    .filter((s) => {
      const id = s.id ?? "";
      return !(/^\d+-[a-z0-9]+$/.test(id) && !s.realId);
    })
    .sort((a, b) => {
      if (a.pinned && !b.pinned) return -1;
      if (!a.pinned && b.pinned) return 1;
      const aTime = a.updatedAt ?? a.createdAt ?? "";
      const bTime = b.updatedAt ?? b.createdAt ?? "";
      if (!aTime && !bTime) return 0;
      if (!aTime) return 1;
      if (!bTime) return -1;
      return bTime < aTime ? -1 : bTime > aTime ? 1 : 0;
    });
}, [sessions]);
```

- [ ] **Step 2: Stabilize itemData via ref in ChatSessionDrawer**

In `ChatSessionDrawer/index.tsx`, replace the itemData useMemo (lines ~577-611):

```typescript
// Hold latest sortedSessions in a ref so itemData doesn't depend on it
const sortedSessionsRef = useRef(sortedSessions);
sortedSessionsRef.current = sortedSessions;

const itemData = useMemo<SessionRowData>(
  () => ({
    sortedSessionsRef,
    currentSessionId,
    switchingSessionId,
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
    handleItemContextMenu,
  }),
  [
    currentSessionId,
    switchingSessionId,
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
    handleItemContextMenu,
  ],
);
```

- [ ] **Step 3: Update SessionRowData interface and SessionRow component**

Update `SessionRowData` to use ref:

```typescript
interface SessionRowData {
  sortedSessionsRef: React.MutableRefObject<ExtendedChatSession[]>;
  currentSessionId: string | undefined;
  switchingSessionId: string | null;
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
  handleItemContextMenu: (sessionId: string, event: React.MouseEvent) => void;
}
```

Update `SessionRow`:

```typescript
const SessionRow = React.memo(function SessionRow({
  index,
  style,
  data,
}: ListChildComponentProps<SessionRowData>) {
  const session = data.sortedSessionsRef.current[index];
  if (!session) return null;
  const channelKey = session.channel?.trim() || "";
  // ... rest unchanged
});
```

- [ ] **Step 4: Verify TypeScript compiles**

Run: `cd console && npx tsc --noEmit --pretty 2>&1 | head -30`
Expected: No errors

- [ ] **Step 5: Commit**

```bash
git add console/src/pages/Chat/components/ChatSessionDrawer/index.tsx \
        console/src/pages/Chat/components/ChatSessionDrawer/useSessionListData.ts
git commit -m "perf(ChatSessionDrawer): optimize sort + stabilize itemData via ref"
```

---

## Task 8: LRU Converted Session Cache

**Files:**
- Modify: `console/src/pages/Chat/sessionApi/index.ts`

- [ ] **Step 1: Add LRU cache fields and helper methods**

After the `sessionResultCache` field (line ~452), add:

```typescript
// ---------------------------------------------------------------------------
// LRU cache for fully-converted sessions (avoids re-fetching on switch-back)
// ---------------------------------------------------------------------------

private static readonly CONVERTED_CACHE_MAX = 10;
private static readonly CONVERTED_CACHE_TTL = 5 * 60 * 1000; // 5 minutes

/** LRU cache: backendId → { session, timestamp } */
private convertedSessionCache = new Map<
  string,
  { session: ExtendedSession; timestamp: number }
>();

private getCachedConvertedSession(backendId: string): ExtendedSession | null {
  const entry = this.convertedSessionCache.get(backendId);
  if (!entry) return null;
  if (Date.now() - entry.timestamp > SessionApi.CONVERTED_CACHE_TTL) {
    this.convertedSessionCache.delete(backendId);
    return null;
  }
  // LRU: move to end
  this.convertedSessionCache.delete(backendId);
  this.convertedSessionCache.set(backendId, entry);
  return entry.session;
}

private setCachedConvertedSession(
  backendId: string,
  session: ExtendedSession,
): void {
  if (this.convertedSessionCache.size >= SessionApi.CONVERTED_CACHE_MAX) {
    // Evict oldest (first entry in Map iteration order)
    const oldestKey = this.convertedSessionCache.keys().next().value;
    if (oldestKey) this.convertedSessionCache.delete(oldestKey);
  }
  this.convertedSessionCache.set(backendId, {
    session,
    timestamp: Date.now(),
  });
}

/** Invalidate the converted cache for a session (call after sending a message). */
invalidateConvertedCache(backendId: string): void {
  this.convertedSessionCache.delete(backendId);
}
```

- [ ] **Step 2: Use cache in fetchAndBuildSession**

At the top of `fetchAndBuildSession`, add cache check:

```typescript
private async fetchAndBuildSession(
  displayId: string,
  backendId: string,
  listEntry: ExtendedSession | undefined,
  signal?: AbortSignal,
): Promise<ExtendedSession> {
  // Check LRU cache for non-generating sessions
  const isIdle = !listEntry?.generating;
  if (isIdle) {
    const cached = this.getCachedConvertedSession(backendId);
    if (cached) {
      // Update mutable fields that may differ
      cached.id = displayId;
      if (listEntry?.name) cached.name = listEntry.name;
      this.updateWindowVariables(cached);
      return cached;
    }
  }

  const chatHistory = await api.getChat(backendId, { signal });
  if (signal?.aborted) throw new DOMException("Aborted", "AbortError");
  const generating = isGenerating(chatHistory);
  const messages = convertMessages(chatHistory.messages || []);
  this.patchLastUserMessage(messages, generating, backendId);

  const session: ExtendedSession = {
    id: displayId,
    name: listEntry?.name || DEFAULT_SESSION_NAME,
    sessionId: listEntry?.sessionId || displayId,
    userId: listEntry?.userId || DEFAULT_USER_ID,
    channel: listEntry?.channel || DEFAULT_CHANNEL,
    messages,
    meta: listEntry?.meta || {},
    realId: listEntry?.realId,
    generating,
  };
  this.updateWindowVariables(session);

  // Cache non-generating sessions
  if (!generating) {
    this.setCachedConvertedSession(backendId, session);
  }

  return session;
}
```

- [ ] **Step 3: Invalidate cache on session delete**

In the existing `removeSession` or wherever session deletion happens, call:

```typescript
this.invalidateConvertedCache(backendId);
```

Also expose it so ChatPage can call it after sending a message:

```typescript
// Already public via: invalidateConvertedCache(backendId: string)
```

- [ ] **Step 4: Verify TypeScript compiles**

Run: `cd console && npx tsc --noEmit --pretty 2>&1 | head -30`
Expected: No errors

- [ ] **Step 5: Commit**

```bash
git add console/src/pages/Chat/sessionApi/index.ts
git commit -m "perf(sessionApi): add LRU cache for converted sessions"
```

---

## Task 9: convertMessages Optimization

**Files:**
- Modify: `console/src/pages/Chat/sessionApi/index.ts:258-277`

- [ ] **Step 1: Optimize convertMessages to use slice instead of push loop**

Replace the existing `convertMessages` function:

```typescript
const convertMessages = (
  messages: Message[],
): IAgentScopeRuntimeWebUIMessage[] => {
  const result: IAgentScopeRuntimeWebUIMessage[] = [];
  const len = messages.length;
  let i = 0;

  while (i < len) {
    if (messages[i].role === ROLE_USER) {
      result.push(buildUserCard(messages[i++]));
    } else {
      // Collect consecutive non-user messages
      const startIdx = i;
      while (i < len && messages[i].role !== ROLE_USER) i++;
      const outputMsgs = messages.slice(startIdx, i).map(toOutputMessage);
      if (outputMsgs.length) result.push(buildResponseCard(outputMsgs));
    }
  }

  return result;
};
```

- [ ] **Step 2: Commit**

```bash
git add console/src/pages/Chat/sessionApi/index.ts
git commit -m "perf(sessionApi): optimize convertMessages with slice"
```

---

## Task 10: Integration Verification

- [ ] **Step 1: Full TypeScript check**

Run: `cd console && npx tsc --noEmit --pretty`
Expected: Clean — no errors

- [ ] **Step 2: Lint check**

Run: `cd console && npx eslint src/pages/Chat/sessionApi/index.ts src/pages/Chat/components/ChatSessionDrawer/index.tsx src/pages/Chat/components/ChatSessionInitializer/index.tsx src/api/modules/chat.ts --max-warnings=0 2>&1 | tail -20`
Expected: No errors (warnings acceptable if pre-existing)

- [ ] **Step 3: Final commit (if any lint fixes needed)**

```bash
git add -A
git commit -m "chore: lint fixes for session switch performance"
```
