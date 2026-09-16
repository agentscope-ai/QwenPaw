import { findVoiceSender } from "./voiceSender";
import { useVoiceScope } from "@/api/voiceScope";
import { voiceApi } from "@/api/modules/voice";
import {
  AgentScopeRuntimeWebUI,
  IAgentScopeRuntimeWebUIOptions,
  type IAgentScopeRuntimeWebUIRef,
} from "@agentscope-ai/chat";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { handleArtifactDownloadLink } from "./artifactDownloadLink";
import { artifactLocatorFromFileCard } from "./fileCardLocator";
import { Alert, Button, Modal, Result, Tooltip } from "antd";
import { useAppMessage } from "../../hooks/useAppMessage";
import { useIsMobile } from "../../hooks/useIsMobile";
import { ExclamationCircleOutlined, SettingOutlined } from "@ant-design/icons";
import { SparkCopyLine, SparkAttachmentLine } from "@agentscope-ai/icons";
import { usePlugins } from "../../plugins/PluginContext";
import { useTranslation } from "react-i18next";
import { AnimatePresence, motion, useReducedMotion } from "motion/react";
import i18n from "../../i18n";
import { useLocation, useNavigate } from "react-router-dom";
import sessionApi from "./sessionApi";
import { resolveStopChatId } from "./chatIdentity";
import { modelCatalogApi } from "@/api/modules/modelCatalog";
import { useAuthStore } from "@/stores/authStore";
import {
  chooseConversationModel,
  currentModelContext,
  isCurrentModelContext,
  loadConversationModel,
  draftModel,
} from "./conversationModel";
import {
  attachClientMessageId,
  createClientMessageId,
  QWENPAW_CLIENT_MESSAGE_ID_KEY,
} from "../../utils/clientMessageId";
import defaultConfig, { getDefaultConfig } from "./OptionsPanel/defaultConfig";
import { chatApi } from "../../api/modules/chat";
import { isConversationReadOnly } from "../../api/types/chat";
import { planApi } from "../../api/modules/plan";
import { getApiUrl } from "../../api/config";
import { buildAuthHeaders } from "../../api/authHeaders";
import { slashApi, type SlashCatalogItem } from "../../api/modules/slash";
import {
  listChatFileCandidates,
  encodeFileMention,
  rewriteFileMentions,
  sourceLabels,
  type ChatFileCandidate,
} from "./fileMentions";
import ModelSelector from "./ModelSelector";
import PublicationModelLock from "./components/PublicationModelLock";
import { useTheme } from "../../contexts/ThemeContext";
import {
  isAgentHistoricalReadOnly,
  useAgentStore,
} from "../../stores/agentStore";
import {
  syncSessionsGlobal,
  useSessionListStore,
} from "../../stores/sessionListStore";
import {
  beginLoopModeSubmission,
  fetchActiveLoopMode,
  fetchAvailableLoopModes,
  markLoopModeRunning,
  prepareLoopModeMessage,
  useLoopStore,
} from "../../stores/loopStore";
import { buildLoopSlashSuggestions } from "./loopSlashSuggestions";
import { InlineMarkdown } from "../../components/Markdown/InlineMarkdown";
import { LoopModeSelector } from "../../components/LoopInput";
import {
  useChatAnywhereInput,
  useChatAnywhereSessionsState,
} from "@agentscope-ai/chat";
import styles from "./index.module.less";
import { IconButton } from "@agentscope-ai/design";
import ChatActionGroup from "./components/ChatActionGroup";
import ChatSessionDrawer from "./components/ChatSessionDrawer";
import { useSidebarModeStore } from "../../stores/sidebarModeStore";
import ContextUsageIndicator from "./components/ContextUsageIndicator";
import {
  patchContextMaxInputLength,
  wrapChatResponseUsageStream,
} from "./turnUsage";
import { wrapReplayFastForward } from "./replayFastForward";
import { useTurnUsageStore } from "./turnUsageStore";
import ChatHeaderTitle from "./components/ChatHeaderTitle";
import ChatSessionInitializer from "./components/ChatSessionInitializer";
import { replaceRuntimeMessageSnapshot } from "./runtimeMessageSnapshot";
import { ChatTransportLifecycle } from "./chatTransportLifecycle";
import { ApprovalCard } from "../../components/ApprovalCard/ApprovalCard";
import TaskInteractionPanel from "../../components/TaskInteractionPanel";
import { commandsApi } from "../../api/modules/commands";
import { useApprovalContext } from "../../contexts/ApprovalContext";
import {
  useChatScalarSnapshot,
  useChatListSnapshot,
} from "../../plugins/registry/useChatExtensions";
import { PluginSlotBoundary } from "../../plugins/registry/PluginSlotBoundary";
import {
  resolveLocalized,
  type ChatApprovalRendererItem,
  type WelcomeRenderProps,
} from "../../plugins/registry/types";
import { ChatScalar, ChatList } from "../../plugins/registry/slotKeys";
import { HostRequestCard, HostResponseCard } from "./HostBubbles";
import { withGenericFallback } from "../../components/Chat/ToolCards/adapters/v1Adapter";
import { applyApprovalLevelToRequestBody } from "./approvalPayload";
import {
  createHeadlineFilterState,
  filterHeadlineDelta,
  flushHeadlineFilter,
  type HeadlineStreamFilterState,
  stripScrollHeadlineTextBlocks,
} from "./headlineFilter";
import FilesDrawer from "../../features/files-workspace/FilesDrawer";
import SessionProjectDirectory from "../../features/project-directory/SessionProjectDirectory";
import {
  sessionFilesScopeKey,
  type FilesWorkspaceScope,
} from "../../features/files-workspace/filesWorkspaceScope";
import {
  filePathFromPreviewUrl,
  parseInternalFileLink,
  rootForFileReference,
} from "../../features/files-workspace/internalFileLinks";
import type {
  FilesDrawerEvent,
  FileTarget,
} from "../../features/files-workspace/types";
import { chatProjectDirectoryApi } from "../../api/modules/chatProjectDirectory";
import { projectDirectoryApi } from "../../api/modules/projectDirectory";
import {
  getPendingProjectDirectory,
  migratePendingProjectDirectory,
  setPendingProjectDirectory,
  withPendingProjectDirectory,
} from "../../features/project-directory/pendingProjectDirectory";
import {
  useFilesSurfaceStore,
  useSessionFilesDrawer,
} from "../../stores/filesSurfaceStore";
import { useCodingTabsStore } from "../../stores/codingTabsStore";
import { RichFileReferenceInputProvider } from "./RichFileReferenceInput";
import type { ParsedFileReference } from "./fileReferenceFormatting";
import {
  findPersonalLibraryMentionToken,
  rewritePersonalLibraryMentionsInInput,
} from "./personalLibraryMentions";
import { scrollReverseMessageList } from "./messageScroll";
import { useSharedConversationAccessGuard } from "./hooks/useSharedConversationAccessGuard";

interface ApprovalMessageData {
  requestId: string;
  sessionId: string;
  rootSessionId?: string;
  agentId: string;
  toolName: string;
  toolSource?: string;
  severity: string;
  findingsCount: number;
  findingsSummary: string;
  toolParams: Record<string, unknown>;
  createdAt: number;
  timeoutSeconds: number;
  // Approval-scope choice (console-only). When isGeneralized is true the
  // card offers Approve Pattern (similar) vs Approve Exact (exact).
  isGeneralized?: boolean;
  exactTarget?: string;
  similarTarget?: string;
  sourceType: string;
}

function resolveBackendChatId(chatId?: string | null): string | undefined {
  if (!chatId) return undefined;
  const resolved = sessionApi.getRealIdForSession(chatId);
  if (resolved) return resolved;
  return /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(
    chatId,
  )
    ? chatId
    : undefined;
}

export function createReconnectRequestPayload(input: {
  backendSessionId: string;
  userId: string;
  channel: string;
  conversationId?: string;
}) {
  return {
    reconnect: true,
    session_id: input.backendSessionId,
    user_id: input.userId,
    channel: input.channel,
    conversation_id: input.conversationId,
  };
}

import WhisperSpeechButton, {
  WhisperSpeechButtonRef,
} from "./components/WhisperSpeechButton";

import {
  toDisplayUrl,
  toStoredName,
  copyText,
  extractCopyableText,
  buildModelError,
  normalizeContentUrls,
  extractUserMessageText,
  extractTextFromMessage,
  clearSubmittedSenderInput,
  getActiveSenderTextarea,
  getSenderTextareaFromTarget,
  setTextareaValue,
  formatMessageTime,
  type CopyableResponse,
  type RuntimeLoadingBridgeApi,
} from "./utils";
import {
  CHAT_BASE_PATH,
  buildChatPath,
  getSessionIdFromPath,
} from "../../utils/sessionRoute";
import { useUploadLimitStore } from "../../stores/uploadLimitStore";
import ChatSenderTabsPanel from "./components/ChatSenderTabsPanel";
import {
  selectTasksForSession,
  useBackgroundTasksStore,
} from "../../stores/backgroundTasksStore";
import {
  hydrateBackgroundTasksForSession,
  stopBackgroundWatchersNotInSession,
} from "../../hooks/useBackgroundTaskWatcher";
import ApprovalLevelToggle from "./components/ApprovalLevelToggle";
import HarnessApprovalToggle from "./components/HarnessApprovalToggle";
import HarnessModelSelector from "./components/HarnessModelSelector";
import { useAgentRunningConfigApprovalLevel } from "../../hooks/useAgentRunningConfigApprovalLevel";
import {
  decideChatResumeAction,
  shouldSyncChatAfterResume,
} from "./chatResumeSync";
import { type ToolExecutionLevel } from "../../utils/approval";
import {
  useMessageQueueStore,
  type QueueItem,
  MAX_QUEUE_SIZE,
  getStoragePrefix,
  withSendLock,
  holdOwnershipLock,
} from "../../stores/messageQueueStore";
import {
  requiresQwenPawModel,
  supportsAgentAttachments,
} from "../../utils/agentBackend";
import { getUserScopedStorageKey } from "../../stores/identityStorage";

// ---------------------------------------------------------------------------
// Background queue sender — keeps sending after ChatPage unmounts.
// Supports multiple concurrent sessions: each session has its own controller.
// ---------------------------------------------------------------------------

const _bgAborts = new Map<string, AbortController>();

function stopBackgroundQueue(queueKey?: string) {
  if (queueKey) {
    const ctrl = _bgAborts.get(queueKey);
    if (ctrl) {
      ctrl.abort();
      _bgAborts.delete(queueKey);
    }
  } else {
    // Stop all (used during full cleanup if needed)
    for (const ctrl of _bgAborts.values()) {
      ctrl.abort();
    }
    _bgAborts.clear();
  }
}

/**
 * Wait until the backend reports the chat is no longer generating
 * (status !== "running"). Used so the next queued item is sent only after
 * the currently running task finishes — preserving order task1 → task2 → 3.
 *
 * Returns true when the chat became idle (or status is unknown / 404, which
 * we treat as idle to avoid blocking the queue forever); false if aborted.
 *
 * @param agentId - If provided, overrides X-Agent-Id in the status request
 *   so that switching agents does not cause a spurious "idle" result.
 */
async function waitForChatIdle(
  chatIdForStatus: string,
  signal: AbortSignal,
  agentId?: string,
): Promise<boolean> {
  if (!chatIdForStatus) return true;
  while (!signal.aborted) {
    try {
      // Use direct fetch with the correct agent ID header to avoid
      // cross-agent status misreads when the user has switched agents.
      const headers = buildAuthHeaders();
      if (agentId) {
        headers["X-Agent-Id"] = agentId;
      }
      const res = await fetch(
        getApiUrl(`/chats/${encodeURIComponent(chatIdForStatus)}`),
        { headers, signal },
      );
      if (!res.ok) return true; // 404 / error → treat as idle
      const chat = await res.json();
      if (chat?.status !== "running") return true;
    } catch {
      // If aborted, return false (not idle) so the caller breaks cleanly.
      if (signal.aborted) return false;
      // Backend unreachable / 404 (e.g. id is still a local timestamp).
      // Treat as idle so we don't block forever.
      return true;
    }
    await new Promise<void>((resolve) => {
      const timer = setTimeout(resolve, 1000);
      const onAbort = () => {
        clearTimeout(timer);
        resolve();
      };
      signal.addEventListener("abort", onAbort, { once: true });
    });
  }
  return false;
}

/**
 * Convert a queue item's attachments array into the content-item format
 * expected by the backend POST body and by patchLastUserMessage.
 */
function buildAttachmentContentItems(
  attachments: Array<{ url: string; name?: string; type?: string }> | undefined,
): Array<{ type: string; [key: string]: unknown }> {
  if (!attachments || attachments.length === 0) return [];
  return attachments.map((a) => {
    const storedUrl = toStoredName(a.url);
    if (a.type?.startsWith("image/")) {
      return { type: "image", image_url: storedUrl };
    }
    if (a.type?.startsWith("video/")) {
      return { type: "video", video_url: storedUrl };
    }
    if (a.type?.startsWith("audio/")) {
      return { type: "audio", data: storedUrl };
    }
    return { type: "file", file_url: storedUrl, file_name: a.name || "file" };
  });
}

/**
 * Clear the SDK Sender's attachment preview by clicking all remove buttons.
 * Deferred to next tick so React commits pending state updates first.
 */
function clearSenderAttachments(): void {
  setTimeout(() => {
    const senderRoot = document
      .querySelector('[class*="sender-header"] [class*="attachment-list-card"]')
      ?.closest('[class*="sender"]');
    if (senderRoot) {
      const removeBtns = senderRoot.querySelectorAll<HTMLButtonElement>(
        'button[class*="attachment-list-card-remove"]',
      );
      removeBtns.forEach((btn) => {
        btn.dispatchEvent(
          new MouseEvent("click", { bubbles: true, cancelable: true }),
        );
      });
    }
  }, 0);
}

async function startBackgroundQueue(
  queueKey: string,
  backendSessionId: string,
  chatIdForStatus: string,
) {
  // Stop only THIS session's previous background sender (if any)
  stopBackgroundQueue(queueKey);
  if (useMessageQueueStore.getState().getQueue(queueKey).length === 0) return;

  const ctrl = new AbortController();
  _bgAborts.set(queueKey, ctrl);

  // Acquire the per-session send lock so only one tab keeps draining the queue
  // after the page unmounts. If the lock is taken, skip background sending.
  await withSendLock(queueKey, async () => {
    while (!ctrl.signal.aborted) {
      // Always read the latest queue from the store: items may have been
      // added / removed / reordered by the user, by other tabs, or by the
      // foreground page mounting again.
      const current = useMessageQueueStore.getState().getQueue(queueKey);
      if (current.length === 0) break;

      // Respect pause/error state.
      const rs = useMessageQueueStore.getState().getRunState(queueKey);
      if (rs === "paused" || rs === "error") break;

      const item = current[0];
      const clientMessageId = item.clientMessageId ?? item.id;

      // Wait until the backend finishes the currently running task before
      // sending the next one. This preserves order task1 → task2 → task3
      // and prevents firing while task1 is still generating.
      const idle = await waitForChatIdle(
        chatIdForStatus,
        ctrl.signal,
        item.agentId,
      );
      if (!idle) break;

      // Mark as sending — visible to other tabs and to the foreground page
      // if the user navigates back. Crucially we do NOT remove the item
      // before the request completes, so a navigate-back during sending
      // still shows the item in the queue.
      useMessageQueueStore
        .getState()
        .setItemStatus(queueKey, item.id, "sending");
      useMessageQueueStore.getState().setCurrentSendingId(item.id);

      // Mirror what foreground customFetch does: cache the in-flight user
      // text in sessionStorage so that when ChatPage re-mounts during
      // generation, sessionApi.patchLastUserMessage can patch THIS user
      // message into history (otherwise the previous turn's stale text
      // would surface, e.g. showing user="2" while task3 is generating).
      if (chatIdForStatus) {
        // Build content items matching the POST body (stored-name format)
        // so patchLastUserMessage can rebuild the user card with attachments.
        const contentItems: Array<{ type: string; [key: string]: unknown }> = [
          { type: "text", text: item.text },
          ...buildAttachmentContentItems(item.attachments),
        ];
        sessionApi.setLastUserMessage(
          chatIdForStatus,
          item.text,
          contentItems,
          clientMessageId,
        );
      }

      let fetchSucceeded = false;
      // True once fetch() has resolved with an HTTP response. For a streaming
      // chat endpoint, this means the backend has already accepted the
      // request and started generating — the backend keeps producing the turn
      // and the foreground SDK's reconnect will pick it up.
      let fetchStarted = false;
      try {
        const authHeaders = buildAuthHeaders();
        const queueAgentId = item.agentId || "default";
        // Use the agent ID captured at enqueue time to prevent cross-agent
        // delivery when the user switches agents after queueing.
        if (item.agentId) {
          authHeaders["X-Agent-Id"] = item.agentId;
        }
        const pendingRequest = withPendingProjectDirectory(
          {
            input: [
              {
                role: "user",
                metadata: {
                  [QWENPAW_CLIENT_MESSAGE_ID_KEY]: clientMessageId,
                },
                content: [
                  { type: "text", text: item.text },
                  ...buildAttachmentContentItems(item.attachments),
                ],
              },
            ],
            session_id: item.backendSessionId || backendSessionId,
            user_id: item.userId || DEFAULT_USER_ID,
            channel: item.channel || DEFAULT_CHANNEL,
            stream: true,
          },
          queueAgentId,
          queueKey,
        );
        // Intentionally do NOT pass ctrl.signal to fetch. This keeps the
        // HTTP connection alive even when the queue loop is aborted (e.g.
        // foreground takes over). The server finishes generating and
        // persists the turn so no message is lost and no re-send occurs.
        const res = await fetch(getApiUrl("/console/chat"), {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            ...authHeaders,
          },
          body: JSON.stringify(pendingRequest.requestBody),
        });

        if (!res.ok) {
          sessionApi.discardLastUserMessage(chatIdForStatus, clientMessageId);
          throw new Error(`HTTP ${res.status}`);
        }
        if (pendingRequest.projectDir) {
          setPendingProjectDirectory(queueAgentId, queueKey, null);
        }
        fetchStarted = true;

        // Drain the stream; reaching `done` means the backend persisted the
        // turn. Only then is it safe to remove the item from the queue.
        const reader = res.body?.getReader();
        if (reader) {
          while (!ctrl.signal.aborted) {
            const r = await reader.read();
            if (r.done) break;
          }
        }
        fetchSucceeded = !ctrl.signal.aborted;
      } catch {
        fetchSucceeded = false;
      }

      if (ctrl.signal.aborted) {
        if (fetchStarted) {
          // Server connection was NOT aborted (no signal on fetch), so the
          // backend will finish generating and persist this turn. Safe to
          // remove — the foreground SDK will see it in history on reconnect.
          useMessageQueueStore.getState().remove(queueKey, item.id);
        } else {
          // Request never made it out (aborted while waiting for status idle
          // or before the response head arrived). Restore to pending so the
          // foreground sender can pick it up.
          useMessageQueueStore
            .getState()
            .setItemStatus(queueKey, item.id, "pending");
        }
        break;
      }

      if (fetchSucceeded) {
        // Backend finished generating → safe to remove from queue.
        useMessageQueueStore.getState().remove(queueKey, item.id);
      } else {
        // Network/HTTP failure: keep the item visible with `failed` status
        // so the user can retry from the queue panel on next visit.
        useMessageQueueStore
          .getState()
          .setItemStatus(
            queueKey,
            item.id,
            "failed",
            i18n.t("chat.queue.sendFailed"),
          );
        break;
      }
    }
    useMessageQueueStore.getState().setCurrentSendingId(null);
  });

  if (_bgAborts.get(queueKey) === ctrl) _bgAborts.delete(queueKey);
}

/**
 * Scan localStorage for all sessions with pending queue items and start
 * background senders for each one (except the excluded foreground session
 * and any that already have an active background sender).
 */
function startAllBackgroundQueues(excludeSessionId?: string) {
  const storagePrefix = getStoragePrefix();
  for (let i = 0; i < localStorage.length; i++) {
    const key = localStorage.key(i);
    if (!key || !key.startsWith(storagePrefix)) continue;
    const sessionId = key.slice(storagePrefix.length);
    if (sessionId === excludeSessionId) continue;
    // Skip sessions already running a background sender
    if (_bgAborts.has(sessionId)) continue;
    try {
      const raw = localStorage.getItem(key);
      if (!raw) continue;
      const parsed = JSON.parse(raw);
      const items: Array<{ status: string }> = Array.isArray(parsed)
        ? parsed
        : parsed.items;
      if (!items || items.length === 0) continue;
      // Only start if there are actionable items
      const hasPending = items.some(
        (it) => it.status === "pending" || it.status === "failed",
      );
      if (!hasPending) continue;
      // Check runState: respect paused queues
      const runState = Array.isArray(parsed) ? "idle" : parsed.runState;
      if (runState === "paused") continue;
    } catch {
      continue;
    }
    // For background sending, resolve the actual session_id the backend
    // expects (chat.session_id), which may differ from the localStorage key
    // (chat.id). Prefer the snapshot stored in the queue item (captured at
    // enqueue time) because the session list may have been cleared after an
    // agent switch. Fall back to sessionApi lookup, then to the key itself.
    let backendSessionId: string | undefined;
    try {
      const raw2 = localStorage.getItem(key);
      if (raw2) {
        const parsed2 = JSON.parse(raw2);
        const itemsArr: Array<{ backendSessionId?: string }> = Array.isArray(
          parsed2,
        )
          ? parsed2
          : parsed2.items;
        backendSessionId = itemsArr?.[0]?.backendSessionId || undefined;
      }
    } catch {
      // ignore
    }
    if (!backendSessionId) {
      backendSessionId = sessionApi.getBackendSessionId(sessionId);
    }
    const chatIdForStatus =
      sessionApi.getRealIdForSession(sessionId) || sessionId;
    startBackgroundQueue(sessionId, backendSessionId, chatIdForStatus);
  }
}

// ---------------------------------------------------------------------------

interface SessionInfo {
  session_id?: string;
  user_id?: string;
  channel?: string;
}

interface CustomWindow extends Window {
  currentSessionId?: string;
  currentUserId?: string;
  currentChannel?: string;
}

declare const window: CustomWindow;

interface CommandSuggestion {
  command: string;
  value: string;
  description: string;
  group?: string;
  icon?: string;
}

interface SlashMenuState {
  open: boolean;
  keyword: string;
  slashStart: number;
  cursor: number;
  left: number;
  bottom: number;
  activeIndex: number;
}

function messageRequestsHistoryClear(message: unknown): boolean {
  if (!message || typeof message !== "object") return false;
  const metadata = (message as Record<string, unknown>).metadata;
  if (!metadata || typeof metadata !== "object") return false;

  const meta = metadata as Record<string, unknown>;
  if (meta.clear_history === true) return true;

  const nested = meta.metadata;
  return (
    !!nested &&
    typeof nested === "object" &&
    (nested as Record<string, unknown>).clear_history === true
  );
}

function payloadRequestsHistoryClear(payload: unknown): boolean {
  if (!payload || typeof payload !== "object") return false;

  const record = payload as Record<string, unknown>;
  const candidates: unknown[] = [];

  if (record.object === "message") {
    candidates.push(record);
  }

  if (record.object === "response" && Array.isArray(record.output)) {
    candidates.push(...record.output);
  }

  return candidates.some(messageRequestsHistoryClear);
}

function payloadCompletesResponse(payload: unknown): boolean {
  if (!payload || typeof payload !== "object") return false;

  const record = payload as Record<string, unknown>;
  return record.object === "response" && record.status === "completed";
}

function renderSuggestionLabel(item: CommandSuggestion) {
  return (
    <div
      className={`${styles.suggestionLabel} ${
        item.description ? "" : styles.suggestionLabelCompact
      }`}
    >
      <div className={styles.suggestionMain}>
        {item.icon && (
          <span className={styles.suggestionIcon}>{item.icon}</span>
        )}
        <span className={styles.suggestionCommand}>{item.command}</span>
        {item.group && (
          <span className={styles.suggestionGroup}>{item.group}</span>
        )}
      </div>
      {item.description && (
        <div className={styles.suggestionDescription}>
          <InlineMarkdown markdown={item.description} />
        </div>
      )}
    </div>
  );
}

interface PersonalLibraryMentionMenuState {
  open: boolean;
  keyword: string;
  mentionStart: number;
  cursor: number;
  left: number;
  bottom: number;
  activeIndex: number;
}

function suggestionValue(insertText: string): string {
  return insertText.replace(/^\/+/, "");
}

function findInlineSlashToken(
  textarea: HTMLTextAreaElement,
): Pick<SlashMenuState, "keyword" | "slashStart" | "cursor"> | null {
  const cursor = textarea.selectionStart ?? 0;
  if (cursor !== textarea.selectionEnd) return null;

  const beforeCursor = textarea.value.slice(0, cursor);
  const match = /(^|\s)\/([^\s]*)$/.exec(beforeCursor);
  if (!match) return null;

  const keyword = match[2].toLowerCase();
  return {
    keyword,
    slashStart: cursor - keyword.length - 1,
    cursor,
  };
}

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const DEFAULT_USER_ID = "default";
const DEFAULT_CHANNEL = "console";
const WIDE_MODE_STORAGE_KEY = "qwenpaw_chat_wide_mode";

// Stable fallback so an absent queue entry doesn't produce a fresh array
// reference on every render (which would invalidate the options memo).
const EMPTY_QUEUE: QueueItem[] = [];

function sanitizeHeadlinePayload(
  node: unknown,
  streamState: HeadlineStreamFilterState,
): void {
  if (!node || typeof node !== "object") return;
  if (!Array.isArray(node)) {
    const record = node as Record<string, unknown>;
    if (typeof record.delta === "string") {
      record.delta = filterHeadlineDelta(record.delta, streamState);
    }
  }
  stripScrollHeadlineTextBlocks(node);
}

// ---------------------------------------------------------------------------
// Custom hooks
// ---------------------------------------------------------------------------

/** Handle IME composition events to prevent premature Enter key submission. */
function useIMEComposition(isChatActive: () => boolean) {
  const isComposingRef = useRef(false);

  useEffect(() => {
    const handleCompositionStart = () => {
      if (!isChatActive()) return;
      isComposingRef.current = true;
    };

    const handleCompositionEnd = () => {
      if (!isChatActive()) return;
      // Small delay for Safari on macOS, which fires keydown after
      // compositionend within the same event loop tick.  Keep this as
      // short as possible so fast typists who hit Space+Enter in quick
      // succession are not blocked.
      setTimeout(() => {
        isComposingRef.current = false;
      }, 50);
    };

    const suppressImeEnter = (e: KeyboardEvent) => {
      if (!isChatActive()) return;
      const target = e.target as HTMLElement;
      if (target?.tagName === "TEXTAREA" && e.key === "Enter" && !e.shiftKey) {
        // e.isComposing is the standard flag; isComposingRef covers the
        // post-compositionend grace period needed by Safari.
        if (isComposingRef.current || (e as any).isComposing) {
          e.stopPropagation();
          e.stopImmediatePropagation();
          e.preventDefault();
          return false;
        }
      }
    };

    document.addEventListener("compositionstart", handleCompositionStart, true);
    document.addEventListener("compositionend", handleCompositionEnd, true);
    // Listen on both keydown (Safari) and keypress (legacy) in capture phase.
    document.addEventListener("keydown", suppressImeEnter, true);
    document.addEventListener("keypress", suppressImeEnter, true);

    return () => {
      document.removeEventListener(
        "compositionstart",
        handleCompositionStart,
        true,
      );
      document.removeEventListener(
        "compositionend",
        handleCompositionEnd,
        true,
      );
      document.removeEventListener("keydown", suppressImeEnter, true);
      document.removeEventListener("keypress", suppressImeEnter, true);
    };
  }, [isChatActive]);

  return isComposingRef;
}

function sortByOrder<T extends { item: { order?: number } }>(arr: T[]): T[] {
  return arr
    .slice()
    .sort((a, b) => (a.item.order ?? 100) - (b.item.order ?? 100));
}

/** Fetch and track multimodal capabilities for the active model. */
function useMultimodalCapabilities(
  refreshKey: number,
  locationPathname: string,
  _isChatActive: () => boolean,
  selectedAgent: string,
  usesQwenPawBackend: boolean,
) {
  const [multimodalCaps, setMultimodalCaps] = useState<{
    supportsMultimodal: boolean;
    supportsImage: boolean;
    supportsVideo: boolean;
  }>({ supportsMultimodal: false, supportsImage: false, supportsVideo: false });

  const updateCapsIfChanged = useCallback(
    (next: {
      supportsMultimodal: boolean;
      supportsImage: boolean;
      supportsVideo: boolean;
    }) => {
      setMultimodalCaps((prev) =>
        prev.supportsMultimodal === next.supportsMultimodal &&
        prev.supportsImage === next.supportsImage &&
        prev.supportsVideo === next.supportsVideo
          ? prev
          : next,
      );
    },
    [],
  );

  const fetchMultimodalCaps = useCallback(async () => {
    const noCaps = {
      supportsMultimodal: false,
      supportsImage: false,
      supportsVideo: false,
    };
    if (!usesQwenPawBackend) {
      updateCapsIfChanged(noCaps);
      return;
    }
    const context = currentModelContext(locationPathname);
    try {
      const [catalog, activeModels] = await Promise.all([
        modelCatalogApi.list(selectedAgent),
        loadConversationModel(),
      ]);
      if (!isCurrentModelContext(context)) return;
      const activeProviderId = activeModels?.active_llm?.provider_id;
      const activeModelId = activeModels?.active_llm?.model;
      if (!activeProviderId || !activeModelId) {
        updateCapsIfChanged(noCaps);
        return;
      }
      const model = catalog.models.find(
        (m) => m.provider_id === activeProviderId && m.model === activeModelId,
      );
      updateCapsIfChanged({
        supportsMultimodal: Boolean(
          model?.supports_image || model?.supports_video,
        ),
        supportsImage: model?.supports_image ?? false,
        supportsVideo: model?.supports_video ?? false,
      });
    } catch {
      if (isCurrentModelContext(context)) updateCapsIfChanged(noCaps);
    }
  }, [
    selectedAgent,
    locationPathname,
    updateCapsIfChanged,
    usesQwenPawBackend,
  ]);

  // Fetch caps on mount and whenever refreshKey changes
  useEffect(() => {
    fetchMultimodalCaps();
  }, [fetchMultimodalCaps, refreshKey]);

  // Re-sync caps only when navigating FROM a non-chat page back to chat.
  // Do NOT re-fetch when switching between sessions (e.g. /chat/A → /chat/B)
  // because the agent/model config hasn't changed — avoids unnecessary
  // models + active API calls on every session switch.
  const prevChatPathRef = useRef(locationPathname);
  useEffect(() => {
    const prev = prevChatPathRef.current;
    prevChatPathRef.current = locationPathname;
    const wasOutsideChat = !prev.startsWith("/chat");
    const isNowInChat = locationPathname.startsWith("/chat");
    if (wasOutsideChat && isNowInChat) {
      fetchMultimodalCaps();
    }
  }, [locationPathname, fetchMultimodalCaps]);

  return { multimodalCaps, fetchMultimodalCaps };
}

function useMessageHistoryNavigation(
  chatRef: React.RefObject<IAgentScopeRuntimeWebUIRef | null>,
  isChatActive: () => boolean,
  isComposingRef: React.RefObject<boolean>,
) {
  const historyIndexRef = useRef<number>(-1);
  const draftRef = useRef<string>("");

  /** Cached user messages to avoid re-computing on every keydown */
  const userMessagesCacheRef = useRef<string[]>([]);
  const cachedMessageCountRef = useRef<number>(0);

  const getUserMessagesWithText = useCallback((): string[] => {
    if (!chatRef.current?.messages?.getMessages) return [];

    const allMessages = chatRef.current.messages.getMessages();
    if (!Array.isArray(allMessages)) return [];

    const currentCount = allMessages.length;
    if (
      userMessagesCacheRef.current.length > 0 &&
      cachedMessageCountRef.current === currentCount
    ) {
      return userMessagesCacheRef.current;
    }

    const userMessages = allMessages
      .filter((msg) => msg.role === "user")
      .map((msg) => extractTextFromMessage(msg))
      .filter((text) => text.trim().length > 0);

    userMessagesCacheRef.current = userMessages;
    cachedMessageCountRef.current = currentCount;

    return userMessages;
  }, [chatRef]);

  interface MessageResult {
    index: number;
    text: string;
  }

  const findMessageInDirection = (
    messages: string[],
    startIndex: number,
    direction: 1 | -1,
  ): MessageResult | null => {
    const MAX_LOOKUP = 100;
    let lookupIndex = startIndex;
    let steps = 0;

    while (
      lookupIndex >= 0 &&
      lookupIndex < messages.length &&
      steps < MAX_LOOKUP
    ) {
      const messageText = messages[messages.length - 1 - lookupIndex];
      if (messageText) {
        return { index: lookupIndex, text: messageText };
      }
      lookupIndex += direction;
      steps += 1;
    }

    return null;
  };

  const isSuggestionPopupOpen = (textarea: HTMLTextAreaElement): boolean =>
    textarea.value.startsWith("/");

  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (!isChatActive()) return;
      if (e.key !== "ArrowUp" && e.key !== "ArrowDown") return;

      const textarea = getSenderTextareaFromTarget(e.target);
      if (!textarea) return;
      if (isComposingRef.current || (e as any).isComposing) return;
      if (e.ctrlKey || e.metaKey || e.altKey) return;

      const hasSelection = textarea.selectionStart !== textarea.selectionEnd;
      if (hasSelection) return;

      const userMessages = getUserMessagesWithText();

      if (e.key === "ArrowUp") {
        if (isSuggestionPopupOpen(textarea)) return;

        const cursorPosition = textarea.selectionStart || 0;
        const textBeforeCursor = textarea.value.substring(0, cursorPosition);
        const lineBreaks = textBeforeCursor.split("\n").length - 1;
        if (lineBreaks > 0) return;

        if (userMessages.length === 0) return;

        if (historyIndexRef.current === -1) {
          draftRef.current = textarea.value;
        }

        const startIndex = historyIndexRef.current + 1;
        const messageText = findMessageInDirection(userMessages, startIndex, 1);

        if (messageText) {
          e.preventDefault();
          historyIndexRef.current = messageText.index;
          setTextareaValue(textarea, messageText.text);
        }
      } else if (e.key === "ArrowDown") {
        if (historyIndexRef.current < 0) return;

        const cursorPosition = textarea.selectionStart || 0;
        const textAfterCursor = textarea.value.substring(cursorPosition);
        if (textAfterCursor.includes("\n")) return;

        const startIndex = historyIndexRef.current - 1;
        const messageText = findMessageInDirection(
          userMessages,
          startIndex,
          -1,
        );

        if (messageText) {
          e.preventDefault();
          historyIndexRef.current = messageText.index;
          setTextareaValue(textarea, messageText.text);
        } else {
          e.preventDefault();
          historyIndexRef.current = -1;
          setTextareaValue(textarea, draftRef.current);
        }
      }
    };

    const handleFocus = (e: FocusEvent) => {
      if (getSenderTextareaFromTarget(e.target)) {
        historyIndexRef.current = -1;
        draftRef.current = "";
      }
    };

    document.addEventListener("keydown", handleKeyDown, true);
    document.addEventListener("focusin", handleFocus, true);

    return () => {
      document.removeEventListener("keydown", handleKeyDown, true);
      document.removeEventListener("focusin", handleFocus, true);
    };
  }, [isChatActive, isComposingRef, getUserMessagesWithText]);
}

// ---------------------------------------------------------------------------
// Chat input draft persistence
// ---------------------------------------------------------------------------

const DRAFT_STORAGE_KEY_PREFIX = "qwenpaw_chat_input_draft";
let draftSuppressed = false;

function getDraftStorageKey(agentId?: string): string {
  const baseKey = agentId
    ? `${DRAFT_STORAGE_KEY_PREFIX}_${agentId}`
    : DRAFT_STORAGE_KEY_PREFIX;
  return getUserScopedStorageKey(baseKey);
}

interface DraftState {
  value: string;
  selectionStart: number;
  selectionEnd: number;
}

function useChatInputDraft(isChatActive: () => boolean, agentId?: string) {
  const storageKey = getDraftStorageKey(agentId);

  useEffect(() => {
    if (!isChatActive()) return;

    let saveTimer: ReturnType<typeof setTimeout> | null = null;

    const getTextarea = (): HTMLTextAreaElement | null => {
      const sender = document.querySelector('[class*="sender"]');
      return sender?.querySelector("textarea") as HTMLTextAreaElement | null;
    };

    const saveDraft = (textarea: HTMLTextAreaElement) => {
      const draft: DraftState = {
        value: textarea.value,
        selectionStart: textarea.selectionStart,
        selectionEnd: textarea.selectionEnd,
      };
      if (draft.value) {
        localStorage.setItem(storageKey, JSON.stringify(draft));
      } else {
        localStorage.removeItem(storageKey);
      }
    };

    const handleInput = (e: Event) => {
      const target = e.target as HTMLElement;
      if (target?.tagName !== "TEXTAREA") return;
      if (!target?.closest('[class*="sender"]')) return;

      if (saveTimer) clearTimeout(saveTimer);
      saveTimer = setTimeout(() => {
        saveDraft(target as HTMLTextAreaElement);
      }, 300);

      // Minimal loop mode detection: sync indicator with availableModes
      const val = (target as HTMLTextAreaElement).value.trimStart();
      const modes = useLoopStore.getState().availableModes;
      const match = modes.find((m) => {
        if (!m.slash_command) return false;
        const prefix = `/${m.slash_command}`;
        // Match "/cmd" or "/cmd " exactly, avoid "/cmdxxx"
        return val === prefix || val.startsWith(`${prefix} `);
      });
      if (match) useLoopStore.getState().setSelectedMode(match.id);
    };

    // Restore draft on mount with polling for textarea readiness
    let restoreAttempts = 0;
    const maxRestoreAttempts = 20;
    const restoreInterval = setInterval(() => {
      restoreAttempts++;
      const textarea = getTextarea();
      if (textarea) {
        clearInterval(restoreInterval);
        const raw = localStorage.getItem(storageKey);
        if (raw) {
          try {
            const draft: DraftState = JSON.parse(raw);
            if (draft.value) {
              setTextareaValue(textarea, draft.value);
              requestAnimationFrame(() => {
                textarea.selectionStart = draft.selectionStart;
                textarea.selectionEnd = draft.selectionEnd;
              });
            }
          } catch {
            // Ignore malformed data
          }
        }
      } else if (restoreAttempts >= maxRestoreAttempts) {
        clearInterval(restoreInterval);
      }
    }, 100);

    document.addEventListener("input", handleInput, true);

    return () => {
      clearInterval(restoreInterval);
      if (saveTimer) clearTimeout(saveTimer);
      document.removeEventListener("input", handleInput, true);

      // Final save on unmount (skip if message was just sent)
      if (!draftSuppressed) {
        const textarea = getTextarea();
        if (textarea) {
          saveDraft(textarea);
        }
      }
      draftSuppressed = false;
    };
  }, [isChatActive, storageKey]);
}

function RuntimeLoadingBridge({
  bridgeRef,
  onLoadingChange,
}: {
  bridgeRef: { current: RuntimeLoadingBridgeApi | null };
  onLoadingChange?: (loading: boolean | string) => void;
}) {
  const { loading, setLoading, getLoading } = useChatAnywhereInput(
    (value) =>
      ({
        loading: value.loading,
        setLoading: value.setLoading,
        getLoading: value.getLoading,
      }) as { loading: boolean | string } & RuntimeLoadingBridgeApi,
  );

  useEffect(() => {
    if (!setLoading || !getLoading) {
      bridgeRef.current = null;
      return;
    }

    bridgeRef.current = {
      setLoading,
      getLoading,
    };

    return () => {
      if (bridgeRef.current?.setLoading === setLoading) {
        bridgeRef.current = null;
      }
    };
  }, [getLoading, setLoading, bridgeRef]);

  useEffect(() => {
    onLoadingChange?.(loading ?? false);
  }, [loading, onLoadingChange]);

  return null;
}

function RuntimeReadOnlyBridge({ readOnly }: { readOnly: boolean }) {
  const { setDisabled } = useChatAnywhereInput(
    (value) =>
      ({ setDisabled: value.setDisabled }) as {
        setDisabled?: (disabled: boolean) => void;
      },
  );
  const { currentSessionId } = useChatAnywhereSessionsState();

  useEffect(() => {
    if (!setDisabled) return;
    const timer = window.setTimeout(() => setDisabled(readOnly), 0);
    return () => {
      window.clearTimeout(timer);
      setDisabled(false);
    };
  }, [currentSessionId, readOnly, setDisabled]);

  return null;
}

const timestampStyle: React.CSSProperties = {
  fontSize: 12,
  color: "var(--ant-color-text-quaternary)",
  whiteSpace: "nowrap",
};

const HISTORY_PANEL_STORAGE_KEY = "qwenpaw_history_panel_open";

/**
 * Temporary local session ids (created before the first message is sent) are
 * not real backend sessions and must never be used for URL restore, session
 * preference, or persistence.
 */
const isLocalTimestampId = (id: string | null | undefined): boolean =>
  !!id && /^\d+-[a-z0-9]+$/.test(id);

export default function ChatPage() {
  const canManageModels = useAuthStore(
    (state) =>
      state.mode !== "multi_user" || state.user?.platform_role === "admin",
  );
  const { t, i18n } = useTranslation();
  const navigate = useNavigate();
  const location = useLocation();
  const { isDark } = useTheme();
  const { selectedAgent, agents } = useAgentStore();
  const historicalReadOnly = isAgentHistoricalReadOnly(agents, selectedAgent);
  const chatId = useMemo(
    () => getSessionIdFromPath(location.pathname),
    [location.pathname],
  );
  const sessions = useSessionListStore((state) => state.sessions);
  const currentSession = useMemo(
    () =>
      sessions.find(
        (session) => session.id === chatId || session.realId === chatId,
      ),
    [chatId, sessions],
  );
  const conversationReadOnly = isConversationReadOnly({
    access_role: currentSession?.accessRole,
    read_only: currentSession?.readOnly,
  });
  const chatReadOnly = historicalReadOnly || conversationReadOnly;
  const publicationVersion = currentSession?.meta?.publication_version;
  const lockedPublicationModel = currentSession?.meta?.locked_model as
    | { provider_id?: string; model?: string }
    | undefined;
  const isPublicationConversation =
    typeof publicationVersion === "string" &&
    Boolean(lockedPublicationModel?.provider_id && lockedPublicationModel?.model);
  const queueSessionId = chatId ?? sessionApi.lastActiveChatId ?? "new";
  const backendChatId = resolveBackendChatId(chatId);
  const pendingProjectDir = backendChatId
    ? undefined
    : getPendingProjectDirectory(selectedAgent, queueSessionId) ?? undefined;
  const sessionScope = useMemo<
    Extract<FilesWorkspaceScope, { kind: "session" }>
  >(
    () => ({
      kind: "session",
      agentId: selectedAgent,
      sessionId: queueSessionId,
      chatId: backendChatId,
      projectDirOverride: pendingProjectDir,
    }),
    [backendChatId, pendingProjectDir, queueSessionId, selectedAgent],
  );
  const currentSessionFilesScopeKey = sessionFilesScopeKey(
    selectedAgent,
    queueSessionId,
  );
  const filesDrawerState = useSessionFilesDrawer(currentSessionFilesScopeKey);
  const dispatchFilesDrawer = useCallback(
    (event: FilesDrawerEvent) => {
      useFilesSurfaceStore
        .getState()
        .dispatchSession(currentSessionFilesScopeKey, event);
    },
    [currentSessionFilesScopeKey],
  );
  const filesWorkspaceOpen = filesDrawerState.kind === "workspace";
  const toggleFilesWorkspace = useCallback(() => {
    const current = useFilesSurfaceStore.getState().sessionDrawers[
      currentSessionFilesScopeKey
    ] ?? { kind: "closed" as const };
    if (current.kind === "workspace") {
      dispatchFilesDrawer({ type: "CLOSE" });
      return;
    }
    if (current.kind === "preview") {
      dispatchFilesDrawer({ type: "EXPAND_WORKSPACE" });
      return;
    }
    dispatchFilesDrawer({
      type: "OPEN_WORKSPACE",
      trigger: null,
    });
  }, [currentSessionFilesScopeKey, dispatchFilesDrawer]);

  useEffect(() => {
    const openPreview = (event: Event) => {
      const customEvent = event as CustomEvent<{
        target: FileTarget;
        trigger?: HTMLElement | null;
      }>;
      dispatchFilesDrawer({
        type: "OPEN_PREVIEW",
        target: customEvent.detail.target,
        trigger: customEvent.detail.trigger ?? null,
      });
    };
    window.addEventListener("qwenpaw:open-file-preview", openPreview);
    return () =>
      window.removeEventListener("qwenpaw:open-file-preview", openPreview);
  }, [dispatchFilesDrawer]);

  const handleInternalFileLink = useCallback(
    (event: React.MouseEvent<HTMLDivElement>) => {
      if (handleArtifactDownloadLink(event)) return;
      const element = event.target;
      if (!(element instanceof Element)) return;
      const anchor = element.closest<HTMLAnchorElement>("a[href]");
      if (!anchor) return;
      const target = parseInternalFileLink(anchor.getAttribute("href") ?? "");
      if (!target) return;
      event.preventDefault();
      event.stopPropagation();
      dispatchFilesDrawer({
        type: "OPEN_PREVIEW",
        target,
        trigger: anchor,
      });
    },
    [dispatchFilesDrawer],
  );

  // Wide mode toggle: expand chat content to full available width
  const [isWideMode, setIsWideMode] = useState(() => {
    try {
      return localStorage.getItem(WIDE_MODE_STORAGE_KEY) === "true";
    } catch {
      return false;
    }
  });
  const toggleWideMode = useCallback(() => {
    setIsWideMode((prev) => {
      const next = !prev;
      try {
        if (next) {
          localStorage.setItem(WIDE_MODE_STORAGE_KEY, "true");
        } else {
          localStorage.removeItem(WIDE_MODE_STORAGE_KEY);
        }
      } catch {
        // storage unavailable
      }
      return next;
    });
  }, []);

  const [showModelPrompt, setShowModelPrompt] = useState(false);
  const [rateLimitAlternatives, setRateLimitAlternatives] = useState<
    Array<{
      provider_id: string;
      provider_name: string;
      model_id: string;
      model_name: string;
    }>
  >([]);
  const selectedAgentInfo = agents.find((agent) => agent.id === selectedAgent);
  const selectedAgentBackend = selectedAgentInfo?.backend ?? "qwenpaw";
  const backendCapabilities = selectedAgentInfo?.backend_capabilities;
  const usesQwenPawBackend = requiresQwenPawModel(selectedAgentBackend);
  const loopAvailableModes = useLoopStore((state) => state.availableModes);
  const approvalPresets = backendCapabilities?.approval_presets ?? [];
  const supportsAttachments = supportsAgentAttachments(
    selectedAgentBackend,
    backendCapabilities,
  );
  const { toolRenderConfig } = usePlugins();
  const extScalar = useChatScalarSnapshot();
  const extLists = useChatListSnapshot();
  const [refreshKey, setRefreshKey] = useState(0);
  const runtimeLoadingBridgeRef = useRef<RuntimeLoadingBridgeApi | null>(null);
  const headlineStreamFilterRef = useRef<HeadlineStreamFilterState>(
    createHeadlineFilterState(),
  );
  // Use sessionApi.lastActiveChatId when available to avoid "new" collision
  const queueSessionIdRef = useRef(queueSessionId);
  queueSessionIdRef.current = queueSessionId;
  const messageQueue =
    useMessageQueueStore((s) => s.queues[queueSessionId]) ?? EMPTY_QUEUE;
  const messageQueueRef = useRef(messageQueue);
  messageQueueRef.current = messageQueue;
  const autoSendTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const prevQueueLenRef = useRef(messageQueue.length);

  const sessionApprovalLevelRef = useRef<ToolExecutionLevel | null>(null);
  const backendControlsRef = useRef<Record<string, unknown>>({});
  const runningConfigApprovalLevel = useAgentRunningConfigApprovalLevel();

  // Track pending attachments for queue support
  const pendingFileListRef = useRef<
    {
      uid: string;
      name: string;
      url: string;
      thumbUrl?: string;
      type?: string;
      size?: number;
    }[]
  >([]);

  // Build SDK fileList from QueueItem.attachments
  // SDK reads file.response.url for image_url / file_url (see AgentScopeRuntimeRequestBuilder)
  const buildFileList = useCallback(
    (item: {
      attachments?: {
        url: string;
        name?: string;
        type?: string;
        size?: number;
      }[];
    }) => {
      if (!item.attachments || item.attachments.length === 0) return undefined;
      return item.attachments.map((a) => ({
        uid: a.url,
        name: a.name ?? "file",
        url: a.url,
        thumbUrl: a.type?.startsWith("image/") ? a.url : undefined,
        status: "done" as const,
        response: { url: a.url },
        size: a.size,
        type: a.type,
      }));
    },
    [],
  );

  // Single-tab ownership: only one tab per conversation may send. Other tabs
  // are queue-only (input is enqueued instead of submitted). The owner is
  // determined by an exclusive Web Lock keyed by sessionId; when the owner
  // tab closes, another tab acquires the lock and becomes the owner.
  const [isOwner, setIsOwner] = useState(false);
  const [ownershipResolved, setOwnershipResolved] = useState(false);
  const isOwnerRef = useRef(false);
  isOwnerRef.current = isOwner;
  useEffect(() => {
    setIsOwner(false);
    setOwnershipResolved(false);
    const ctrl = new AbortController();
    void holdOwnershipLock(
      queueSessionId,
      () => {
        setIsOwner(true);
        setOwnershipResolved(true);
      },
      ctrl.signal,
    );
    // If the lock callback never fires (e.g. another tab holds it), resolve
    // after a short delay so the non-owner Alert appears without flashing.
    const fallbackTimer = setTimeout(() => {
      setOwnershipResolved(true);
    }, 300);
    return () => {
      ctrl.abort();
      clearTimeout(fallbackTimer);
    };
  }, [queueSessionId]);

  const syncLoopModeStatus = useCallback(() => {
    const backendSessionId =
      window.currentSessionId ||
      (queueSessionId !== "new"
        ? sessionApi.getBackendSessionId(queueSessionId)
        : "");
    return fetchActiveLoopMode({
      chatId,
      sessionId: backendSessionId,
    });
  }, [chatId, queueSessionId]);

  useEffect(() => {
    const controller = new AbortController();
    useLoopStore.getState().resetSessionMode();
    void fetchAvailableLoopModes(controller.signal);
    if (chatId) {
      void fetchActiveLoopMode({
        chatId,
        sessionId:
          window.currentSessionId || sessionApi.getBackendSessionId(chatId),
        signal: controller.signal,
      });
    }
    return () => controller.abort();
  }, [chatId, selectedAgent]);

  // Whether this tab is confirmed to be a non-owner (queue-only) tab.
  // Stays false until ownership check completes, preventing a flash of
  // the "other tab is owner" banner on every session switch.
  const isQueueOnlyTab = ownershipResolved && !isOwner;
  const hasQueueItems = messageQueue.length > 0;

  // Backend session id for the background-task panel (list API + store filter).
  const [bgBackendSessionId, setBgBackendSessionId] = useState("");
  // Count only this session's bg tasks so other sessions don't force empty
  // sender chrome / layout padding.
  const bgTaskCount = useBackgroundTasksStore(
    (s) => selectTasksForSession(s.tasks, bgBackendSessionId).length,
  );
  const showSenderBeforeUI = isQueueOnlyTab || hasQueueItems || bgTaskCount > 0;

  // On session load / switch: prune other sessions' watchers, then rehydrate
  // still-offloaded tools from GET /tool-calls/{session_id}.
  useEffect(() => {
    // Invalidate immediately so A→B never briefly filters/shows A's tasks.
    setBgBackendSessionId("");

    if (!queueSessionId || queueSessionId === "new") {
      stopBackgroundWatchersNotInSession("");
      return;
    }

    let cancelled = false;

    const resolveBackendSessionId = async (): Promise<string> => {
      // Prefer sessionApi mapping; do not trust window.currentSessionId here —
      // it can briefly still hold the previous session after a switch.
      for (let i = 0; i < 20 && !cancelled; i++) {
        const mapped = sessionApi.getBackendSessionId(queueSessionId);
        const knownInList =
          mapped !== queueSessionId ||
          sessionApi.getRealIdForSession(queueSessionId) != null;
        if (mapped && knownInList) return mapped;
        await new Promise((r) => setTimeout(r, 250));
      }
      return sessionApi.getBackendSessionId(queueSessionId) || queueSessionId;
    };

    void (async () => {
      const backendSid = await resolveBackendSessionId();
      if (cancelled || !backendSid) return;
      setBgBackendSessionId(backendSid);
      stopBackgroundWatchersNotInSession(backendSid);
      await hydrateBackgroundTasksForSession(backendSid);
    })();

    return () => {
      cancelled = true;
      // Drop stale binding as soon as queueSessionId changes / unmounts.
      setBgBackendSessionId("");
    };
  }, [queueSessionId]);

  const scheduleNextSend = useCallback(() => {
    if (autoSendTimerRef.current) clearTimeout(autoSendTimerRef.current);
    autoSendTimerRef.current = setTimeout(() => {
      autoSendTimerRef.current = null;
      if (chatLoadingRef.current) return;
      // Only the owner tab is allowed to actually send.
      if (!isOwnerRef.current) return;
      // Respect pause/error state — read fresh from store
      const state = useMessageQueueStore.getState().getRunState(queueSessionId);
      if (state === "paused" || state === "error") return;
      const q = messageQueueRef.current;
      if (q.length === 0) return;
      const next = q[0];
      // Acquire the per-session send lock so concurrent tabs don't both fire
      // the same item. If another tab holds the lock, drop this attempt; the
      // cross-tab broadcast will refresh our queue and the next loading→idle
      // transition will retry.
      void withSendLock(queueSessionId, () => {
        // Re-check: another tab may have already removed this item via
        // broadcast, or a session switch may have happened.
        const fresh = useMessageQueueStore.getState().getQueue(queueSessionId);
        if (fresh.length === 0 || fresh[0].id !== next.id) return;
        useMessageQueueStore.getState().setCurrentSendingId(next.id);
        useMessageQueueStore.getState().remove(queueSessionId, next.id);
        // Force-set window.currentSessionId from the queue item's snapshot
        // so customFetch uses the correct session_id, even if the global
        // was overwritten by a recent agent switch.
        if (next.backendSessionId) {
          (
            window as unknown as { currentSessionId?: string }
          ).currentSessionId = next.backendSessionId;
        }
        chatRef.current?.input.submit({
          query: beginLoopModeSubmission(next.text),
          fileList: buildFileList(next),
        });
      });
    }, 500);
  }, [queueSessionId, buildFileList]);

  // Reload queue when switching sessions or on first mount
  const prevQueueSessionIdRef = useRef<string | null>(null);
  useEffect(() => {
    const isFirstMount = prevQueueSessionIdRef.current === null;
    const isSameSession = prevQueueSessionIdRef.current === queueSessionId;

    if (!isFirstMount && isSameSession) return;

    // Cancel any pending auto-send from the old session
    if (autoSendTimerRef.current) {
      clearTimeout(autoSendTimerRef.current);
      autoSendTimerRef.current = null;
    }
    prevChatLoadingRef.current = false;
    // Keep prevQueueLenRef at current value to prevent auto-send effect from
    // seeing a false 0→N transition on stale messageQueue in the same render.
    prevQueueLenRef.current = messageQueue.length;

    // If we just migrated "new" → queueSessionId, the in-memory store already
    // holds the authoritative items. Skip loadFromStorage which would no-op
    // (storage already has the data) but also don't double-process.
    const migratedTo = useMessageQueueStore.getState().consumeMigratedTo();
    if (migratedTo !== queueSessionId) {
      useMessageQueueStore.getState().loadFromStorage(queueSessionId);
    }

    prevQueueSessionIdRef.current = queueSessionId;

    // If the new session has queued items, schedule auto-send after React
    // updates messageQueueRef (next render). The 500ms delay ensures refs
    // are current and the session-switch is fully settled.
    const newQueue = useMessageQueueStore.getState().getQueue(queueSessionId);
    if (newQueue.length > 0) {
      scheduleNextSend();
    }
  }, [queueSessionId, scheduleNextSend]);
  const [chatLoading, setChatLoading] = useState<boolean | string>(false);
  const chatLoadingRef = useRef<boolean | string>(false);
  chatLoadingRef.current = chatLoading;
  const prevChatLoadingRef = useRef<boolean | string>(false);
  const { message } = useAppMessage();
  const { approvals, setApprovals } = useApprovalContext();
  const [approvalRequests, setApprovalRequests] = useState<
    Map<string, ApprovalMessageData>
  >(new Map());
  const [planEnabled, setPlanEnabled] = useState(false);
  const [slashCatalog, setSlashCatalog] = useState<SlashCatalogItem[]>([]);
  const [slashMenu, setSlashMenu] = useState<SlashMenuState>({
    open: false,
    keyword: "",
    slashStart: 0,
    cursor: 0,
    left: 0,
    bottom: 0,
    activeIndex: 0,
  });
  const slashTextareaRef = useRef<HTMLTextAreaElement | null>(null);
  const slashMenuRef = useRef<HTMLDivElement | null>(null);
  const slashItemRefs = useRef<Array<HTMLButtonElement | null>>([]);
  const [personalLibraryDocuments, setPersonalLibraryDocuments] = useState<
    ChatFileCandidate[]
  >([]);
  const [mentionMenu, setMentionMenu] =
    useState<PersonalLibraryMentionMenuState>({
      open: false,
      keyword: "",
      mentionStart: 0,
      cursor: 0,
      left: 0,
      bottom: 0,
      activeIndex: 0,
    });
  const mentionTextareaRef = useRef<HTMLTextAreaElement | null>(null);
  const isChatActiveRef = useRef(false);
  isChatActiveRef.current =
    location.pathname === "/" ||
    location.pathname.startsWith("/chat") ||
    location.pathname.startsWith("/coding");

  const isChatActive = useCallback(() => isChatActiveRef.current, []);
  const { mode: sidebarMode } = useSidebarModeStore();
  const isFullMode = sidebarMode === "full";

  // On mobile viewports the right-side history panel should always be
  // available regardless of the sidebar mode setting.
  const isMobile = useIsMobile();
  const prefersReducedMotion = useReducedMotion();
  const effectiveIsFullMode = isFullMode || isMobile;

  // Right-side history panel state
  const [historyPanelOpen, setHistoryPanelOpen] = useState(() => {
    try {
      return localStorage.getItem(HISTORY_PANEL_STORAGE_KEY) === "true";
    } catch {
      return false;
    }
  });
  const toggleHistoryPanel = useCallback(() => {
    setHistoryPanelOpen((prev) => {
      const next = !prev;
      try {
        if (next) {
          localStorage.setItem(HISTORY_PANEL_STORAGE_KEY, "true");
        } else {
          localStorage.removeItem(HISTORY_PANEL_STORAGE_KEY);
        }
      } catch {
        // storage unavailable
      }
      return next;
    });
  }, []);

  useEffect(() => {
    let cancelled = false;
    planApi
      .getPlanConfig()
      .then((cfg) => {
        if (!cancelled) setPlanEnabled(cfg.enabled);
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, [selectedAgent]);

  useEffect(() => {
    let cancelled = false;
    setPersonalLibraryDocuments([]);
    listChatFileCandidates(chatId)
      .then((documents) => {
        if (cancelled) return;
        setPersonalLibraryDocuments(documents);
      })
      .catch(() => {
        if (!cancelled) setPersonalLibraryDocuments([]);
      });
    return () => {
      cancelled = true;
    };
  }, [selectedAgent, chatId]);

  const slashSuggestions = useMemo<CommandSuggestion[]>(() => {
    const catalogItems = slashCatalog
      .filter(
        (item) =>
          item.type === "command" ||
          item.type === "skill" ||
          item.type.startsWith("mcp_"),
      )
      .map((item) => ({
        command: item.command,
        value: suggestionValue(item.insertText),
        description: item.description || item.group || "",
        group: item.group,
        icon: item.icon,
      }));

    // Keep legacy host/backend and loop-mode shortcuts in the same custom
    // menu. The SDK sender must not receive these or it renders a duplicate
    // centered popup for the same slash input.
    const extraItems: CommandSuggestion[] = [
      {
        command: "/new",
        value: "new",
        description: "",
        group: "Commands",
      },
      ...(usesQwenPawBackend
        ? []
        : (backendCapabilities?.commands ?? []).map((item) => ({
            command: `/${item.name}`,
            value: item.name,
            description: item.description || "",
            group: "Commands",
          }))),
      ...(usesQwenPawBackend
        ? buildLoopSlashSuggestions(
            loopAvailableModes,
            new Set(catalogItems.map((item) => item.value)),
            t,
            i18n.language,
          )
        : []),
    ];

    const seen = new Set<string>();
    return [...catalogItems, ...extraItems].filter((item) => {
      if (seen.has(item.value)) return false;
      seen.add(item.value);
      return true;
    });
  }, [
    backendCapabilities?.commands,
    i18n.language,
    loopAvailableModes,
    slashCatalog,
    t,
    usesQwenPawBackend,
  ]);

  const filteredSlashSuggestions = useMemo(() => {
    if (!slashMenu.open) return [];
    if (!slashMenu.keyword) return slashSuggestions;
    return slashSuggestions.filter((item) => {
      const haystack = `${item.command} ${item.description} ${
        item.group ?? ""
      }`.toLowerCase();
      return haystack.includes(slashMenu.keyword);
    });
  }, [slashMenu.open, slashMenu.keyword, slashSuggestions]);

  useEffect(() => {
    slashItemRefs.current = slashItemRefs.current.slice(
      0,
      filteredSlashSuggestions.length,
    );
  }, [filteredSlashSuggestions.length]);

  useEffect(() => {
    if (!slashMenu.open || filteredSlashSuggestions.length === 0) return;
    const activeItem = slashItemRefs.current[slashMenu.activeIndex];
    activeItem?.scrollIntoView({ block: "nearest" });
  }, [filteredSlashSuggestions.length, slashMenu.activeIndex, slashMenu.open]);

  const closeSlashMenu = useCallback(() => {
    setSlashMenu((current) =>
      current.open ? { ...current, open: false } : current,
    );
  }, []);

  const updateSlashMenuFromTextarea = useCallback(
    (textarea: HTMLTextAreaElement) => {
      if (!isChatActive()) return;
      const token = findInlineSlashToken(textarea);
      if (!token || slashSuggestions.length === 0) {
        closeSlashMenu();
        return;
      }

      const rect = textarea.getBoundingClientRect();
      const senderRect = textarea
        .closest('[class*="sender"]')
        ?.getBoundingClientRect();
      const positioningRect = textarea
        .closest('[class*="chat-anywhere-layout"]')
        ?.getBoundingClientRect();
      slashTextareaRef.current = textarea;
      setSlashMenu((current) => {
        const next = {
          open: true,
          keyword: token.keyword,
          slashStart: token.slashStart,
          cursor: token.cursor,
          // The SDK layout can establish a transformed containing block for
          // this fixed menu. Convert the viewport coordinate into that block.
          left: (senderRect?.left ?? rect.left) - (positioningRect?.left ?? 0),
          bottom: Math.max(window.innerHeight - rect.top + 8, 96),
          activeIndex: 0,
        };
        if (
          current.open === next.open &&
          current.keyword === next.keyword &&
          current.slashStart === next.slashStart &&
          current.cursor === next.cursor &&
          current.left === next.left &&
          current.bottom === next.bottom
        ) {
          return current;
        }
        return next;
      });
    },
    [closeSlashMenu, isChatActive, slashSuggestions.length],
  );

  const applySlashSuggestion = useCallback(
    (item: CommandSuggestion) => {
      const textarea = slashTextareaRef.current;
      if (!textarea) return;

      const cursor = textarea.selectionStart ?? slashMenu.cursor;
      const insertion = `/${item.value}`;
      const nextValue =
        textarea.value.slice(0, slashMenu.slashStart) +
        insertion +
        textarea.value.slice(cursor);
      const nextCursor = slashMenu.slashStart + insertion.length;
      setTextareaValue(textarea, nextValue, nextCursor);
      textarea.focus();
      closeSlashMenu();
    },
    [closeSlashMenu, slashMenu.cursor, slashMenu.slashStart],
  );

  useEffect(() => {
    const isChatSenderTextarea = (
      target: EventTarget | null,
    ): target is HTMLTextAreaElement =>
      target instanceof HTMLTextAreaElement &&
      target.closest('[class*="sender"]') !== null;

    const scheduleSlashMenuUpdate = (textarea: HTMLTextAreaElement) => {
      window.requestAnimationFrame(() => {
        if (document.activeElement === textarea) {
          updateSlashMenuFromTextarea(textarea);
        }
      });
    };

    const handleInput = (event: Event) => {
      if (!isChatSenderTextarea(event.target)) return;
      scheduleSlashMenuUpdate(event.target);
    };

    const handleClick = (event: MouseEvent) => {
      if (!isChatSenderTextarea(event.target)) {
        closeSlashMenu();
        return;
      }
      scheduleSlashMenuUpdate(event.target);
    };

    const handleKeyUp = (event: KeyboardEvent) => {
      if (!isChatSenderTextarea(event.target)) return;
      if (
        ["ArrowUp", "ArrowDown", "Enter", "Tab", "Escape"].includes(event.key)
      ) {
        return;
      }
      scheduleSlashMenuUpdate(event.target);
    };

    const handleKeyDown = (event: KeyboardEvent) => {
      if (!slashMenu.open || !isChatSenderTextarea(event.target)) return;
      if (filteredSlashSuggestions.length === 0) return;

      const claimNavigationKey = () => {
        event.preventDefault();
        event.stopPropagation();
        event.stopImmediatePropagation();
      };

      if (event.key === "ArrowDown") {
        claimNavigationKey();
        setSlashMenu((current) => ({
          ...current,
          activeIndex:
            (current.activeIndex + 1) % filteredSlashSuggestions.length,
        }));
      } else if (event.key === "ArrowUp") {
        claimNavigationKey();
        setSlashMenu((current) => ({
          ...current,
          activeIndex:
            (current.activeIndex - 1 + filteredSlashSuggestions.length) %
            filteredSlashSuggestions.length,
        }));
      } else if (event.key === "Enter" || event.key === "Tab") {
        claimNavigationKey();
        applySlashSuggestion(
          filteredSlashSuggestions[
            Math.min(slashMenu.activeIndex, filteredSlashSuggestions.length - 1)
          ],
        );
      } else if (event.key === "Escape") {
        claimNavigationKey();
        closeSlashMenu();
      }
    };

    document.addEventListener("input", handleInput);
    document.addEventListener("click", handleClick);
    document.addEventListener("keyup", handleKeyUp);
    document.addEventListener("keydown", handleKeyDown, true);

    return () => {
      document.removeEventListener("input", handleInput);
      document.removeEventListener("click", handleClick);
      document.removeEventListener("keyup", handleKeyUp);
      document.removeEventListener("keydown", handleKeyDown, true);
    };
  }, [
    applySlashSuggestion,
    closeSlashMenu,
    filteredSlashSuggestions,
    slashMenu.activeIndex,
    slashMenu.open,
    updateSlashMenuFromTextarea,
  ]);

  const filteredPersonalLibraryDocuments = useMemo(() => {
    if (!mentionMenu.open) return [];
    if (!mentionMenu.keyword) return personalLibraryDocuments;
    return personalLibraryDocuments.filter((document) =>
      `${document.name} ${document.relative_path}`
        .toLowerCase()
        .includes(mentionMenu.keyword),
    );
  }, [mentionMenu.keyword, mentionMenu.open, personalLibraryDocuments]);

  const closeMentionMenu = useCallback(() => {
    setMentionMenu((current) =>
      current.open ? { ...current, open: false } : current,
    );
  }, []);

  useEffect(() => {
    if (!mentionMenu.open) return;
    let cancelled = false;
    void listChatFileCandidates(chatId)
      .then((files) => {
        if (!cancelled) setPersonalLibraryDocuments(files);
      })
      .catch(() => {
        if (!cancelled) setPersonalLibraryDocuments([]);
      });
    return () => {
      cancelled = true;
    };
  }, [mentionMenu.open, selectedAgent, chatId]);

  const applyPersonalLibraryMention = useCallback(
    (document: ChatFileCandidate) => {
      const textarea = mentionTextareaRef.current;
      if (!textarea) return;
      const cursor = textarea.selectionStart ?? mentionMenu.cursor;
      const insertion = `${encodeFileMention(document)} `;
      const nextValue =
        textarea.value.slice(0, mentionMenu.mentionStart) +
        insertion +
        textarea.value.slice(cursor);
      const nextCursor = mentionMenu.mentionStart + insertion.length;
      setTextareaValue(textarea, nextValue, nextCursor);
      textarea.focus();
      closeMentionMenu();
    },
    [closeMentionMenu, mentionMenu.cursor, mentionMenu.mentionStart],
  );

  useEffect(() => {
    const isSenderTextarea = (
      target: EventTarget | null,
    ): target is HTMLTextAreaElement =>
      target instanceof HTMLTextAreaElement &&
      target.closest('[class*="sender"]') !== null;
    const update = (textarea: HTMLTextAreaElement) => {
      const cursor = textarea.selectionStart ?? 0;
      if (cursor !== textarea.selectionEnd) {
        closeMentionMenu();
        return;
      }
      const token = findPersonalLibraryMentionToken(textarea.value, cursor);
      if (!token) {
        closeMentionMenu();
        return;
      }
      const rect = textarea.getBoundingClientRect();
      const senderRect = textarea
        .closest('[class*="sender"]')
        ?.getBoundingClientRect();
      const positioningRect = textarea
        .closest('[class*="chat-anywhere-layout"]')
        ?.getBoundingClientRect();
      mentionTextareaRef.current = textarea;
      setMentionMenu({
        open: true,
        keyword: token.keyword,
        mentionStart: token.mentionStart,
        cursor: token.cursor,
        left: (senderRect?.left ?? rect.left) - (positioningRect?.left ?? 0),
        bottom: Math.max(window.innerHeight - rect.top + 8, 96),
        activeIndex: 0,
      });
    };
    const handleInput = (event: Event) => {
      if (isSenderTextarea(event.target)) {
        const textarea = event.target;
        window.requestAnimationFrame(() => update(textarea));
      }
    };
    const handleKeyDown = (event: globalThis.KeyboardEvent) => {
      if (!mentionMenu.open || !isSenderTextarea(event.target)) return;
      if (event.key === "Escape") {
        event.preventDefault();
        closeMentionMenu();
        return;
      }
      if (filteredPersonalLibraryDocuments.length === 0) return;
      if (["ArrowDown", "ArrowUp", "Enter", "Tab"].includes(event.key)) {
        event.preventDefault();
        event.stopPropagation();
        event.stopImmediatePropagation();
      }
      if (event.key === "ArrowDown") {
        setMentionMenu((current) => ({
          ...current,
          activeIndex:
            (current.activeIndex + 1) % filteredPersonalLibraryDocuments.length,
        }));
      } else if (event.key === "ArrowUp") {
        setMentionMenu((current) => ({
          ...current,
          activeIndex:
            (current.activeIndex -
              1 +
              filteredPersonalLibraryDocuments.length) %
            filteredPersonalLibraryDocuments.length,
        }));
      } else if (event.key === "Enter" || event.key === "Tab") {
        applyPersonalLibraryMention(
          filteredPersonalLibraryDocuments[
            Math.min(
              mentionMenu.activeIndex,
              filteredPersonalLibraryDocuments.length - 1,
            )
          ],
        );
      }
    };
    document.addEventListener("input", handleInput);
    document.addEventListener("keydown", handleKeyDown, true);
    return () => {
      document.removeEventListener("input", handleInput);
      document.removeEventListener("keydown", handleKeyDown, true);
    };
  }, [
    applyPersonalLibraryMention,
    closeMentionMenu,
    filteredPersonalLibraryDocuments,
    mentionMenu.activeIndex,
    mentionMenu.open,
    personalLibraryDocuments.length,
  ]);

  useEffect(() => {
    let cancelled = false;
    slashApi
      .catalog(selectedAgent)
      .then((items) => {
        if (!cancelled) setSlashCatalog(items);
      })
      .catch((error) => {
        console.warn("[Slash] Failed to load slash catalog:", error);
        if (!cancelled) setSlashCatalog([]);
      });
    return () => {
      cancelled = true;
    };
  }, [selectedAgent]);

  // Consume approvals from Context and filter by current session.
  // Uses a serialized key to avoid creating a new Map (and triggering
  // re-renders of the entire Chat tree) when the filtered result is identical.
  const prevApprovalKeyRef = useRef("");

  useEffect(() => {
    const currentSessionId = window.currentSessionId || chatId || "";

    // When no session ID is available yet, use the first approval's
    // root_session_id as a hint (handles the race where approval arrives
    // before the session ID is propagated).
    let effectiveSessionId = currentSessionId;
    if (!effectiveSessionId && approvals.length > 0) {
      effectiveSessionId = approvals[0].root_session_id;
    }

    const sessionApprovals = effectiveSessionId
      ? approvals.filter(
          (approval) => approval.root_session_id === effectiveSessionId,
        )
      : approvals;

    // Build a stable key from the filtered request IDs so we can skip
    // the Map rebuild when nothing changed (avoids re-render every 2.5s poll).
    const approvalKey = sessionApprovals
      .map((a) => a.request_id)
      .sort()
      .join(",");

    if (approvalKey === prevApprovalKeyRef.current) return;
    prevApprovalKeyRef.current = approvalKey;

    const newMap = new Map<string, ApprovalMessageData>();
    for (const approval of sessionApprovals) {
      newMap.set(approval.request_id, {
        requestId: approval.request_id,
        sessionId: approval.session_id,
        rootSessionId: approval.root_session_id,
        agentId: approval.agent_id,
        toolName: approval.tool_name,
        toolSource: approval.tool_source,
        severity: approval.severity,
        findingsCount: approval.findings_count,
        findingsSummary: approval.findings_summary,
        toolParams: approval.tool_params,
        createdAt: approval.created_at,
        timeoutSeconds: approval.timeout_seconds,
        isGeneralized: approval.is_generalized,
        exactTarget: approval.exact_target,
        similarTarget: approval.similar_target,
        sourceType: approval.source_type,
      });
    }

    setApprovalRequests(newMap);
  }, [approvals, chatId]);

  const approvalRenderers = useMemo(() => {
    const renderers = new Map<
      string,
      { pluginId: string; item: ChatApprovalRendererItem }
    >();
    for (const entry of extLists[ChatList.approvalRenderers]) {
      renderers.set(entry.item.sourceType, entry);
    }
    return renderers;
  }, [extLists]);

  const dismissApproval = useCallback(
    (requestId: string) => {
      setApprovals((previous) =>
        previous.filter((item) => item.request_id !== requestId),
      );
      setApprovalRequests((previous) => {
        const next = new Map(previous);
        next.delete(requestId);
        return next;
      });
    },
    [setApprovals, setApprovalRequests],
  );

  const handleApprove = useCallback(
    async (requestId: string, scope?: "exact" | "similar") => {
      const request = approvalRequests.get(requestId);
      if (!request) return;

      const rootSessionId = request.rootSessionId || request.sessionId;

      try {
        const cardElement = document.querySelector(
          `[data-approval-id="${requestId}"]`,
        );
        if (cardElement) {
          cardElement.classList.add("approvalCardExit");
        }

        await commandsApi.sendApprovalCommand(
          "approve",
          requestId,
          rootSessionId,
          undefined,
          scope,
          resolveBackendChatId(chatIdRef.current ?? chatId),
        );
        setApprovals((prev) =>
          prev.filter((item) => item.request_id !== requestId),
        );
        message.success(t("approval.approved"));

        // Delay removal to let exit animation complete
        setTimeout(() => {
          setApprovalRequests((prev) => {
            const next = new Map(prev);
            next.delete(requestId);
            return next;
          });
        }, 300);
      } catch (error) {
        message.error(t("approval.approveFailed"));
        console.error("Failed to approve:", error);
      }
    },
    [approvalRequests, chatId, t, message, setApprovals],
  );

  const handleDeny = useCallback(
    async (requestId: string) => {
      const request = approvalRequests.get(requestId);
      if (!request) return;

      // Use currentSessionId (root session) instead of request.sessionId (sub-agent session)
      const rootSessionId = request.rootSessionId || request.sessionId;

      try {
        // Add exit animation class
        const cardElement = document.querySelector(
          `[data-approval-id="${requestId}"]`,
        );
        if (cardElement) {
          cardElement.classList.add("approvalCardExit");
        }

        await commandsApi.sendApprovalCommand(
          "deny",
          requestId,
          rootSessionId,
          undefined,
          undefined,
          resolveBackendChatId(chatIdRef.current ?? chatId),
        );
        setApprovals((prev) =>
          prev.filter((item) => item.request_id !== requestId),
        );
        message.success(t("approval.denied"));

        // Delay removal to let animation complete
        // Backend will remove from pending list, next poll will update UI
        setTimeout(() => {
          setApprovalRequests((prev) => {
            const next = new Map(prev);
            next.delete(requestId);
            return next;
          });
        }, 300); // Match animation duration
      } catch (error) {
        message.error(t("approval.denyFailed"));
        console.error("Failed to deny:", error);
      }
    },
    [approvalRequests, chatId, t, message, setApprovals],
  );

  // Use custom hooks for better separation of concerns
  const isComposingRef = useIMEComposition(isChatActive);
  const { multimodalCaps, fetchMultimodalCaps } = useMultimodalCapabilities(
    refreshKey,
    location.pathname,
    isChatActive,
    selectedAgent,
    usesQwenPawBackend,
  );

  const { setLastChatId, getLastChatId, removeLastChatId } = useAgentStore();
  const setLastChatIdRef = useRef(setLastChatId);
  setLastChatIdRef.current = setLastChatId;
  const getLastChatIdRef = useRef(getLastChatId);
  getLastChatIdRef.current = getLastChatId;
  const removeLastChatIdRef = useRef(removeLastChatId);
  removeLastChatIdRef.current = removeLastChatId;
  const selectedAgentRef = useRef(selectedAgent);
  selectedAgentRef.current = selectedAgent;

  const lastSessionIdRef = useRef<string | null>(null);
  /** Tracks the stale auto-selected session ID that was skipped on init, so we can suppress its late-arriving onSessionSelected callback. */
  const staleAutoSelectedIdRef = useRef<string | null>(null);
  const chatIdRef = useRef(chatId);
  const navigateRef = useRef(navigate);
  const chatRef = useRef<IAgentScopeRuntimeWebUIRef>(null);
  const chatTransportLifecycleRef = useRef(new ChatTransportLifecycle());
  const pendingSenderClearRef = useRef<string | null>(null);

  const clearConversationView = useCallback(() => {
    chatTransportLifecycleRef.current.abortCurrent();
    chatRef.current?.messages.removeAllMessages();
    useTurnUsageStore.getState().setSnapshot(null);
  }, []);

  useEffect(() => {
    window.addEventListener("qwenpaw:new-chat-reset", clearConversationView);
    return () =>
      window.removeEventListener(
        "qwenpaw:new-chat-reset",
        clearConversationView,
      );
  }, [clearConversationView]);

  useEffect(() => {
    if (
      chatId ||
      !sessionApi.lastActiveChatId ||
      !isLocalTimestampId(sessionApi.lastActiveChatId)
    ) {
      return;
    }

    // Route transition effects from the SDK can re-apply the previous
    // selection after the initial reset event. Clear once after the /chat
    // draft route has committed as the authoritative final guard.
    clearConversationView();
    const frame = window.requestAnimationFrame(clearConversationView);
    return () => window.cancelAnimationFrame(frame);
  }, [chatId, clearConversationView]);

  const handleSharedConversationRevoked = useCallback(() => {
    const activeId = chatIdRef.current;
    const activeBackendId = resolveBackendChatId(activeId);
    if (!activeId || !activeBackendId || activeBackendId !== backendChatId) {
      return;
    }

    const remainingSessions =
      sessionApi.invalidateSessionAccess(activeBackendId);
    syncSessionsGlobal(remainingSessions);
    chatRef.current?.messages.removeAllMessages();
    useTurnUsageStore.getState().setSnapshot(null);
    lastSessionIdRef.current = null;
    sessionApi.resetWindowIdentity();
    message.warning(t("chat.sharedAccessRevoked"));
    navigateRef.current(CHAT_BASE_PATH, { replace: true });
  }, [backendChatId, message, t]);

  useSharedConversationAccessGuard({
    conversationId: backendChatId,
    enabled: currentSession?.accessRole === "viewer",
    onRevoked: handleSharedConversationRevoked,
  });

  useEffect(() => {
    const handler = (e: Event) => {
      void fetchMultimodalCaps();
      const maxInputLength = (e as CustomEvent<{ maxInputLength?: number }>)
        .detail?.maxInputLength;
      if (typeof maxInputLength === "number") {
        patchContextMaxInputLength(chatRef, maxInputLength);
      }
    };
    window.addEventListener("model-switched", handler);
    return () => window.removeEventListener("model-switched", handler);
  }, [fetchMultimodalCaps]);

  const pendingClearHistoryRef = useRef(false);
  const resumeSyncInFlightRef = useRef(false);
  const lastResumeSyncAtRef = useRef(0);
  const wasRunningWhenHiddenRef = useRef(false);
  const whisperSpeechRef = useRef<WhisperSpeechButtonRef>(null);
  const voiceScope = useVoiceScope();
  const [voiceStatus, setVoiceStatus] = useState<{
    key: string;
    available: boolean;
  } | null>(null);
  const whisperEnabled =
    !chatReadOnly &&
    voiceScope.canUse &&
    voiceStatus?.key === voiceScope.key &&
    voiceStatus.available;
  useEffect(() => {
    let active = true;
    let controller: AbortController | null = null;
    const refresh = async () => {
      controller?.abort();
      controller = new AbortController();
      const requestController = controller;
      if (!voiceScope.canUse || chatReadOnly) {
        setVoiceStatus(null);
        return;
      }
      try {
        const status = await voiceApi.status(
          voiceScope,
          requestController.signal,
        );
        if (active && voiceScope.current() && !requestController.signal.aborted)
          setVoiceStatus({
            key: voiceScope.key,
            available: status.enabled && status.available,
          });
      } catch {
        if (active && voiceScope.current() && !requestController.signal.aborted)
          setVoiceStatus(null);
      }
    };
    void refresh();
    window.addEventListener("focus", refresh);
    window.addEventListener("voice-transcription-changed", refresh);
    return () => {
      active = false;
      controller?.abort();
      window.removeEventListener("focus", refresh);
      window.removeEventListener("voice-transcription-changed", refresh);
    };
  }, [voiceScope, chatReadOnly, queueSessionId]);
  const getVoiceSender = useCallback(
    (anchor?: HTMLElement | null) => {
      if (!isChatActive()) return null;
      const root = chatMessagesAreaRef.current;
      if (anchor) {
        return findVoiceSender(root, anchor);
      }
      const focused = document.activeElement;
      if (
        focused instanceof HTMLTextAreaElement &&
        root?.contains(focused) &&
        focused.closest('[class*="sender"]')
      )
        return focused;
      return (
        root?.querySelector<HTMLTextAreaElement>(
          '[class*="sender"] textarea',
        ) ?? null
      );
    },
    [isChatActive],
  );
  const handleWhisperTranscription = useCallback(
    (text: string, textarea?: HTMLTextAreaElement) => {
      if (
        !textarea ||
        !chatMessagesAreaRef.current?.contains(textarea) ||
        !isChatActive() ||
        chatReadOnly
      )
        return;
      setTextareaValue(
        textarea,
        textarea.value ? `${textarea.value} ${text}` : text,
      );
      textarea.focus();
    },
    [isChatActive, chatReadOnly],
  );

  useMessageHistoryNavigation(chatRef, isChatActive, isComposingRef);
  useChatInputDraft(isChatActive, selectedAgent);
  // ── Message Queue ───────────────────────────────────────────────────────

  // Stop background sender for THIS session when ChatPage mounts (foreground
  // takes over); start background senders for all OTHER sessions with pending
  // items. On unmount (or session switch), start bg sender for THIS session.
  useEffect(() => {
    const currentQueueSessionId = queueSessionId;
    stopBackgroundQueue(currentQueueSessionId);
    // Kick off background senders for other sessions that have pending items
    startAllBackgroundQueues(currentQueueSessionId);
    return () => {
      if (autoSendTimerRef.current) {
        clearTimeout(autoSendTimerRef.current);
        autoSendTimerRef.current = null;
      }
      // Only the owner tab may continue sending in the background; non-owner
      // tabs leave the queue alone for the owner (or next owner) to handle.
      if (!isOwnerRef.current) return;
      const remaining = messageQueueRef.current;
      if (remaining.length > 0) {
        // Use captured queueSessionId from this effect instance, not the
        // ref (which may already point to the next session after re-render).
        const queueKey = currentQueueSessionId;
        const backendSessionId =
          sessionApi.getBackendSessionId(queueKey) || queueKey;
        // Skip if no real backend session yet (e.g. "new" chat that never
        // resolved an id) — the items remain in storage to be picked up by
        // the next foreground load.
        if (backendSessionId) {
          // Resolve the chat UUID for status polling. queueKey may be a
          // local timestamp if the URL hasn't been replaced yet; in that
          // case sessionApi keeps the real backend UUID under realId.
          const chatIdForStatus =
            sessionApi.getRealIdForSession(queueKey) || queueKey;
          startBackgroundQueue(queueKey, backendSessionId, chatIdForStatus);
        }
      }
    };
  }, [queueSessionId]);

  // Auto-send next queue item when:
  // 1. Response just completed (loading→idle), OR
  // 2. Queue goes from empty→non-empty while idle (Ctrl+Enter while not chatting)
  // Uses a delayed timer so session switches can cancel it before it fires.
  useEffect(() => {
    const wasLoading = prevChatLoadingRef.current;
    const prevLen = prevQueueLenRef.current;
    prevChatLoadingRef.current = chatLoading;
    prevQueueLenRef.current = messageQueue.length;

    const responseJustCompleted = wasLoading && !chatLoading;
    const itemsJustQueued =
      prevLen === 0 && messageQueue.length > 0 && !chatLoading;

    if (responseJustCompleted) {
      // The currently-sending item finished. Clear the marker so the next
      // Enter handler decision and lock acquisition see a clean state.
      useMessageQueueStore.getState().setCurrentSendingId(null);
      void syncLoopModeStatus().finally(scheduleNextSend);
    } else if (itemsJustQueued) {
      scheduleNextSend();
    }
  }, [chatLoading, messageQueue, scheduleNextSend, syncLoopModeStatus]);

  // When this tab acquires ownership (e.g., previous owner closed), kick the
  // queue: any pending items left behind should now be sent by us.
  useEffect(() => {
    if (!isOwner) return;
    if (chatLoadingRef.current) return;
    const q = useMessageQueueStore.getState().getQueue(queueSessionId);
    if (q.length > 0) {
      scheduleNextSend();
    }
  }, [isOwner, queueSessionId, scheduleNextSend]);

  // Intercept Enter to enqueue:
  //  - Ctrl/Meta+Enter: always enqueue (even when idle)
  //  - Plain Enter while loading: enqueue (SDK blocks triggerSend when loading)
  //  - Plain Enter while the queue subsystem is otherwise busy (queue not
  //    empty / auto-send timer pending / an item is currently being sent):
  //    enqueue, so we don't slip into a direct SDK send during the brief
  //    idle window between two queued items.
  useEffect(() => {
    const handleEnterEnqueue = (e: KeyboardEvent) => {
      if (!isChatActive() || e.key !== "Enter" || e.shiftKey) return;
      const hasCtrl = e.ctrlKey || e.metaKey;
      const queueBusy =
        messageQueueRef.current.length > 0 ||
        autoSendTimerRef.current !== null ||
        useMessageQueueStore.getState().currentSendingId !== null;
      if (!hasCtrl && !chatLoadingRef.current && !queueBusy) return;
      if (!hasCtrl && e.altKey) return;
      if (isComposingRef.current || (e as any).isComposing) return;
      const textarea = hasCtrl
        ? getActiveSenderTextarea()
        : getSenderTextareaFromTarget(e.target);
      if (!textarea) return;
      const val = textarea.value.trim();
      if (!val) return;
      e.preventDefault();
      e.stopPropagation();
      const currentQ = useMessageQueueStore.getState().getQueue(queueSessionId);
      if (currentQ.length >= MAX_QUEUE_SIZE) {
        message.warning(t("chat.queue.queueFull", { max: MAX_QUEUE_SIZE }));
        return;
      }
      const queueText = prepareLoopModeMessage(val);
      const enqueueIdentity = sessionApi.getSessionIdentity();
      useMessageQueueStore.getState().enqueue(queueSessionId, {
        text: queueText,
        attachments:
          pendingFileListRef.current.length > 0
            ? pendingFileListRef.current.map((f) => ({
                url: f.url,
                name: f.name,
                type: f.type,
                size: f.size,
              }))
            : undefined,
        userId: enqueueIdentity.userId,
        channel: enqueueIdentity.channel,
      });
      // Clear tracked attachments after enqueuing
      pendingFileListRef.current = [];
      setTextareaValue(textarea, "");
      // Clear sender attachment preview. Defer to next tick so React commits
      // any pending state updates (e.g. from setTextareaValue) before we
      // interact with the Attachments component's remove buttons.
      clearSenderAttachments();
    };
    document.addEventListener("keydown", handleEnterEnqueue, true);
    return () =>
      document.removeEventListener("keydown", handleEnterEnqueue, true);
  }, [isChatActive, queueSessionId]);

  const handleQueueRemove = useCallback(
    (id: string) => {
      useMessageQueueStore.getState().remove(queueSessionId, id);
    },
    [queueSessionId],
  );

  const handleQueueEdit = useCallback(
    (id: string, text: string) => {
      useMessageQueueStore.getState().edit(queueSessionId, id, text);
    },
    [queueSessionId],
  );

  const handleQueueReorder = useCallback(
    (reordered: QueueItem[]) => {
      useMessageQueueStore.getState().reorder(queueSessionId, reordered);
    },
    [queueSessionId],
  );

  const handleQueueInterruptAndSend = useCallback(
    (item: QueueItem) => {
      if (!isOwnerRef.current) return;
      if (runtimeLoadingBridgeRef.current?.getLoading?.()) {
        const sessionId = window.currentSessionId || chatIdRef.current;
        if (sessionId) {
          const resolvedId =
            sessionApi.getRealIdForSession(sessionId) ?? sessionId;
          chatApi.stopChat(resolvedId).catch(() => {});
        }
      }
      useMessageQueueStore.getState().remove(queueSessionId, item.id);
      setTimeout(() => {
        void withSendLock(queueSessionId, () => {
          useMessageQueueStore.getState().setCurrentSendingId(item.id);
          chatRef.current?.input.submit({
            query: beginLoopModeSubmission(item.text),
            fileList: buildFileList(item),
          });
        });
      }, 600);
    },
    [queueSessionId, buildFileList],
  );

  const handleQueueClear = useCallback(() => {
    useMessageQueueStore.getState().clear(queueSessionId);
  }, [queueSessionId]);

  const handleQueuePauseResume = useCallback(() => {
    const current = useMessageQueueStore.getState().getRunState(queueSessionId);
    if (current === "paused") {
      useMessageQueueStore.getState().setRunState(queueSessionId, "running");
      // Try to resume sending immediately
      if (!chatLoadingRef.current && isOwnerRef.current) {
        void withSendLock(queueSessionId, () => {
          const q = useMessageQueueStore.getState().getQueue(queueSessionId);
          if (q.length === 0) return;
          const head = q[0];
          useMessageQueueStore.getState().setCurrentSendingId(head.id);
          useMessageQueueStore.getState().remove(queueSessionId, head.id);
          chatRef.current?.input.submit({
            query: beginLoopModeSubmission(head.text),
            fileList: buildFileList(head),
          });
        });
      }
    } else {
      useMessageQueueStore.getState().setRunState(queueSessionId, "paused");
    }
  }, [queueSessionId, buildFileList]);

  const handleQueueRetry = useCallback(
    (id: string) => {
      useMessageQueueStore
        .getState()
        .setItemStatus(queueSessionId, id, "pending");
      useMessageQueueStore.getState().setRunState(queueSessionId, "running");
      // Trigger send if idle
      if (!chatLoadingRef.current && isOwnerRef.current) {
        void withSendLock(queueSessionId, () => {
          const q = useMessageQueueStore.getState().getQueue(queueSessionId);
          const target = q.find((it) => it.id === id);
          if (!target) return;
          useMessageQueueStore.getState().setCurrentSendingId(id);
          useMessageQueueStore.getState().remove(queueSessionId, id);
          chatRef.current?.input.submit({
            query: beginLoopModeSubmission(target.text),
            fileList: buildFileList(target),
          });
        });
      }
    },
    [queueSessionId, buildFileList],
  );

  const handleQueueSkip = useCallback(
    (id: string) => {
      useMessageQueueStore.getState().remove(queueSessionId, id);
      // After skip, try to continue sending
      if (!chatLoadingRef.current && isOwnerRef.current) {
        void withSendLock(queueSessionId, () => {
          const q = useMessageQueueStore.getState().getQueue(queueSessionId);
          if (q.length === 0) return;
          const next = q[0];
          useMessageQueueStore.getState().setCurrentSendingId(next.id);
          useMessageQueueStore.getState().remove(queueSessionId, next.id);
          chatRef.current?.input.submit({
            query: beginLoopModeSubmission(next.text),
            fileList: buildFileList(next),
          });
        });
      }
    },
    [queueSessionId, buildFileList],
  );
  // ── End Message Queue ───────────────────────────────────────────────────

  const onFileCardClick = useCallback(
    (fileInfo: { name?: string; size?: number; url?: string }) => {
      if (!fileInfo.url) return;
      const locator = artifactLocatorFromFileCard({
        agentId: selectedAgent,
        conversationId: backendChatId,
        file: fileInfo,
      });
      if (locator) {
        dispatchFilesDrawer({
          type: "OPEN_PREVIEW",
          locator,
          trigger: null,
        });
        return;
      }
      const target: FileTarget = {
        source: "attachment",
        path:
          filePathFromPreviewUrl(fileInfo.url) ||
          fileInfo.name ||
          fileInfo.url.split("?")[0].split("/").pop() ||
          t("files.title"),
        artifactUrl: fileInfo.url,
      };
      dispatchFilesDrawer({
        type: "OPEN_PREVIEW",
        target,
        trigger: null,
      });
    },
    [backendChatId, dispatchFilesDrawer, selectedAgent, t],
  );

  const openInlineFileReference = useCallback(
    async (reference: ParsedFileReference, trigger: HTMLElement) => {
      let root: FileTarget["root"] = "project";
      try {
        const agentDirectory = await projectDirectoryApi.get();
        const backendChatId = resolveBackendChatId(chatId);
        const projectDirectory = backendChatId
          ? (await chatProjectDirectoryApi.get(backendChatId)).project_dir
          : agentDirectory.path;
        root = rootForFileReference(
          reference.path,
          projectDirectory,
          agentDirectory.workspace_dir ?? agentDirectory.path,
        );
      } catch {
        root = "project";
      }
      const target: FileTarget = {
        source: "workspace",
        path: reference.path,
        root,
        line: reference.startLine,
        endLine: reference.endLine,
      };
      dispatchFilesDrawer({
        type: reference.kind === "editor" ? "OPEN_WORKSPACE" : "OPEN_PREVIEW",
        target,
        trigger,
      });
    },
    [chatId, dispatchFilesDrawer],
  );

  // Shortcut key for voice recording (Ctrl+Shift+M or Cmd+Shift+M on Mac)
  useEffect(() => {
    const handleShortcut = (e: KeyboardEvent) => {
      if (!isChatActive()) return;
      // Check for Ctrl+Shift+M (Windows/Linux) or Cmd+Shift+M (Mac)
      if (
        (e.ctrlKey || e.metaKey) &&
        e.shiftKey &&
        e.key.toLowerCase() === "m"
      ) {
        e.preventDefault();
        if (whisperEnabled) {
          whisperSpeechRef.current?.toggleRecording();
        }
      }
    };
    document.addEventListener("keydown", handleShortcut);
    return () => document.removeEventListener("keydown", handleShortcut);
  }, [isChatActive, whisperEnabled]);
  chatIdRef.current = chatId;
  navigateRef.current = navigate;

  const scheduleHistoryClear = useCallback(() => {
    queueMicrotask(() => {
      if (!pendingClearHistoryRef.current) return;
      pendingClearHistoryRef.current = false;
      chatRef.current?.messages.removeAllMessages();
      useTurnUsageStore.getState().setSnapshot(null);
    });
  }, []);

  const handleCompactCommand = useCallback(() => {
    chatRef.current?.input.submit({ query: "/compact" });
  }, []);

  const handleNewCommand = useCallback(() => {
    const current = useTurnUsageStore.getState().snapshot;
    const maxInputLength = current?.context_usage?.max_input_length ?? 131072;
    useTurnUsageStore.getState().setSnapshot({
      usage: null,
      context_usage: {
        estimated_tokens: 0,
        max_input_length: maxInputLength,
        context_usage_ratio: 0,
      },
    });
    chatRef.current?.input.submit({ query: "/new" });
  }, []);

  // Tell sessionApi which session to put first in getSessionList, so the library's
  // useMount auto-selects the correct session without an extra getSession round-trip.
  // When URL has no chatId (e.g. navigating back from /settings), fall back to the
  // last actively selected session to avoid jumping to the first session on re-mount.
  // Never use a temporary local timestamp id here: it would be passed to the SDK
  // as preferredChatId and could be navigated to as a bogus URL.
  const safeLastActive = isLocalTimestampId(sessionApi.lastActiveChatId)
    ? null
    : sessionApi.lastActiveChatId;
  const safeLastStored = isLocalTimestampId(getLastChatId(selectedAgent))
    ? null
    : getLastChatId(selectedAgent);
  const effectiveChatId = chatId || safeLastActive || safeLastStored;
  if (effectiveChatId && sessionApi.preferredChatId !== effectiveChatId) {
    sessionApi.preferredChatId = effectiveChatId;
  }

  // Register session API event callbacks for URL synchronization

  useEffect(() => {
    const buildCurrentSessionPath = (sessionId: string) =>
      buildChatPath(sessionId);

    const buildCurrentBasePath = () => CHAT_BASE_PATH;

    sessionApi.onSessionIdResolved = (tempId, realId) => {
      if (!isChatActiveRef.current) return;
      const agentId = selectedAgentRef.current;
      migratePendingProjectDirectory(agentId, tempId, realId);
      const fromScopeKey = sessionFilesScopeKey(agentId, tempId);
      const toScopeKey = sessionFilesScopeKey(agentId, realId);
      useCodingTabsStore.getState().migrateScope(fromScopeKey, toScopeKey);
      useFilesSurfaceStore.getState().migrateSession(fromScopeKey, toScopeKey);
      try {
        useMessageQueueStore.getState().migrateQueue(tempId, realId);
      } catch {
        // ignore migration errors
      }
      lastSessionIdRef.current = realId;
      sessionApi.trackNavigatedSession(
        realId,
        setLastChatIdRef.current,
        selectedAgentRef.current,
      );
      navigateRef.current(buildCurrentSessionPath(realId), { replace: true });
    };

    sessionApi.onSessionRemoved = (removedId) => {
      // Drop the persisted last-chat id for the current agent when it points
      // at the removed session, so agent-switch restore doesn't resurrect a
      // deleted conversation.
      const agentId = selectedAgentRef.current;
      if (getLastChatIdRef.current(agentId) === removedId) {
        removeLastChatIdRef.current(agentId);
      }
      // Same for the in-memory re-mount fallback used when the URL has no
      // chatId (e.g. navigating back from /settings).
      const lastActive = sessionApi.lastActiveChatId;
      if (
        lastActive &&
        (lastActive === removedId ||
          sessionApi.getRealIdForSession(lastActive) === removedId)
      ) {
        sessionApi.lastActiveChatId = null;
      }

      // Clean up the queue and abort any in-flight background send for the
      // removed session so stale items don't linger in storage or get sent
      // after the conversation is deleted. Navigation to a fresh chat is
      // owned by the delete handlers (via the "qwenpaw:sidebar-new-chat"
      // event), so this callback stays focused on resource cleanup and can
      // run regardless of which session is currently active.
      try {
        useMessageQueueStore.getState().clear(removedId);
      } catch {
        // ignore
      }
      stopBackgroundQueue(removedId);
      const removedScopeKey = sessionFilesScopeKey(
        selectedAgentRef.current,
        removedId,
      );
      useCodingTabsStore.getState().removeScope(removedScopeKey);
      useFilesSurfaceStore.getState().removeSession(removedScopeKey);
    };

    sessionApi.onSessionSelected = (
      sessionId: string | null | undefined,
      realId: string | null,
    ) => {
      if (!isChatActiveRef.current) return;

      // Issue #4557: When a user-initiated session switch is in progress,
      // handleSessionClick owns the navigate call. Do NOT navigate here
      // to avoid race conditions and infinite loops.
      if (sessionApi.isSessionSwitching) return;

      // If the user just created a new chat that hasn't sent its first message
      // yet, suppress the library's auto-selection of another session.
      // The pending session will enter the drawer (and become the selected
      // session) only after triggerResolve fires onSessionIdResolved.
      if (
        sessionApi.lastActiveChatId &&
        sessionApi.isUnresolvedLocalSession(sessionApi.lastActiveChatId)
      ) {
        return;
      }

      // Update URL when session is selected and different from current
      const targetId = realId || sessionId;
      if (!targetId) return;

      // If a preferred chatId from the URL exists and no navigation has happened yet,
      // skip the library's initial auto-selection (always first session).
      // ChatSessionInitializer will apply the correct selection afterward.
      if (
        chatIdRef.current &&
        lastSessionIdRef.current === null &&
        targetId !== chatIdRef.current
      ) {
        lastSessionIdRef.current = targetId;
        // Record the stale ID so its delayed getSession callback is also suppressed.
        staleAutoSelectedIdRef.current = targetId;
        return;
      }

      // Suppress the stale getSession callback that arrives after the correct session loads.
      if (
        staleAutoSelectedIdRef.current &&
        staleAutoSelectedIdRef.current === targetId
      ) {
        staleAutoSelectedIdRef.current = null;
        return;
      }

      const resolvedTarget = sessionApi.getEffectiveSessionId(targetId, null);
      // History reads are not navigation intents, including after completion.
      if (
        chatIdRef.current &&
        sessionApi.getEffectiveSessionId(chatIdRef.current) !== resolvedTarget
      )
        return;

      // Never navigate to a temporary local timestamp id. The SDK may
      // auto-select an unresolved local session after an agent switch;
      // ignoring it keeps the URL stable until the user sends a message or
      // selects a real backend session.
      if (isLocalTimestampId(resolvedTarget)) return;

      if (
        resolvedTarget !== lastSessionIdRef.current &&
        targetId !== lastSessionIdRef.current
      ) {
        lastSessionIdRef.current = resolvedTarget;
        sessionApi.trackNavigatedSession(
          resolvedTarget,
          setLastChatIdRef.current,
          selectedAgentRef.current,
        );
        navigateRef.current(buildCurrentSessionPath(resolvedTarget), {
          replace: true,
        });
      }
    };

    sessionApi.onSessionCreated = (sessionId) => {
      if (!isChatActiveRef.current) return;
      const agentId = selectedAgentRef.current;
      migratePendingProjectDirectory(agentId, "new", sessionId);
      const fromScopeKey = sessionFilesScopeKey(agentId, "new");
      const toScopeKey = sessionFilesScopeKey(agentId, sessionId);
      useCodingTabsStore.getState().migrateScope(fromScopeKey, toScopeKey);
      useFilesSurfaceStore.getState().migrateSession(fromScopeKey, toScopeKey);
      try {
        useMessageQueueStore.getState().clear("new");
      } catch {
        // ignore
      }
      lastSessionIdRef.current = sessionId;
      sessionApi.lastActiveChatId = sessionId;
      // Do not persist a temporary local timestamp id. It would otherwise be
      // restored on agent switch and appear as an unknown id in the URL. The
      // real backend UUID is persisted by onSessionIdResolved after the first
      // message is sent.
      if (isLocalTimestampId(sessionId)) {
        removeLastChatIdRef.current(selectedAgentRef.current);
      } else {
        setLastChatIdRef.current(selectedAgentRef.current, sessionId);
      }
      navigateRef.current(buildCurrentBasePath(), { replace: true });
    };

    return () => {
      sessionApi.onSessionIdResolved = null;
      sessionApi.onSessionRemoved = null;
      sessionApi.onSessionSelected = null;
      sessionApi.onSessionCreated = null;
    };
  }, []);

  const syncCurrentChatAfterResume = useCallback(async () => {
    if (!isChatActiveRef.current || resumeSyncInFlightRef.current) return;

    if (
      !shouldSyncChatAfterResume({
        wasRunningWhenHidden: wasRunningWhenHiddenRef.current,
        frontendRunning: Boolean(chatLoadingRef.current),
      })
    ) {
      return;
    }
    wasRunningWhenHiddenRef.current = false;

    const now = Date.now();
    if (now - lastResumeSyncAtRef.current < 1500) return;
    lastResumeSyncAtRef.current = now;

    const sessionId = chatIdRef.current || window.currentSessionId || "";
    if (!sessionId || sessionId === "undefined" || sessionId === "null") {
      return;
    }

    resumeSyncInFlightRef.current = true;
    try {
      await sessionApi.getSessionList();
      const realId = sessionApi.getRealIdForSession(sessionId) ?? sessionId;
      if (!realId || /^\d+$/.test(realId)) return;

      const history = await chatApi.getChat(realId);
      if ((history.messages || []).length === 0) return;

      const currentMessageCount =
        chatRef.current?.messages?.getMessages?.()?.length ?? 0;
      const backendMessageCount = history.messages.length;
      const resumeAction = decideChatResumeAction({
        backendStatus: history.status,
        backendMessageCount,
        currentMessageCount,
        frontendRunning: Boolean(chatLoadingRef.current),
      });
      if (resumeAction === "replace_history") {
        sessionApi.invalidateConvertedCache(realId);
        const canonicalSession = await sessionApi.getSession(realId);
        const activeId = chatIdRef.current || window.currentSessionId || "";
        const activeRealId =
          sessionApi.getRealIdForSession(activeId) ?? activeId;
        if (!isChatActiveRef.current || activeRealId !== realId) return;

        // Stop the old SSE body before replacing the message list. Browsers can
        // buffer stream chunks while a tab is suspended; without this fence,
        // those chunks are delivered after the canonical snapshot and append
        // the same user/assistant turn with the SDK's transient message IDs.
        chatTransportLifecycleRef.current.abortCurrent();
        replaceRuntimeMessageSnapshot(
          chatRef.current?.messages,
          canonicalSession.messages || [],
        );
        runtimeLoadingBridgeRef.current?.setLoading?.(false);
        setChatLoading(false);
      } else if (resumeAction === "reconnect") {
        chatTransportLifecycleRef.current.abortCurrent();
        setRefreshKey((prev) => prev + 1);
      }
    } catch (error) {
      console.debug("[Chat resume sync] skipped:", error);
    } finally {
      resumeSyncInFlightRef.current = false;
    }
  }, []);

  useEffect(
    () => () => chatTransportLifecycleRef.current.abortCurrent(),
    [],
  );

  useEffect(() => {
    const onResume = () => {
      if (document.visibilityState === "hidden") {
        wasRunningWhenHiddenRef.current = Boolean(chatLoadingRef.current);
        return;
      }
      if (document.visibilityState === "visible") {
        void syncCurrentChatAfterResume();
      }
    };
    const onFocus = () => {
      void syncCurrentChatAfterResume();
    };
    const onPageShow = () => {
      void syncCurrentChatAfterResume();
    };

    document.addEventListener("visibilitychange", onResume);
    window.addEventListener("focus", onFocus);
    window.addEventListener("pageshow", onPageShow);
    return () => {
      document.removeEventListener("visibilitychange", onResume);
      window.removeEventListener("focus", onFocus);
      window.removeEventListener("pageshow", onPageShow);
    };
  }, [syncCurrentChatAfterResume]);

  // Setup multimodal capabilities tracking via custom hook

  // Refresh chat when selectedAgent changes, preserving last active chat per agent
  const prevSelectedAgentRef = useRef(selectedAgent);
  useEffect(() => {
    const prevAgent = prevSelectedAgentRef.current;
    if (prevAgent !== selectedAgent && prevAgent !== undefined) {
      // Session ownership has already advanced: sessionApi subscribes to the
      // agent store and claims the new epoch synchronously with the change,
      // so in-flight results owned by the previous agent are stale by now.

      // Immediately block the queue sender. window.currentSessionId is a
      // global that still holds the PREVIOUS agent's session_id until the
      // SDK finishes reloading. Without this guard, scheduleNextSend could
      // fire during the reload window and send a queued item to the wrong
      // agent's conversation.
      setChatLoading(true);

      // Window identity globals are only rewritten when another session
      // loads, so reset them explicitly — otherwise the new agent inherits
      // the previous agent's session/channel (possibly a deleted channel)
      // and the first message of a fresh chat would carry it.
      sessionApi.resetWindowIdentity();

      // Save current chat ID for the agent we're leaving.
      // Skip temporary local timestamp ids — they are not real backend
      // sessions and should not be restored later.
      const currentChatId =
        chatIdRef.current || lastSessionIdRef.current || undefined;
      if (currentChatId && prevAgent && !isLocalTimestampId(currentChatId)) {
        setLastChatId(prevAgent, currentChatId);
      }

      // Restore last chat ID for the agent we're switching to.
      // Ignore temporary local timestamp ids that may have been persisted
      // before this guard was added.
      const restored = getLastChatId(selectedAgent);
      if (restored && !isLocalTimestampId(restored)) {
        navigateRef.current(buildChatPath(restored), {
          replace: true,
        });
        sessionApi.preferredChatId = restored;
        sessionApi.lastActiveChatId = restored;
      } else {
        navigateRef.current("/chat", { replace: true });
        sessionApi.lastActiveChatId = null;
      }
      // Mark the current session as stale so late-arriving onSessionSelected
      // callbacks from the OLD library instance are suppressed (Bug: after
      // agent switch, old library's in-flight getSession may complete and
      // trigger onSessionSelected for the wrong session).
      staleAutoSelectedIdRef.current =
        lastSessionIdRef.current || chatIdRef.current || null;
      lastSessionIdRef.current = null;

      setRefreshKey((prev) => prev + 1);
    }
    prevSelectedAgentRef.current = selectedAgent;
  }, [selectedAgent, setLastChatId, getLastChatId]);

  const copyResponse = useCallback(
    async (response: CopyableResponse) => {
      try {
        await copyText(extractCopyableText(response));
        message.success(t("common.copied"));
      } catch {
        message.error(t("common.copyFailed"));
      }
    },
    [t],
  );

  const customFetch = useCallback(
    async (data: {
      input?: Array<Record<string, unknown>>;
      biz_params?: Record<string, unknown>;
      signal?: AbortSignal;
    }): Promise<Response> => {
      if (chatReadOnly) {
        message.warning(
          t(
            conversationReadOnly
              ? "chat.sharedReadOnlyNotice"
              : "chat.historicalReadOnlyNotice",
          ),
        );
        return new Response(
          JSON.stringify({ detail: "historical_read_only" }),
          {
            status: 403,
            headers: { "Content-Type": "application/json" },
          },
        );
      }
      const headers: Record<string, string> = {
        "Content-Type": "application/json",
        ...buildAuthHeaders(),
      };

      if (usesQwenPawBackend) {
        try {
          const activeModels = await loadConversationModel();
          if (
            !activeModels?.active_llm?.provider_id ||
            !activeModels?.active_llm?.model
          ) {
            pendingSenderClearRef.current = null;
            setShowModelPrompt(true);
            return buildModelError();
          }
        } catch {
          pendingSenderClearRef.current = null;
          setShowModelPrompt(true);
          return buildModelError();
        }
      }

      const submittedValue = pendingSenderClearRef.current;
      if (submittedValue !== null) {
        clearSubmittedSenderInput(submittedValue);
        pendingSenderClearRef.current = null;
        localStorage.removeItem(getDraftStorageKey(selectedAgent));
      }

      const { input = [], biz_params } = data;
      const session: SessionInfo = input[input.length - 1]?.session || {};
      const lastInput = input.slice(-1);
      const lastMsg = lastInput[0];
      const clientMessageId =
        lastMsg?.role === "user" ? createClientMessageId() : undefined;
      const rewrittenLastMsg: Record<string, unknown> | undefined = lastMsg
        ? clientMessageId
          ? attachClientMessageId(lastMsg, clientMessageId)
          : lastMsg
        : undefined;
      const normalizedInput: Array<Record<string, unknown>> =
        rewrittenLastMsg?.content && Array.isArray(rewrittenLastMsg.content)
          ? [
              {
                ...rewrittenLastMsg,
                content: rewrittenLastMsg.content.map(normalizeContentUrls),
              },
            ]
          : rewrittenLastMsg
          ? [rewrittenLastMsg]
          : [];
      const mentionRewrite =
        rewritePersonalLibraryMentionsInInput(normalizedInput);
      const fileRewrite = rewriteFileMentions(mentionRewrite.input);
      const rewrittenInput = fileRewrite.input;
      const personalLibraryDocumentIds = [
        ...new Set(mentionRewrite.documentIds),
      ];

      const identity = sessionApi.getSessionIdentity();
      let requestBody: Record<string, unknown> = {
        input: rewrittenInput,
        session_id: identity.sessionId || session?.session_id || "",
        user_id: identity.userId || session?.user_id || DEFAULT_USER_ID,
        channel: identity.channel || session?.channel || DEFAULT_CHANNEL,
        stream: true,
        ...biz_params,
      };
      const requestedModel = draftModel();
      if (requestedModel) requestBody.requested_model = requestedModel;

      for (const entry of sortByOrder(
        extLists[ChatList.requestPayloadTransforms],
      )) {
        const next = entry.item.transform({
          payload: requestBody,
          sessionId: String(requestBody.session_id || ""),
          selectedAgent,
        });
        if (next && typeof next === "object") {
          requestBody = next;
        }
      }

      let projectSessionId: string | null = null;
      let appliedProjectDir: string | null = null;

      if (clientMessageId && Array.isArray(requestBody.input)) {
        const requestInput = [...requestBody.input] as Array<
          Record<string, unknown>
        >;
        for (let i = requestInput.length - 1; i >= 0; i--) {
          if (requestInput[i]?.role !== "user") continue;
          requestInput[i] = attachClientMessageId(
            requestInput[i],
            clientMessageId,
          );
          requestBody.input = requestInput;
          break;
        }
      }
      if (usesQwenPawBackend) {
        applyApprovalLevelToRequestBody(
          requestBody,
          sessionApprovalLevelRef.current,
          runningConfigApprovalLevel,
        );
        projectSessionId =
          sessionApi.lastActiveChatId ??
          chatIdRef.current ??
          String(requestBody.session_id || "new");
        const pendingRequest = withPendingProjectDirectory(
          requestBody,
          selectedAgent,
          projectSessionId,
        );
        requestBody = pendingRequest.requestBody;
        appliedProjectDir = pendingRequest.projectDir ?? null;
        if (
          personalLibraryDocumentIds.length > 0 ||
          fileRewrite.references.length > 0
        ) {
          const currentContext =
            requestBody.request_context &&
            typeof requestBody.request_context === "object"
              ? (requestBody.request_context as Record<string, unknown>)
              : {};
          requestBody.request_context = {
            ...currentContext,
            file_references: [
              ...fileRewrite.references,
              ...personalLibraryDocumentIds.map((id) => ({
                source: "personal_library",
                id,
              })),
            ],
          };
        }
      } else if (Object.keys(backendControlsRef.current).length > 0) {
        const currentContext =
          requestBody.request_context &&
          typeof requestBody.request_context === "object"
            ? (requestBody.request_context as Record<string, unknown>)
            : {};
        requestBody.request_context = {
          ...currentContext,
          backend_controls: backendControlsRef.current,
        };
      }

      const backendChatId =
        sessionApi.getRealIdForSession(String(requestBody.session_id || "")) ??
        chatIdRef.current ??
        String(requestBody.session_id || "");
      const existingConversationId = resolveBackendChatId(backendChatId);
      if (existingConversationId) {
        requestBody.conversation_id = existingConversationId;
      }
      if (backendChatId) {
        const userText = rewrittenInput
          .filter((m) => m.role === "user")
          .map(extractUserMessageText)
          .join("\n")
          .trim();
        if (userText) {
          // Also pass the full content array so patchLastUserMessage can
          // rebuild user card with images/files when reconnecting.
          const lastUserMsg = rewrittenInput
            .filter((m) => m.role === "user")
            .slice(-1)[0];
          const contentArr = Array.isArray(lastUserMsg?.content)
            ? (lastUserMsg.content as Array<{
                type: string;
                [key: string]: unknown;
              }>)
            : undefined;
          sessionApi.setLastUserMessage(
            backendChatId,
            userText,
            contentArr,
            clientMessageId,
          );
        }
      }

      headlineStreamFilterRef.current = createHeadlineFilterState();

      const requestOwner = sessionApi.getActiveOwner();
      const sentLocalId = sessionApi.lastActiveChatId ?? chatIdRef.current;
      const transportSignal =
        chatTransportLifecycleRef.current.begin(data.signal);
      const response = await fetch(getApiUrl("/console/chat"), {
        method: "POST",
        headers,
        body: JSON.stringify(requestBody),
        signal: transportSignal,
      });

      if (!response.ok && backendChatId) {
        sessionApi.discardLastUserMessage(backendChatId, clientMessageId);
      }

      const localIdToResolve = sentLocalId;
      if (response.ok && localIdToResolve) {
        if (appliedProjectDir && projectSessionId) {
          setPendingProjectDirectory(selectedAgent, projectSessionId, null);
        }
        const resolvedId = response.headers.get("X-QwenPaw-Chat-Id");
        if (resolvedId)
          sessionApi.acceptResolvedChat(
            localIdToResolve,
            resolvedId,
            requestOwner,
          );
        else sessionApi.triggerResolve(localIdToResolve);
      }

      return wrapChatResponseUsageStream(response, chatRef);
    },
    [
      extLists,
      chatReadOnly,
      conversationReadOnly,
      message,
      selectedAgent,
      runningConfigApprovalLevel,
      t,
      usesQwenPawBackend,
    ],
  );

  const handleFileUpload = useCallback(
    async (options: {
      file: File;
      onSuccess: (body: { url?: string; thumbUrl?: string }) => void;
      onError?: (e: Error) => void;
      onProgress?: (e: { percent?: number }) => void;
    }) => {
      const { file, onSuccess, onError, onProgress } = options;
      try {
        // Warn when model has no multimodal support
        if (usesQwenPawBackend && !multimodalCaps.supportsMultimodal) {
          message.warning(t("chat.attachments.multimodalWarning"));
        } else if (
          multimodalCaps.supportsImage &&
          !multimodalCaps.supportsVideo &&
          !file.type.startsWith("image/")
        ) {
          // Warn (not block) when only image is supported
          message.warning(t("chat.attachments.imageOnlyWarning"));
        }
        const sizeMb = file.size / 1024 / 1024;
        const uploadLimit = useUploadLimitStore.getState().uploadMaxSizeMb;
        if (uploadLimit !== null && sizeMb > uploadLimit) {
          message.error(
            t("chat.attachments.fileSizeExceeded", {
              limit: uploadLimit,
              size: sizeMb.toFixed(2),
            }),
          );
          onError?.(new Error(`File size exceeds ${uploadLimit}MB`));
          return;
        }

        const res = await chatApi.uploadFile(
          file,
          resolveBackendChatId(chatIdRef.current ?? chatId),
        );
        onProgress?.({ percent: 100 });
        const previewUrl = chatApi.filePreviewUrl(res.url);
        onSuccess({ url: previewUrl });
        // Track uploaded file for queue attachment support
        pendingFileListRef.current = [
          ...pendingFileListRef.current,
          {
            uid: res.url,
            name: file.name,
            url: previewUrl,
            type: file.type,
            size: file.size,
          },
        ];
      } catch (e) {
        onError?.(e instanceof Error ? e : new Error(String(e)));
      }
    },
    [chatId, multimodalCaps, t, usesQwenPawBackend],
  );

  const compactSender = filesDrawerState.kind === "workspace";
  const chatMessagesAreaRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const root = chatMessagesAreaRef.current;
    if (!root) return;

    const handleMessagesWheel = (event: WheelEvent) => {
      const handled = scrollReverseMessageList(
        root,
        event.target,
        event.deltaY,
        event.deltaMode,
      );
      if (handled) event.preventDefault();
    };

    root.addEventListener("wheel", handleMessagesWheel, {
      capture: true,
      passive: false,
    });
    return () => {
      root.removeEventListener("wheel", handleMessagesWheel, true);
    };
  }, []);

  const options = useMemo(() => {
    const i18nConfig = getDefaultConfig(t);
    const handleBeforeSubmit = async () => {
      if (chatReadOnly) {
        message.warning(
          t(
            conversationReadOnly
              ? "chat.sharedReadOnlyNotice"
              : "chat.historicalReadOnlyNotice",
          ),
        );
        return false;
      }
      if (isComposingRef.current) return false;
      // Single-tab ownership: non-owner tabs are queue-only. Re-route every
      // submit (Enter / send button / programmatic) to the shared queue and
      // abort the actual SDK send. The owner tab will pick the item up via
      // cross-tab broadcast and send it.
      if (!isOwnerRef.current) {
        const textarea = getActiveSenderTextarea();
        const val = textarea?.value.trim() ?? "";
        if (!val) return false;
        const currentQ = useMessageQueueStore
          .getState()
          .getQueue(queueSessionId);
        if (currentQ.length >= MAX_QUEUE_SIZE) {
          message.warning(t("chat.queue.queueFull", { max: MAX_QUEUE_SIZE }));
          return false;
        }
        const queueText = usesQwenPawBackend
          ? prepareLoopModeMessage(val)
          : val;
        const enqueueIdentity = sessionApi.getSessionIdentity();
        useMessageQueueStore.getState().enqueue(queueSessionId, {
          text: queueText,
          attachments:
            pendingFileListRef.current.length > 0
              ? pendingFileListRef.current.map((f) => ({
                  url: f.url,
                  name: f.name,
                  type: f.type,
                  size: f.size,
                }))
              : undefined,
          userId: enqueueIdentity.userId,
          channel: enqueueIdentity.channel,
        });
        pendingFileListRef.current = [];
        if (textarea) setTextareaValue(textarea, "");
        // Clear sender attachment preview (deferred to next tick)
        clearSenderAttachments();
        localStorage.removeItem(getDraftStorageKey(selectedAgent));
        draftSuppressed = true;
        return false;
      }
      localStorage.removeItem(getDraftStorageKey(selectedAgent));
      draftSuppressed = true;
      // Clear pending attachments when sending directly (not through queue)
      pendingFileListRef.current = [];

      const textarea = getActiveSenderTextarea();
      if (textarea) {
        const prepared = usesQwenPawBackend
          ? beginLoopModeSubmission(textarea.value)
          : textarea.value;
        if (prepared !== textarea.value) {
          setTextareaValue(textarea, prepared);
        }
        pendingSenderClearRef.current = prepared;
      }

      return true;
    };

    // ── Resolve plugin extension snapshots ────────────────────────────────
    const locale = i18n.language;
    const extGreeting = resolveLocalized(
      extScalar[ChatScalar.welcomeGreeting]?.value,
      locale,
    );
    const extDescription = resolveLocalized(
      extScalar[ChatScalar.welcomeDescription]?.value,
      locale,
    );
    const extAvatar = resolveLocalized(
      extScalar[ChatScalar.welcomeAvatar]?.value,
      locale,
    );
    const extNick = resolveLocalized(
      extScalar[ChatScalar.welcomeNick]?.value,
      locale,
    );
    const extPrompts = resolveLocalized(
      extScalar[ChatScalar.welcomePrompts]?.value,
      locale,
    );
    const extLeftTitle = resolveLocalized(
      extScalar[ChatScalar.headerLeftTitle]?.value,
      locale,
    );
    const extLeftLogo = resolveLocalized(
      extScalar[ChatScalar.headerLeftLogo]?.value,
      locale,
    );
    const extColorPrimary = extScalar[ChatScalar.themeColorPrimary]?.value;
    const extPlaceholder = resolveLocalized(
      extScalar[ChatScalar.senderPlaceholder]?.value,
      locale,
    );
    const extDisclaimer = resolveLocalized(
      extScalar[ChatScalar.senderDisclaimer]?.value,
      locale,
    );

    // Whole-section render overrides (plugin can fully replace welcome / leftHeader)
    const extWelcomeRenderEntry = extScalar[ChatScalar.welcomeRender];
    const extWelcomeRender = extWelcomeRenderEntry?.value;
    const extLeftHeaderRenderEntry =
      extScalar[ChatScalar.headerLeftHeaderRender];
    const extLeftHeaderRender = extLeftHeaderRenderEntry?.value;

    const wrappedWelcomeRender = extWelcomeRender
      ? (props: WelcomeRenderProps) => (
          <PluginSlotBoundary
            slot={ChatScalar.welcomeRender}
            pluginId={extWelcomeRenderEntry!.pluginId}
          >
            {extWelcomeRender(props)}
          </PluginSlotBoundary>
        )
      : undefined;

    const pluginRightHeader = sortByOrder(extLists[ChatList.rightHeader]).map(
      (e) => (
        <PluginSlotBoundary
          key={e.item.id}
          slot={ChatList.rightHeader}
          pluginId={e.pluginId}
        >
          {e.item.node}
        </PluginSlotBoundary>
      ),
    );
    const pluginSenderPrefix = sortByOrder(extLists[ChatList.senderPrefix]).map(
      (e) => (
        <PluginSlotBoundary
          key={e.item.id}
          slot={ChatList.senderPrefix}
          pluginId={e.pluginId}
        >
          {e.item.node}
        </PluginSlotBoundary>
      ),
    );
    // Plugin suggestions are not part of the server slash catalog. Preserve
    // them in the SDK while built-in slash candidates stay exclusively in the
    // custom positioned menu.
    const pluginSuggestions = extLists[ChatList.senderSuggestions].flatMap(
      (e) => {
        const resolved = resolveLocalized(e.item.items, locale) ?? [];
        return resolved.map((s) => ({ label: s.label, value: s.value }));
      },
    );
    const activePluginSuggestions = usesQwenPawBackend ? pluginSuggestions : [];
    const wrapActionSpec = (
      pluginId: string,
      slot: string,
      spec: { id: string; icon?: any; render?: any; onClick?: any },
    ) => ({
      icon: spec.icon,
      render: spec.render
        ? (ctx: { data: unknown }) => (
            <PluginSlotBoundary slot={slot} pluginId={pluginId}>
              {spec.render!(ctx)}
            </PluginSlotBoundary>
          )
        : undefined,
      onClick: spec.onClick
        ? (ctx: { data: unknown }) => {
            try {
              spec.onClick!(ctx);
            } catch (err) {
              console.error(
                `[plugin:${pluginId}] action ${spec.id} onClick threw:`,
                err,
              );
            }
          }
        : undefined,
    });

    const pluginActions = extLists[ChatList.actions].map((e) =>
      wrapActionSpec(e.pluginId, ChatList.actions, e.item.item),
    );
    const pluginRequestActions = extLists[ChatList.requestActions].map((e) =>
      wrapActionSpec(e.pluginId, ChatList.requestActions, e.item.item),
    );

    const wrapToolFC = (
      pluginId: string,
      toolName: string,
      FC: React.FC<any>,
    ) => {
      const Wrapped: React.FC<any> = (props) => (
        <PluginSlotBoundary
          slot={`customToolRender:${toolName}`}
          pluginId={pluginId}
        >
          <FC {...props} />
        </PluginSlotBoundary>
      );
      return Wrapped;
    };
    const pluginToolRenderers: Record<string, React.FC<any>> = {};
    for (const e of extLists[ChatList.customToolRender]) {
      pluginToolRenderers[e.item.toolName] = wrapToolFC(
        e.pluginId,
        e.item.toolName,
        e.item.render,
      );
    }
    const mergedToolRenderers: Record<string, React.FC<any>> = {
      ...toolRenderConfig,
      ...pluginToolRenderers,
    };

    const pluginCards: Record<string, React.FC<any>> = {};
    for (const e of extLists[ChatList.cards]) {
      pluginCards[e.item.cardName] = wrapToolFC(
        e.pluginId,
        e.item.cardName,
        e.item.render,
      );
    }

    const userMessageAnchorsConfig = {
      ...defaultConfig.theme.bubbleList.userMessageAnchors,
      variant: "navigator" as const,
    };

    // leftHeader: whole-section render wins, otherwise partial merge {logo, title}.
    const mergedLeftHeader: any =
      extLeftHeaderRender !== undefined ? (
        <PluginSlotBoundary
          slot={ChatScalar.headerLeftHeaderRender}
          pluginId={extLeftHeaderRenderEntry!.pluginId}
        >
          {extLeftHeaderRender}
        </PluginSlotBoundary>
      ) : (
        {
          ...defaultConfig.theme.leftHeader,
          ...(extLeftTitle !== undefined ? { title: extLeftTitle } : {}),
          ...(extLeftLogo !== undefined ? { logo: extLeftLogo } : {}),
        }
      );

    return {
      ...i18nConfig,
      theme: {
        ...defaultConfig.theme,
        darkMode: isDark,
        ...(extColorPrimary ? { colorPrimary: extColorPrimary } : {}),
        bubbleList: {
          ...defaultConfig.theme.bubbleList,
          userMessageAnchors: userMessageAnchorsConfig,
        },
        leftHeader: mergedLeftHeader,
        rightHeader: (
          <>
            <ChatSessionInitializer runtimeRef={chatRef} />
            <RuntimeLoadingBridge
              bridgeRef={runtimeLoadingBridgeRef}
              onLoadingChange={setChatLoading}
            />
            <ChatHeaderTitle />
            <span style={{ flex: 1 }} />
            {isPublicationConversation ? (
              <PublicationModelLock
                version={publicationVersion as string}
                providerId={lockedPublicationModel?.provider_id as string}
                model={lockedPublicationModel?.model as string}
              />
            ) : !chatReadOnly && usesQwenPawBackend ? (
              <ModelSelector />
            ) : !chatReadOnly && backendCapabilities?.model_selection ? (
              <HarnessModelSelector providerId={selectedAgentBackend} />
            ) : null}
            <ChatActionGroup
              onToggleWorkspace={toggleFilesWorkspace}
              workspaceOpen={filesWorkspaceOpen}
              onToggleHistory={
                effectiveIsFullMode ? toggleHistoryPanel : undefined
              }
              historyOpen={effectiveIsFullMode ? historyPanelOpen : false}
              isWideMode={isWideMode}
              onToggleWideMode={toggleWideMode}
              readOnly={chatReadOnly}
            />
            <RuntimeReadOnlyBridge readOnly={chatReadOnly} />
            {pluginRightHeader}
          </>
        ),
      },
      welcome: {
        ...i18nConfig.welcome,
        nick: extNick ?? "QwenPaw",
        avatar: extAvatar ?? "/qwenpaw.png",
        ...(extGreeting !== undefined ? { greeting: extGreeting } : {}),
        ...(extDescription !== undefined
          ? { description: extDescription }
          : {}),
        ...(extPrompts !== undefined ? { prompts: extPrompts } : {}),
        // SDK uses `render` if present and ignores the other fields.
        ...(wrappedWelcomeRender ? { render: wrappedWelcomeRender } : {}),
      },
      sender: {
        ...(i18nConfig as any)?.sender,
        beforeSubmit: handleBeforeSubmit,
        allowSpeech: false,
        beforeUI: (
          <>
            {chatReadOnly && (
              <Alert
                type="info"
                showIcon
                banner
                message={t(
                  conversationReadOnly
                    ? "chat.sharedReadOnlyNotice"
                    : "chat.historicalReadOnlyNotice",
                  { owner: currentSession?.sharedBy || "-" },
                )}
              />
            )}
            <TaskInteractionPanel planEnabled={planEnabled} />
            {isQueueOnlyTab && (
              <Alert
                type="info"
                showIcon
                banner
                message={t("chat.queue.otherTabOwner")}
              />
            )}
            {showSenderBeforeUI && (
              <ChatSenderTabsPanel
                bgSessionId={bgBackendSessionId}
                queueSessionId={queueSessionId}
                onRemove={handleQueueRemove}
                onEdit={handleQueueEdit}
                onReorder={handleQueueReorder}
                onInterruptAndSend={handleQueueInterruptAndSend}
                onClear={handleQueueClear}
                onPauseResume={handleQueuePauseResume}
                onRetry={handleQueueRetry}
                onSkip={handleQueueSkip}
              />
            )}
          </>
        ),
        prefix: (
          <>
            {!chatReadOnly && whisperEnabled ? (
              <WhisperSpeechButton
                ref={whisperSpeechRef}
                onTranscription={handleWhisperTranscription}
                getSender={getVoiceSender}
                conversationId={backendChatId}
                contextKey={queueSessionId}
                disabled={chatReadOnly}
              />
            ) : null}
            {!chatReadOnly && usesQwenPawBackend && <LoopModeSelector />}
            {!chatReadOnly && pluginSenderPrefix}
          </>
        ),
        actionAffix: (
          <span
            className={`${styles.senderActionAffix} ${
              compactSender ? styles.compactSenderAffix : ""
            }`}
          >
            {!chatReadOnly &&
              (usesQwenPawBackend || backendCapabilities?.context_usage) && (
                <ContextUsageIndicator
                  onCompact={handleCompactCommand}
                  onNew={handleNewCommand}
                />
              )}
            {!chatReadOnly && usesQwenPawBackend && (
              <SessionProjectDirectory
                scope={sessionScope}
                compact={compactSender}
              />
            )}
            {!chatReadOnly && usesQwenPawBackend ? (
              <ApprovalLevelToggle
                sessionId={queueSessionId}
                runningConfigApprovalLevel={runningConfigApprovalLevel}
                compact={compactSender}
                onChange={(sessionOverride) => {
                  sessionApprovalLevelRef.current = sessionOverride;
                }}
              />
            ) : !chatReadOnly && approvalPresets.length > 0 ? (
              <HarnessApprovalToggle
                backend={selectedAgentBackend}
                sessionId={queueSessionId}
                presets={approvalPresets}
                onChange={(settings) => {
                  backendControlsRef.current = settings;
                }}
              />
            ) : null}
          </span>
        ),
        ...(!chatReadOnly && supportsAttachments
          ? {
              attachments: {
                multiple: true,
                trigger: function (props: any) {
                  const uploadLimit =
                    useUploadLimitStore.getState().uploadMaxSizeMb;
                  const tooltipKey = multimodalCaps.supportsMultimodal
                    ? multimodalCaps.supportsImage &&
                      !multimodalCaps.supportsVideo
                      ? "chat.attachments.tooltipImageOnly"
                      : "chat.attachments.tooltip"
                    : "chat.attachments.tooltipNoMultimodal";
                  const tooltipTitle =
                    uploadLimit !== null
                      ? `${t(tooltipKey)}, ${t(
                          "chat.attachments.fileSizeLimit",
                          {
                            limit: uploadLimit,
                          },
                        )}`
                      : t(tooltipKey);
                  return (
                    <Tooltip title={tooltipTitle}>
                      <IconButton
                        disabled={props?.disabled}
                        icon={<SparkAttachmentLine />}
                        bordered={false}
                      />
                    </Tooltip>
                  );
                },
                customRequest: handleFileUpload,
              },
              longTextUpload: {
                ...((i18nConfig as any)?.sender?.longTextUpload ?? {}),
                customRequest: handleFileUpload,
                prompt: () =>
                  t(
                    "chat.longTextUploadPrompt",
                    "Please read the uploaded prompt file and answer it.",
                  ),
              },
            }
          : {}),
        placeholder: chatReadOnly
          ? t(
              conversationReadOnly
                ? "chat.sharedReadOnlyPlaceholder"
                : "chat.historicalReadOnlyPlaceholder",
            )
          : extPlaceholder ?? t("chat.inputPlaceholder"),
        ...(extDisclaimer !== undefined ? { disclaimer: extDisclaimer } : {}),
        // Slash candidates are rendered by the positioned inline menu below.
        // Do not pass them to the SDK sender, otherwise it renders a second
        // centered suggestion popup for the same "/" input.
        suggestions: activePluginSuggestions,
      },
      session: {
        multiple: true,
        hideBuiltInSessionList: true,
        api: sessionApi,
      },
      api: {
        ...defaultConfig.api,
        fetch: customFetch,
        responseParser: (chunk: string) => {
          const payload = JSON.parse(chunk) as Record<string, unknown>;
          markLoopModeRunning();
          sanitizeHeadlinePayload(payload, headlineStreamFilterRef.current);

          if (payloadCompletesResponse(payload)) {
            const trailing = flushHeadlineFilter(
              headlineStreamFilterRef.current,
            );
            headlineStreamFilterRef.current = createHeadlineFilterState();
            const output = payload.output;
            // A completed response normally carries canonical full output,
            // which already contains any ordinary trailing prefix. Use the
            // flushed delta only when that canonical output is absent, so it
            // is neither lost nor duplicated.
            if (!output || (Array.isArray(output) && output.length === 0)) {
              const errorMsg =
                (payload.error as any)?.message || t("chat.emptyOutputError");
              payload.output = [
                {
                  type: "message",
                  role: "assistant",
                  content: [{ type: "text", text: trailing || errorMsg }],
                },
              ];
            }
          }

          if (payload.type === "turn_usage") {
            return null;
          }

          // Replay boundary marker from the reconnect stream. The
          // fast-forward wrapper strips it at the byte level; if one
          // still slips through, map it to the SDK's heartbeat no-op —
          // returning null here would crash the response builder
          // mid-stream and drop every subsequent live token.
          if (payload.type === "replay_end") {
            return { object: "message", type: "heartbeat" } as any;
          }

          if (payload.type === "rate_limited") {
            const alts =
              (payload.alternatives as typeof rateLimitAlternatives) || [];
            const modelContext = currentModelContext();
            void modelCatalogApi
              .list(selectedAgent)
              .then((catalog) => {
                if (!isCurrentModelContext(modelContext)) return;
                setRateLimitAlternatives(
                  alts.filter((alt) =>
                    catalog.models.some(
                      (model) =>
                        model.provider_id === alt.provider_id &&
                        model.model === alt.model_id,
                    ),
                  ),
                );
              })
              .catch(() => {
                if (isCurrentModelContext(modelContext))
                  setRateLimitAlternatives([]);
              });
            message.warning(t("chat.rateLimitHit"));
            return null;
          }

          if (payloadRequestsHistoryClear(payload)) {
            pendingClearHistoryRef.current = true;
            if (payloadCompletesResponse(payload)) {
              scheduleHistoryClear();
            }
          }

          return payload as any;
        },
        replaceMediaURL: (url: string) => {
          return toDisplayUrl(url);
        },
        onFileCardClick,
        cancel(data: { session_id: string }) {
          const resolvedChatId = resolveStopChatId(
            data.session_id,
            (sessionId) => sessionApi.getRealIdForSession(sessionId),
          );
          if (resolvedChatId) {
            chatApi.stopChat(resolvedChatId).catch((err) => {
              console.error("Failed to stop chat:", err);
            });
          }
        },
        async reconnect(data: { session_id: string; signal?: AbortSignal }) {
          const headers: Record<string, string> = {
            "Content-Type": "application/json",
            ...buildAuthHeaders(),
          };

          const reconnectIdentity = sessionApi.getSessionIdentity();
          const reconnectConversationId = resolveBackendChatId(
            sessionApi.getRealIdForSession(data.session_id) ?? data.session_id,
          );
          headlineStreamFilterRef.current = createHeadlineFilterState();
          const response = await fetch(getApiUrl("/console/chat"), {
            method: "POST",
            headers,
            body: JSON.stringify(
              createReconnectRequestPayload({
                backendSessionId: sessionApi.getBackendSessionId(
                  data.session_id,
                ),
                userId: reconnectIdentity.userId,
                channel: reconnectIdentity.channel,
                conversationId: reconnectConversationId,
              }),
            ),
            signal: data.signal,
          });

          // Fast-forward the replayed section: render the already
          // generated part instantly instead of re-animating it.
          return wrapChatResponseUsageStream(
            wrapReplayFastForward(response),
            chatRef,
          );
        },
      },
      customToolRenderConfig: withGenericFallback(mergedToolRenderers),
      cards: {
        // Host wrappers that delegate to vendor defaults when no plugin
        // request/response render/prepend/append is registered — and
        // compose plugin slots otherwise.
        AgentScopeRuntimeRequestCard: HostRequestCard,
        AgentScopeRuntimeResponseCard: HostResponseCard,
        ...pluginCards,
      },
      actions: {
        list: [
          {
            icon: (
              <span title={t("common.copy")}>
                <SparkCopyLine />
              </span>
            ),
            onClick: ({ data }: { data: CopyableResponse }) => {
              void copyResponse(data);
            },
          },
          {
            render: ({
              data,
            }: {
              data: { data?: { created_at?: number; completed_at?: number } };
            }) => {
              return (
                <span style={timestampStyle}>
                  {formatMessageTime(
                    data?.data?.completed_at ?? data?.data?.created_at ?? 0,
                  )}
                </span>
              );
            },
          },
          ...pluginActions,
        ],
        replace: true,
        right: false,
      },
      requestActions: {
        list: [
          {
            render: ({ data }: { data: { created_at?: number } }) => {
              return (
                <span style={timestampStyle}>
                  {formatMessageTime(data?.created_at ?? 0)}
                </span>
              );
            },
          },
          {
            icon: <SparkCopyLine />,
            onClick: ({ data }: { data: { input?: any[] } }) => {
              const text = (data?.input || [])
                .map(extractUserMessageText)
                .join("\n")
                .trim();
              if (text) {
                void copyText(text)
                  .then(() => message.success(t("common.copied")))
                  .catch(() => message.error(t("common.copyFailed")));
              }
            },
          },
          ...pluginRequestActions,
        ],
      },
    } as unknown as IAgentScopeRuntimeWebUIOptions;
  }, [
    customFetch,
    copyResponse,
    handleFileUpload,
    t,
    i18n.language,
    isDark,
    multimodalCaps,
    toolRenderConfig,
    extScalar,
    extLists,
    scheduleHistoryClear,
    planEnabled,
    selectedAgent,
    selectedAgentBackend,
    backendCapabilities,
    approvalPresets,
    usesQwenPawBackend,
    supportsAttachments,
    runningConfigApprovalLevel,
    queueSessionId,
    onFileCardClick,
    whisperEnabled,
    handleWhisperTranscription,
    getVoiceSender,
    backendChatId,
    isWideMode,
    toggleWideMode,
    hasQueueItems,
    isQueueOnlyTab,
    handleQueueRemove,
    handleQueueEdit,
    handleQueueReorder,
    handleQueueInterruptAndSend,
    handleQueueClear,
    handleQueuePauseResume,
    handleQueueRetry,
    handleQueueSkip,
    effectiveIsFullMode,
    historyPanelOpen,
    toggleHistoryPanel,
    handleCompactCommand,
    handleNewCommand,
    compactSender,
    sessionScope,
    filesWorkspaceOpen,
    toggleFilesWorkspace,
    isOwner,
    bgTaskCount,
    bgBackendSessionId,
    queueSessionId,
    chatReadOnly,
    conversationReadOnly,
    currentSession?.sharedBy,
  ]);

  const filesDrawerClass =
    filesDrawerState.kind === "closed"
      ? ""
      : filesDrawerState.kind === "preview"
      ? styles.filesPreviewOpen
      : styles.filesWorkspaceOpen;

  return (
    <div
      className={`${styles.chatPageRoot} ${filesDrawerClass}`}
      onClickCapture={handleInternalFileLink}
    >
      <AnimatePresence initial={false} mode="popLayout">
        {filesDrawerState.kind !== "closed" ? (
          <FilesDrawer
            key="session-files-drawer"
            state={filesDrawerState}
            dispatch={dispatchFilesDrawer}
            scope={sessionScope}
          />
        ) : null}
      </AnimatePresence>
      {/* Main chat area */}
      <motion.div
        className={styles.chatMainArea}
        layout={prefersReducedMotion ? false : "size"}
        transition={
          prefersReducedMotion
            ? { duration: 0 }
            : {
                layout: {
                  type: "spring",
                  stiffness: 360,
                  damping: 38,
                  mass: 0.82,
                },
              }
        }
      >
        <div
          ref={chatMessagesAreaRef}
          className={
            isWideMode
              ? `${styles.chatMessagesArea} ${styles.wideMode}`
              : styles.chatMessagesArea
          }
        >
          <RichFileReferenceInputProvider
            onOpenReference={(reference, trigger) =>
              void openInlineFileReference(reference, trigger)
            }
          >
            <AgentScopeRuntimeWebUI
              ref={chatRef}
              key={refreshKey}
              options={options}
            />
          </RichFileReferenceInputProvider>
        </div>

        {slashMenu.open && filteredSlashSuggestions.length > 0 && (
          <div
            ref={slashMenuRef}
            className={styles.inlineSlashMenu}
            style={{
              left: slashMenu.left,
              bottom: slashMenu.bottom,
            }}
            onMouseDown={(event) => event.preventDefault()}
          >
            {filteredSlashSuggestions.map((item, index) => (
              <button
                ref={(element) => {
                  slashItemRefs.current[index] = element;
                }}
                key={`${item.command}:${item.value}`}
                type="button"
                className={`${styles.inlineSlashItem} ${
                  index === slashMenu.activeIndex
                    ? styles.inlineSlashItemActive
                    : ""
                }`}
                onMouseEnter={() =>
                  setSlashMenu((current) => ({
                    ...current,
                    activeIndex: index,
                  }))
                }
                onClick={() => applySlashSuggestion(item)}
              >
                {renderSuggestionLabel(item)}
              </button>
            ))}
          </div>
        )}

        {mentionMenu.open && (
          <div
            className={styles.inlineSlashMenu}
            style={{ left: mentionMenu.left, bottom: mentionMenu.bottom }}
            onMouseDown={(event) => event.preventDefault()}
          >
            <div className={styles.suggestionDescription}>
              临时文件 · 个人资料库 · Agent资料 · 产物（可读取的文本文件）
            </div>
            {filteredPersonalLibraryDocuments.length === 0 && (
              <div className={styles.suggestionDescription}>
                未找到可引用文件，请检查文件名、资料库授权和当前会话。
              </div>
            )}
            {filteredPersonalLibraryDocuments.map((document, index) => (
              <button
                key={`${document.source}:${document.id}`}
                type="button"
                className={`${styles.inlineSlashItem} ${
                  index === mentionMenu.activeIndex
                    ? styles.inlineSlashItemActive
                    : ""
                }`}
                onMouseEnter={() =>
                  setMentionMenu((current) => ({
                    ...current,
                    activeIndex: index,
                  }))
                }
                onClick={() => applyPersonalLibraryMention(document)}
              >
                <div className={styles.suggestionLabel}>
                  <div className={styles.suggestionMain}>
                    <span className={styles.suggestionCommand}>
                      @{document.name}
                    </span>
                    <span className={styles.suggestionGroup}>
                      {sourceLabels[document.source]}
                    </span>
                  </div>
                  <div className={styles.suggestionDescription}>
                    {document.relative_path}
                  </div>
                </div>
              </button>
            ))}
          </div>
        )}

        {/* Rate-limit guidance banner */}
        {usesQwenPawBackend && rateLimitAlternatives.length > 0 && (
          <div className={styles.rateLimitBanner}>
            <span className={styles.rateLimitText}>
              {t("chat.rateLimitMessage")}
            </span>
            <div className={styles.rateLimitActions}>
              {rateLimitAlternatives.slice(0, 3).map((alt) => (
                <Button
                  key={`${alt.provider_id}/${alt.model_id}`}
                  size="small"
                  type="default"
                  onClick={async () => {
                    try {
                      await chooseConversationModel({
                        provider_id: alt.provider_id,
                        model: alt.model_id,
                      });
                      window.dispatchEvent(new CustomEvent("model-switched"));
                      message.success(
                        t("chat.rateLimitSwitched", { model: alt.model_name }),
                      );
                      setRateLimitAlternatives([]);
                    } catch {
                      message.error(t("modelSelector.switchFailed"));
                    }
                  }}
                >
                  {alt.model_name}
                </Button>
              ))}
              <Button
                size="small"
                type="link"
                onClick={() => setRateLimitAlternatives([])}
              >
                {t("common.close")}
              </Button>
            </div>
          </div>
        )}

        {/* Render approval cards as overlays */}
        {!chatReadOnly &&
          Array.from(approvalRequests.values()).map((request) => {
            const renderer = approvalRenderers.get(request.sourceType);
            const CustomApprovalCard = renderer?.item.render;
            const defaultApprovalCard = (
              <ApprovalCard
                requestId={request.requestId}
                agentId={request.agentId}
                toolName={request.toolName}
                toolSource={request.toolSource}
                severity={request.severity}
                findingsCount={request.findingsCount}
                findingsSummary={request.findingsSummary}
                toolParams={request.toolParams}
                createdAt={request.createdAt}
                timeoutSeconds={request.timeoutSeconds}
                sessionId={request.sessionId}
                rootSessionId={request.rootSessionId}
                isGeneralized={request.isGeneralized}
                exactTarget={request.exactTarget}
                similarTarget={request.similarTarget}
                onApprove={(reqId, scope) => handleApprove(reqId, scope)}
                onDeny={handleDeny}
                onCancel={() => {
                  const sessionId =
                    request.rootSessionId || window.currentSessionId || "";
                  const resolvedChatId =
                    sessionApi.getRealIdForSession(sessionId) ??
                    chatIdRef.current ??
                    sessionId;

                  if (resolvedChatId) {
                    console.log(
                      "[Chat] Calling stopChat with:",
                      resolvedChatId,
                    );
                    chatApi
                      .stopChat(resolvedChatId)
                      .then(() => {
                        console.log("[Chat] stopChat succeeded");
                        setApprovals((prev) =>
                          prev.filter(
                            (item) =>
                              item.root_session_id !== request.rootSessionId,
                          ),
                        );
                      })
                      .catch((err) => {
                        console.error("[Chat] stopChat failed:", err);
                      });
                  } else {
                    console.warn(
                      "[Chat] No chat_id resolved, cannot cancel task",
                    );
                  }
                }}
              />
            );

            return (
              <div
                key={request.requestId}
                data-approval-id={request.requestId}
                style={{
                  position: "fixed",
                  bottom: 80,
                  right: 24,
                  zIndex: 1000,
                  maxWidth: 480,
                  width: "calc(100vw - 48px)",
                }}
              >
                {CustomApprovalCard ? (
                  <PluginSlotBoundary
                    slot={`approval:${request.sourceType}`}
                    pluginId={renderer.pluginId}
                    fallback={defaultApprovalCard}
                  >
                    <CustomApprovalCard
                      approval={request}
                      onResolved={() => dismissApproval(request.requestId)}
                    />
                  </PluginSlotBoundary>
                ) : (
                  defaultApprovalCard
                )}
              </div>
            );
          })}

        <Modal
          open={usesQwenPawBackend && showModelPrompt}
          closable={false}
          footer={null}
          width={480}
          styles={{
            content: isDark
              ? {
                  background: "#1f1f1f",
                  boxShadow: "0 8px 32px rgba(0,0,0,0.5)",
                }
              : undefined,
          }}
        >
          <Result
            icon={<ExclamationCircleOutlined style={{ color: "#faad14" }} />}
            title={
              <span
                style={{ color: isDark ? "rgba(255,255,255,0.88)" : undefined }}
              >
                {t("modelConfig.promptTitle")}
              </span>
            }
            subTitle={
              <span
                style={{ color: isDark ? "rgba(255,255,255,0.55)" : undefined }}
              >
                {t("modelConfig.promptMessage")}
              </span>
            }
            extra={[
              <Button key="skip" onClick={() => setShowModelPrompt(false)}>
                {t("modelConfig.skipButton")}
              </Button>,
              canManageModels && (
                <Button
                  key="configure"
                  type="primary"
                  icon={<SettingOutlined />}
                  onClick={() => {
                    setShowModelPrompt(false);
                    navigate("/models");
                  }}
                >
                  {t("modelConfig.configureButton")}
                </Button>
              ),
            ]}
          />
        </Modal>
      </motion.div>
      {/* End of main chat area */}

      {/* Right-side history panel (full mode only) */}
      {effectiveIsFullMode && historyPanelOpen && (
        <>
          {isMobile ? (
            <ChatSessionDrawer
              open={historyPanelOpen}
              onClose={toggleHistoryPanel}
              embedded={false}
            />
          ) : (
            <>
              <div
                className={styles.historyPanelMask}
                onClick={toggleHistoryPanel}
              />
              <div className={styles.historyPanel}>
                <ChatSessionDrawer
                  open={historyPanelOpen}
                  onClose={toggleHistoryPanel}
                  embedded
                />
              </div>
            </>
          )}
        </>
      )}
    </div>
  );
}
