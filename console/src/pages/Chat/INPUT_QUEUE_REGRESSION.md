# Chat Input Queue Regression Checklist

Last refreshed: 2026-07-03

Source snapshot: extracted from the Yuque documents "用户输入队列方案设计" and
"修复聊天输入队列会话 ID 迁移问题汇总" via `only_read_docs`. Keep this file as
the local regression source of truth so future PR5514 checks do not need to
re-read the external docs.

## Required Verification Commands

Run from `console/` unless noted otherwise.

```bash
npm run build
npm run test:run
```

`npm run lint` is useful signal, but currently fails on repository-wide existing
lint debt. Do not treat it as PR5514-specific failure unless new errors are
introduced in the input queue/session paths.

## Core Scenarios

| ID | Scenario | Regression Check | Status |
| --- | --- | --- | --- |
| A | Continuous follow-up | While the assistant is generating, enqueue multiple follow-up messages with Ctrl/Cmd+Enter. They should drain in order after the current response completes. | Must pass |
| B | Reorder queued prompts | Queue at least three prompts, drag the second ahead of the first, and confirm the new order is used for sending. | Must pass |
| C | Edit queued message | Edit a queued prompt and confirm the updated text is sent. Empty text must show a user-facing warning instead of silently dropping/sending an empty prompt. | Risk: verify manually |
| D | Send failure handling | Force a queued send failure. The item should be marked failed, queue draining should stop, and retry/delete/clear should remain available. | Must pass |
| E | Session switching | Queue messages in Topic A, switch to Topic B, then return to Topic A. Each session should show only its own queue. | Must pass |
| F | Attachments in queue | Queue text plus image/file attachment. The sender preview should clear, the queue panel should show the attachment, and the eventual request should preserve file/image fields. | Must pass |
| G | Pause then refresh | Pause a non-empty queue, refresh/reopen the page, and confirm the queue stays paused until the user resumes it. | Must pass |
| H | Multi-tab collaboration | Open the same chat in two tabs. Only one tab should own sending; the peer tab should enqueue into the shared queue and take over after owner closes/expires. | Must pass |
| I | Background draining | Leave ChatPage with a real backend session and pending queue. The background runner should continue draining, with localStorage and in-memory state synchronized when returning. | Must pass |
| J | New chat passthrough | On `/chat` or an unresolved local session, Enter/Ctrl+Enter should pass through the SDK's normal create-chat flow instead of being swallowed by the queue. | Risk: verify pure numeric temp URL manually |

## PR5514 Bug Regression

| ID | Bug | Regression Check | Status |
| --- | --- | --- | --- |
| B1 | Same agent, different tabs: message sent but no response | In same-agent multi-tab mode, send while another tab has queue ownership. The request must preserve session context and receive/patch the response. | Must pass |
| B2 | Switching between Test1/Test2 shows wrong queue and sends in new chat | Queue in Test1 and Test2, switch back and forth, then send. Queue/session id must follow the visible chat rather than stale SDK state. | Must pass |
| B3 | Switching agents sends queued messages to another agent | Queue under Test2, switch agents repeatedly, then drain. Queued request must keep original agent context. | Must pass |
| B4 | Tab1 Test1 queue blocks Tab2 Test2 queue/send | Run queues in two different sessions/tabs. Ownership and background runners must be scoped by queueSessionId, so one chat does not block the other. | Must pass |
| B5 | Tab2 switching agent to Test1 makes Tab1 Test1 lose tasks until refresh | With active queues in Tab1/Tab2, switch Tab2 agent/session. Tab1 queue should remain visible and synchronized without requiring refresh. | Must pass |

## Local Implementation Anchors

Use these files first when checking regressions:

- `chatSessionIds.ts`: agent-scoped queue id construction and queue/backend id stripping.
- `inputQueueStorage.ts`: localStorage migration from temporary queue id to real backend queue id.
- `index.tsx`: SDK queue integration through `getSessionId`, `getRequestContext`, and `isSessionRunning`.
- `sessionApi/index.ts`: active-agent cache reset, queue session id lookup, requested-session identity lookup, and stale async response protection.
- `components/ChatSessionInitializer/index.tsx`: route-to-SDK session synchronization for real id, local id, and backend session id aliases.

## Current Known Risks

- Scenario C needs explicit manual confirmation until there is an automated or
SDK-level assertion that empty edited queue text warns the user.
- Scenario J needs explicit manual confirmation for direct numeric temporary
URLs not present in `sessionApi.sessionList`.
- If Chat-specific unit test files are deleted or excluded, `npm run test:run`
can still pass while leaving queue/session behavior under-covered. Check
`git status` and the changed test set before calling coverage complete.
