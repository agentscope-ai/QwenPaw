## Description

Fix session navigation bug where navigating to Settings/Agent/Control loses the active session ID.

**Problem:**
When users navigate from Chat to Settings (or Agent/Control sections), the React component unmounts and `window.currentSessionId` is lost. When returning to Chat, a new empty session is created instead of restoring the previous one.

**Root Cause:**
Session ID was stored only in `window.currentSessionId` (JavaScript global) which is lost when React components unmount. No persistence mechanism existed to restore the active session ID on remount.

**Solution:**
Add LocalStorage persistence for session ID:
- Key: `agent-scope-current-session-id`
- Saved on: session creation, session switch, session update
- Restored on: component mount, navigation return

**Fixes:**
- Chat → Settings → Chat now returns to same session
- Chat → Agent → Chat now returns to same session
- Chat → Control → Chat now returns to same session
- Browser refresh preserves active session

## Type of Change

- [x] Bug fix

## Component(s) Affected

- [x] Console (frontend web UI)

## Changes

### `console/src/pages/Chat/sessionApi/index.ts`
- Add `currentSessionKey` property for LocalStorage key name
- Add `saveCurrentSessionId()` method
- Add `getCurrentSessionId()` method
- Modify `getLocalSession()` to restore persisted session
- Modify `createSession()` to persist new session ID
- Modify `updateSession()` to persist session ID

### `console/src/pages/Chat/index.tsx`
- Add `useEffect` hook to restore session on mount
- Import `useEffect` from React

## Testing

### Manual Tests Completed
| Test | Result |
|------|--------|
| Chat → Settings → Chat | ✅ Pass |
| Chat → Agent → Chat | ✅ Pass |
| Chat → Control → Chat | ✅ Pass |
| Browser refresh | ✅ Pass |
| LocalStorage key exists | ✅ Pass |
| New session creation | ✅ Pass |

### CI Tests
- [x] `npm run build` passes
- [x] `npm run format:check` passes
- [x] TypeScript compilation passes
- [x] No new ESLint errors introduced

## Backward Compatibility

| Scenario | Behavior |
|----------|----------|
| Existing sessions | Works ✅ |
| New sessions | Works ✅ |
| No localStorage key | Creates new session (graceful) ✅ |
| Corrupted key | Creates new session (graceful) ✅ |
| Private/Incognito | Creates new session (expected) ✅ |

## Checklist

- [x] I ran `pre-commit run --all-files` locally and it passes
- [x] I ran tests locally and they pass
- [x] Documentation updated (PR description)
- [x] Ready for review

## Related Issue

Fixes console session loss on navigation.
