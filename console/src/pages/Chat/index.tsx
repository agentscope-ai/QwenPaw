import {
  AgentScopeRuntimeWebUI,
  IAgentScopeRuntimeWebUIOptions,
  type IAgentScopeRuntimeWebUIRef,
} from "@agentscope-ai/chat";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Button, Modal, Result, Tooltip } from "antd";
import { useAppMessage } from "../../hooks/useAppMessage";
import { ExclamationCircleOutlined, SettingOutlined } from "@ant-design/icons";
import { SparkCopyLine, SparkAttachmentLine } from "@agentscope-ai/icons";
import { usePlugins } from "../../plugins/PluginContext";
import { useTranslation } from "react-i18next";
import i18n from "../../i18n";
import { useLocation, useNavigate } from "react-router-dom";
import sessionApi from "./sessionApi";
import defaultConfig, { getDefaultConfig } from "./OptionsPanel/defaultConfig";
import { chatApi } from "../../api/modules/chat";
import { agentApi } from "../../api/modules/agent";
import { skillApi } from "../../api/modules/skill";
import { getApiUrl } from "../../api/config";
import { buildAuthHeaders } from "../../api/authHeaders";
import { providerApi } from "../../api/modules/provider";
import type { ProviderInfo, ModelInfo, SkillSpec } from "../../api/types";
import ModelSelector from "./ModelSelector";
import { useTheme } from "../../contexts/ThemeContext";
import { useAgentStore } from "../../stores/agentStore";
import { useCodingMode } from "../../stores/codingModeStore";
import { useChatAnywhereInput } from "@agentscope-ai/chat";
import styles from "./index.module.less";
import { IconButton } from "@agentscope-ai/design";
import ChatActionGroup from "./components/ChatActionGroup";
import ChatSessionDrawer from "./components/ChatSessionDrawer";
import { useSidebarModeStore } from "../../stores/sidebarModeStore";
import TurnUsageAction from "./components/TurnUsageAction";
import {
  patchContextMaxInputLength,
  wrapChatResponseUsageStream,
} from "./turnUsage";
import ChatHeaderTitle from "./components/ChatHeaderTitle";
import ChatSessionInitializer from "./components/ChatSessionInitializer";
import { ApprovalCard } from "../../components/ApprovalCard/ApprovalCard";
import { commandsApi } from "../../api/modules/commands";
import { useApprovalContext } from "../../contexts/ApprovalContext";
import { planApi } from "../../api/modules/plan";
import {
  useChatScalarSnapshot,
  useChatListSnapshot,
} from "../../plugins/registry/useChatExtensions";
import { PluginSlotBoundary } from "../../plugins/registry/PluginSlotBoundary";
import {
  resolveLocalized,
  type WelcomeRenderProps,
} from "../../plugins/registry/types";
import { ChatScalar, ChatList } from "../../plugins/registry/slotKeys";
import { HostRequestCard, HostResponseCard } from "./HostBubbles";
import { withGenericFallback } from "../../components/Chat/ToolCards/adapters/v1Adapter";

interface ApprovalMessageData {
  requestId: string;
  sessionId: string;
  rootSessionId?: string;
  agentId: string;
  toolName: string;
  severity: string;
  findingsCount: number;
  findingsSummary: string;
  toolParams: Record<string, unknown>;
  createdAt: number;
  timeoutSeconds: number;
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
  setTextareaValue,
  formatMessageTime,
  type CopyableResponse,
  type RuntimeLoadingBridgeApi,
} from "./utils";
import {
  getSessionIdFromPath,
  buildBasePath,
  buildSessionPath,
  type SessionRouteMode,
} from "../../utils/sessionRoute";
import { openExternalLink } from "../../utils/openExternalLink";
import { getLastEditorCopy } from "../Coding/lastEditorCopy";
import { useUploadLimitStore } from "../../stores/uploadLimitStore";
import MessageQueuePanel from "./components/MessageQueuePanel";
import {
  useMessageQueueStore,
  type QueueItem,
  MAX_QUEUE_SIZE,
  STORAGE_PREFIX,
  withSendLock,
  holdOwnershipLock,
} from "../../stores/messageQueueStore";

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
        sessionApi.setLastUserMessage(chatIdForStatus, item.text, contentItems);
      }

      let fetchSucceeded = false;
      // True once fetch() has resolved with an HTTP response. For a streaming
      // chat endpoint, this means the backend has already accepted the
      // request and started generating — the backend keeps producing the turn
      // and the foreground SDK's reconnect will pick it up.
      let fetchStarted = false;
      try {
        const authHeaders = buildAuthHeaders();
        // Use the agent ID captured at enqueue time to prevent cross-agent
        // delivery when the user switches agents after queueing.
        if (item.agentId) {
          authHeaders["X-Agent-Id"] = item.agentId;
        }
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
          body: JSON.stringify({
            input: [
              {
                role: "user",
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
          }),
        });

        if (!res.ok) throw new Error(`HTTP ${res.status}`);
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
  for (let i = 0; i < localStorage.length; i++) {
    const key = localStorage.key(i);
    if (!key || !key.startsWith(STORAGE_PREFIX)) continue;
    const sessionId = key.slice(STORAGE_PREFIX.length);
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

function renderSuggestionLabel(command: string, description?: string) {
  return (
    <div
      className={`${styles.suggestionLabel} ${
        description ? "" : styles.suggestionLabelCompact
      }`}
    >
      <span className={styles.suggestionCommand}>{command}</span>
      {description ? (
        <span className={styles.suggestionDescription}>{description}</span>
      ) : null}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const DEFAULT_USER_ID = "default";
const DEFAULT_CHANNEL = "console";
const WIDE_MODE_STORAGE_KEY = "qwenpaw_chat_wide_mode";

function isSkillAvailableInConsole(skill: SkillSpec): boolean {
  if (!skill.enabled) return false;
  const channels = skill.channels?.length ? skill.channels : ["all"];
  return channels.includes("all") || channels.includes(DEFAULT_CHANNEL);
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
    try {
      const [providers, activeModels] = await Promise.all([
        providerApi.listProviders(),
        providerApi.getActiveModels({
          scope: "effective",
          agent_id: selectedAgent,
        }),
      ]);
      const activeProviderId = activeModels?.active_llm?.provider_id;
      const activeModelId = activeModels?.active_llm?.model;
      if (!activeProviderId || !activeModelId) {
        updateCapsIfChanged(noCaps);
        return;
      }
      const provider = (providers as ProviderInfo[]).find(
        (p) => p.id === activeProviderId,
      );
      if (!provider) {
        updateCapsIfChanged(noCaps);
        return;
      }
      const allModels: ModelInfo[] = [
        ...(provider.models ?? []),
        ...(provider.extra_models ?? []),
      ];
      const model = allModels.find((m) => m.id === activeModelId);
      updateCapsIfChanged({
        supportsMultimodal: model?.supports_multimodal ?? false,
        supportsImage: model?.supports_image ?? false,
        supportsVideo: model?.supports_video ?? false,
      });
    } catch {
      updateCapsIfChanged(noCaps);
    }
  }, [selectedAgent, updateCapsIfChanged]);

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

      const target = e.target as HTMLElement;
      const isChatSender =
        target?.tagName === "TEXTAREA" &&
        target?.closest('[class*="sender"]') !== null;

      if (!isChatSender) return;
      if (isComposingRef.current || (e as any).isComposing) return;
      if (e.ctrlKey || e.metaKey || e.altKey) return;

      const textarea = target as HTMLTextAreaElement;
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
      const target = e.target as HTMLElement;
      const isChatSender =
        target?.tagName === "TEXTAREA" &&
        target?.closest('[class*="sender"]') !== null;

      if (isChatSender) {
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
  return agentId
    ? `${DRAFT_STORAGE_KEY_PREFIX}_${agentId}`
    : DRAFT_STORAGE_KEY_PREFIX;
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

/**
 * When the user pastes into the chat textarea text that was just copied
 * from the Coding-mode editor, swap the raw paste for the formatted
 * `path:line[-line]` version (plus optional fenced code). Cmd/Ctrl+C in
 * the editor stays as a plain-text copy for paste-anywhere; only Chat
 * pastes get the editor-context format.
 *
 * Not gated by route: the Chat composer is also embedded in Coding
 * mode (side-by-side with the editor), and that's the primary place
 * users do an editor→chat copy. The handler is already selective (it
 * checks the paste target is a sender textarea AND the pasted text
 * matches the last editor copy), so a global listener is safe.
 */
function useChatPasteFromEditor() {
  useEffect(() => {
    // Anything older than this is treated as stale (different copy session).
    const STALE_MS = 60_000;

    const handlePaste = (e: ClipboardEvent) => {
      const target = e.target as HTMLElement | null;
      if (!target || target.tagName !== "TEXTAREA") return;
      if (!target.closest('[class*="sender"]')) return;

      const last = getLastEditorCopy();
      if (!last) return;
      if (Date.now() - last.ts > STALE_MS) return;

      const pasted = e.clipboardData?.getData("text/plain");
      if (pasted == null || pasted !== last.text) return;

      e.preventDefault();
      const textarea = target as HTMLTextAreaElement;
      const start = textarea.selectionStart ?? textarea.value.length;
      const end = textarea.selectionEnd ?? textarea.value.length;
      const before = textarea.value.slice(0, start);
      const after = textarea.value.slice(end);
      const next = before + last.formatted + after;
      setTextareaValue(textarea, next);
      const caret = before.length + last.formatted.length;
      requestAnimationFrame(() => {
        textarea.selectionStart = textarea.selectionEnd = caret;
      });
    };

    document.addEventListener("paste", handlePaste, true);
    return () => {
      document.removeEventListener("paste", handlePaste, true);
    };
  }, []);
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

const timestampStyle: React.CSSProperties = {
  fontSize: 12,
  color: "var(--ant-color-text-quaternary)",
  whiteSpace: "nowrap",
};

const HISTORY_PANEL_STORAGE_KEY = "qwenpaw_history_panel_open";

export default function ChatPage() {
  const { t, i18n } = useTranslation();
  const navigate = useNavigate();
  const location = useLocation();
  const { isDark } = useTheme();
  const { codingMode, initialized } = useCodingMode();
  const codingModeRef = useRef(codingMode);
  codingModeRef.current = codingMode;

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

  // Redirect to /coding when coding mode is active, preserving sessionId.
  useEffect(() => {
    if (initialized && codingMode && !location.pathname.startsWith("/coding")) {
      // Issue #5142: Carry over the current chatId so the session survives
      // the redirect from /chat/<id> to /coding/<id>.
      const currentChatId = getSessionIdFromPath(location.pathname);
      navigate(buildSessionPath("coding", currentChatId), {
        replace: true,
      });
    }
  }, [initialized, codingMode, navigate, location.pathname]);

  const chatId = useMemo(
    () => getSessionIdFromPath(location.pathname),
    [location.pathname],
  );
  const [showModelPrompt, setShowModelPrompt] = useState(false);
  const [rateLimitAlternatives, setRateLimitAlternatives] = useState<
    Array<{
      provider_id: string;
      provider_name: string;
      model_id: string;
      model_name: string;
    }>
  >([]);
  const { selectedAgent } = useAgentStore();
  const { toolRenderConfig } = usePlugins();
  const extScalar = useChatScalarSnapshot();
  const extLists = useChatListSnapshot();
  const [refreshKey, setRefreshKey] = useState(0);
  const runtimeLoadingBridgeRef = useRef<RuntimeLoadingBridgeApi | null>(null);
  const queueSessionId = chatId ?? "new";
  const queueSessionIdRef = useRef(queueSessionId);
  queueSessionIdRef.current = queueSessionId;
  const messageQueue =
    useMessageQueueStore((s) => s.queues[queueSessionId]) ?? [];
  const messageQueueRef = useRef(messageQueue);
  messageQueueRef.current = messageQueue;
  const autoSendTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const prevQueueLenRef = useRef(messageQueue.length);

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

  const runState = useMessageQueueStore(
    (s) => s.runStates[queueSessionId] ?? "idle",
  );

  // Single-tab ownership: only one tab per conversation may send. Other tabs
  // are queue-only (input is enqueued instead of submitted). The owner is
  // determined by an exclusive Web Lock keyed by sessionId; when the owner
  // tab closes, another tab acquires the lock and becomes the owner.
  const [isOwner, setIsOwner] = useState(false);
  const isOwnerRef = useRef(false);
  isOwnerRef.current = isOwner;
  useEffect(() => {
    setIsOwner(false);
    const ctrl = new AbortController();
    void holdOwnershipLock(queueSessionId, () => setIsOwner(true), ctrl.signal);
    return () => {
      ctrl.abort();
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
          query: next.text,
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
  const { mode: sidebarMode } = useSidebarModeStore();
  const isFullMode = sidebarMode === "full";

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
  const [chatSkills, setChatSkills] = useState<SkillSpec[]>([]);
  const consoleSkills = useMemo(
    () => chatSkills.filter(isSkillAvailableInConsole),
    [chatSkills],
  );

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
    skillApi
      .listSkills(selectedAgent)
      .then((skills) => {
        if (cancelled) return;
        const nextSkills = Array.isArray(skills) ? skills : [];
        setChatSkills(nextSkills);
      })
      .catch((error) => {
        console.warn("[ChatSkills] failed to load slash skills", {
          selectedAgent,
          error,
        });
        if (!cancelled) setChatSkills([]);
      });
    return () => {
      cancelled = true;
    };
  }, [selectedAgent]);

  const isChatActiveRef = useRef(false);
  // Issue #5142: In Coding mode the Chat component is embedded under /coding/*,
  // so session callbacks must also fire on /coding paths.
  isChatActiveRef.current =
    location.pathname === "/" ||
    location.pathname.startsWith("/chat") ||
    location.pathname.startsWith("/coding");

  const isChatActive = useCallback(() => isChatActiveRef.current, []);

  useEffect(() => {
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key !== "Tab" || !isChatActive()) return;
      const textarea = event.target;
      if (!(textarea instanceof HTMLTextAreaElement)) return;
      if (!textarea.closest('[class*="sender"]')) return;
      if (
        !textarea.value.startsWith("/") ||
        /\s/.test(textarea.value.slice(1))
      ) {
        return;
      }

      const selectedItem =
        document.querySelector(
          '[role="menuitemcheckbox"][aria-checked="true"]',
        ) || document.querySelector('[role="menuitem"][aria-current="true"]');
      if (!(selectedItem instanceof HTMLElement)) return;

      const selectedValue = selectedItem.getAttribute("data-path-key")?.trim();
      if (!selectedValue) return;

      event.preventDefault();
      event.stopPropagation();
      setTextareaValue(textarea, `/${selectedValue} `);
      textarea.focus();
    };

    document.addEventListener("keydown", handleKeyDown, true);
    return () => {
      document.removeEventListener("keydown", handleKeyDown, true);
    };
  }, [isChatActive]);

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
        severity: approval.severity,
        findingsCount: approval.findings_count,
        findingsSummary: approval.findings_summary,
        toolParams: approval.tool_params,
        createdAt: approval.created_at,
        timeoutSeconds: approval.timeout_seconds,
      });
    }

    setApprovalRequests(newMap);
  }, [approvals, chatId]);

  const handleApprove = useCallback(
    async (requestId: string) => {
      const request = approvalRequests.get(requestId);
      if (!request) return;

      const rootSessionId = window.currentSessionId || chatId || "";

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
      const rootSessionId = window.currentSessionId || chatId || "";

      try {
        // Add exit animation class
        const cardElement = document.querySelector(
          `[data-approval-id="${requestId}"]`,
        );
        if (cardElement) {
          cardElement.classList.add("approvalCardExit");
        }

        await commandsApi.sendApprovalCommand("deny", requestId, rootSessionId);
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
  );

  const lastSessionIdRef = useRef<string | null>(null);
  /** Tracks the stale auto-selected session ID that was skipped on init, so we can suppress its late-arriving onSessionSelected callback. */
  const staleAutoSelectedIdRef = useRef<string | null>(null);
  const chatIdRef = useRef(chatId);
  const navigateRef = useRef(navigate);
  const chatRef = useRef<IAgentScopeRuntimeWebUIRef>(null);

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
  const whisperSpeechRef = useRef<WhisperSpeechButtonRef>(null);
  const [whisperEnabled, setWhisperEnabled] = useState(false);
  const [whisperChecked, setWhisperChecked] = useState(false);

  // Check if Whisper transcription is configured
  useEffect(() => {
    agentApi
      .getTranscriptionProviderType()
      .then((res) => {
        setWhisperEnabled(res.transcription_provider_type !== "disabled");
      })
      .catch(() => setWhisperEnabled(false))
      .finally(() => setWhisperChecked(true));
  }, []);

  const handleWhisperTranscription = useCallback((text: string) => {
    const senderContainer = document.querySelector('[class*="sender"]');
    const textarea = senderContainer?.querySelector(
      "textarea",
    ) as HTMLTextAreaElement | null;
    if (textarea) {
      const currentValue = textarea.value || "";
      const newValue = currentValue ? `${currentValue} ${text}` : text;
      setTextareaValue(textarea, newValue);
      textarea.focus();
    }
  }, []);

  useMessageHistoryNavigation(chatRef, isChatActive, isComposingRef);
  useChatInputDraft(isChatActive, selectedAgent);
  useChatPasteFromEditor();

  // ── Message Queue ───────────────────────────────────────────────────────

  // Stop background sender for THIS session when ChatPage mounts (foreground
  // takes over); start background senders for all OTHER sessions with pending
  // items. On unmount (or session switch), start bg sender for THIS session.
  useEffect(() => {
    stopBackgroundQueue(queueSessionId);
    // Kick off background senders for other sessions that have pending items
    startAllBackgroundQueues(queueSessionId);
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
        // queueKey is what the queue is stored under (may be "new");
        // backendSessionId is the resolved id sent to /console/chat.
        const queueKey = queueSessionIdRef.current;
        const backendSessionId =
          window.currentSessionId || chatIdRef.current || "";
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
    }

    if (responseJustCompleted || itemsJustQueued) {
      scheduleNextSend();
    }
  }, [chatLoading, messageQueue, scheduleNextSend]);

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
        ? (document
            .querySelector('[class*="sender"]')
            ?.querySelector("textarea") as HTMLTextAreaElement | null)
        : e.target instanceof HTMLTextAreaElement &&
          e.target.closest('[class*="sender"]')
        ? e.target
        : null;
      if (!textarea) return;
      const val = textarea.value.trim();
      if (!val) return;
      e.preventDefault();
      e.stopPropagation();
      if (!chatId) {
        return;
      }
      const currentQ = useMessageQueueStore.getState().getQueue(queueSessionId);
      if (currentQ.length >= MAX_QUEUE_SIZE) {
        message.warning(t("chat.queue.queueFull", { max: MAX_QUEUE_SIZE }));
        return;
      }
      useMessageQueueStore.getState().enqueue(queueSessionId, {
        text: val,
        attachments:
          pendingFileListRef.current.length > 0
            ? pendingFileListRef.current.map((f) => ({
                url: f.url,
                name: f.name,
                type: f.type,
                size: f.size,
              }))
            : undefined,
        userId: window.currentUserId || DEFAULT_USER_ID,
        channel: window.currentChannel || DEFAULT_CHANNEL,
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
            query: item.text,
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
            query: head.text,
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
            query: target.text,
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
            query: next.text,
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
      if (fileInfo.url) {
        openExternalLink(fileInfo.url);
      }
    },
    [],
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
    });
  }, []);

  // Tell sessionApi which session to put first in getSessionList, so the library's
  // useMount auto-selects the correct session without an extra getSession round-trip.
  if (chatId && sessionApi.preferredChatId !== chatId) {
    sessionApi.preferredChatId = chatId;
  }

  // Register session API event callbacks for URL synchronization

  useEffect(() => {
    const getCurrentRouteMode = (): SessionRouteMode =>
      codingModeRef.current ? "coding" : "chat";

    const buildCurrentSessionPath = (sessionId: string) =>
      buildSessionPath(getCurrentRouteMode(), sessionId);

    const buildCurrentBasePath = () => buildBasePath(getCurrentRouteMode());

    sessionApi.onSessionIdResolved = (_tempId, realId) => {
      if (!isChatActiveRef.current) return;
      // Migrate any items still queued under the temporary "new" key over to
      // the resolved real session id BEFORE the URL changes, so the same
      // queueSessionId effect (which now reads `realId`) sees the items
      // already in the store and won't re-send them as part of a fresh
      // "new" conversation later.
      try {
        useMessageQueueStore.getState().migrateQueue("new", realId);
      } catch {
        // ignore migration errors
      }
      // Update URL when realId is resolved, regardless of current chatId
      // (chatId may be undefined if URL was cleared in onSessionCreated)
      lastSessionIdRef.current = realId;
      navigateRef.current(buildCurrentSessionPath(realId), { replace: true });
    };

    sessionApi.onSessionRemoved = (removedId) => {
      if (!isChatActiveRef.current) return;
      // Clear URL when current session is removed
      // Check if removed session matches current session (by realId or sessionId)
      const currentRealId = sessionApi.getRealIdForSession(
        chatIdRef.current || "",
      );
      if (chatIdRef.current === removedId || currentRealId === removedId) {
        lastSessionIdRef.current = null;
        navigateRef.current(buildCurrentBasePath(), { replace: true });
      }
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

      if (targetId !== lastSessionIdRef.current) {
        lastSessionIdRef.current = targetId;
        sessionApi.lastNavigatedChatId = targetId;
        navigateRef.current(buildCurrentSessionPath(targetId), {
          replace: true,
        });
      }
    };

    sessionApi.onSessionCreated = () => {
      if (!isChatActiveRef.current) return;
      // The user is starting a brand new conversation. Drop any leftover items
      // sitting under the temporary "new" key so they don't get auto-sent into
      // the freshly-created chat. Items belonging to a previously-resolved
      // chat have already been migrated to their real session id.
      try {
        useMessageQueueStore.getState().clear("new");
      } catch {
        // ignore
      }
      // Clear URL when creating new session, wait for realId resolution to update
      lastSessionIdRef.current = null;
      navigateRef.current(buildCurrentBasePath(), { replace: true });
    };

    return () => {
      sessionApi.onSessionIdResolved = null;
      sessionApi.onSessionRemoved = null;
      sessionApi.onSessionSelected = null;
      sessionApi.onSessionCreated = null;
    };
  }, []);

  // Setup multimodal capabilities tracking via custom hook

  // Refresh chat when selectedAgent changes, preserving last active chat per agent
  const { setLastChatId, getLastChatId } = useAgentStore();
  const prevSelectedAgentRef = useRef(selectedAgent);
  useEffect(() => {
    const prevAgent = prevSelectedAgentRef.current;
    if (prevAgent !== selectedAgent && prevAgent !== undefined) {
      // Immediately block the queue sender. window.currentSessionId is a
      // global that still holds the PREVIOUS agent's session_id until the
      // SDK finishes reloading. Without this guard, scheduleNextSend could
      // fire during the reload window and send a queued item to the wrong
      // agent's conversation.
      setChatLoading(true);

      // Save current chat ID for the agent we're leaving
      const currentChatId =
        chatIdRef.current || lastSessionIdRef.current || undefined;
      if (currentChatId && prevAgent) {
        setLastChatId(prevAgent, currentChatId);
      }

      // Restore last chat ID for the agent we're switching to
      const restored = getLastChatId(selectedAgent);
      if (restored) {
        navigateRef.current(buildSessionPath("chat", restored), {
          replace: true,
        });
        sessionApi.preferredChatId = restored;
      } else {
        navigateRef.current("/chat", { replace: true });
      }
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
      const headers: Record<string, string> = {
        "Content-Type": "application/json",
        ...buildAuthHeaders(),
      };

      try {
        const activeModels = await providerApi.getActiveModels({
          scope: "effective",
          agent_id: selectedAgent,
        });
        if (
          !activeModels?.active_llm?.provider_id ||
          !activeModels?.active_llm?.model
        ) {
          setShowModelPrompt(true);
          return buildModelError();
        }
      } catch {
        setShowModelPrompt(true);
        return buildModelError();
      }

      const { input = [], biz_params } = data;
      const session: SessionInfo = input[input.length - 1]?.session || {};
      const lastInput = input.slice(-1);
      const lastMsg = lastInput[0];
      const rewrittenInput =
        lastMsg?.content && Array.isArray(lastMsg.content)
          ? [
              {
                ...lastMsg,
                content: lastMsg.content.map(normalizeContentUrls),
              },
            ]
          : lastInput;

      let requestBody: Record<string, unknown> = {
        input: rewrittenInput,
        session_id: window.currentSessionId || session?.session_id || "",
        user_id: window.currentUserId || session?.user_id || DEFAULT_USER_ID,
        channel: window.currentChannel || session?.channel || DEFAULT_CHANNEL,
        stream: true,
        ...biz_params,
      };

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

      const backendChatId =
        sessionApi.getRealIdForSession(String(requestBody.session_id || "")) ??
        chatIdRef.current ??
        String(requestBody.session_id || "");
      if (backendChatId) {
        const userText = rewrittenInput
          .filter((m: any) => m.role === "user")
          .map(extractUserMessageText)
          .join("\n")
          .trim();
        if (userText) {
          // Also pass the full content array so patchLastUserMessage can
          // rebuild user card with images/files when reconnecting.
          const lastUserMsg = rewrittenInput
            .filter((m: any) => m.role === "user")
            .slice(-1)[0];
          const contentArr = Array.isArray(lastUserMsg?.content)
            ? (lastUserMsg.content as Array<{
                type: string;
                [key: string]: unknown;
              }>)
            : undefined;
          sessionApi.setLastUserMessage(backendChatId, userText, contentArr);
        }
      }

      const response = await fetch(getApiUrl("/console/chat"), {
        method: "POST",
        headers,
        body: JSON.stringify(requestBody),
        signal: data.signal,
      });

      return wrapChatResponseUsageStream(response, chatRef);
    },
    [extLists, selectedAgent],
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
        if (!multimodalCaps.supportsMultimodal) {
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

        const res = await chatApi.uploadFile(file);
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
    [multimodalCaps, t],
  );

  const options = useMemo(() => {
    const i18nConfig = getDefaultConfig(t);
    const commandSuggestions: CommandSuggestion[] = [
      {
        command: "/clear",
        value: "clear",
        description: t("chat.commands.clear.description"),
      },
      {
        command: "/compact",
        value: "compact",
        description: t("chat.commands.compact.description"),
      },
      {
        command: "/mission",
        value: "mission",
        description: t("chat.commands.mission.description"),
      },
      {
        command: "/skills",
        value: "skills",
        description: t("chat.commands.skills.description"),
      },
    ];
    if (planEnabled) {
      commandSuggestions.push({
        command: "/plan",
        value: "plan ",
        description: t("chat.commands.plan.description"),
      });
    }
    const reservedCommands = new Set(
      commandSuggestions.map((item) => item.value.trim()),
    );
    const skillSuggestions: CommandSuggestion[] = consoleSkills
      .filter((skill) => !reservedCommands.has(skill.name))
      .sort((a, b) => a.name.localeCompare(b.name))
      .map((skill) => ({
        command: `/${skill.name}`,
        value: skill.name,
        description: "",
      }));
    const handleBeforeSubmit = async () => {
      if (isComposingRef.current) return false;
      // Single-tab ownership: non-owner tabs are queue-only. Re-route every
      // submit (Enter / send button / programmatic) to the shared queue and
      // abort the actual SDK send. The owner tab will pick the item up via
      // cross-tab broadcast and send it.
      if (!isOwnerRef.current) {
        const textarea = document
          .querySelector('[class*="sender"]')
          ?.querySelector("textarea") as HTMLTextAreaElement | null;
        const val = textarea?.value.trim() ?? "";
        if (!val) return false;
        if (!chatId) {
          return false;
        }
        const currentQ = useMessageQueueStore
          .getState()
          .getQueue(queueSessionId);
        if (currentQ.length >= MAX_QUEUE_SIZE) {
          message.warning(t("chat.queue.queueFull", { max: MAX_QUEUE_SIZE }));
          return false;
        }
        useMessageQueueStore.getState().enqueue(queueSessionId, {
          text: val,
          attachments:
            pendingFileListRef.current.length > 0
              ? pendingFileListRef.current.map((f) => ({
                  url: f.url,
                  name: f.name,
                  type: f.type,
                  size: f.size,
                }))
              : undefined,
          userId: window.currentUserId || DEFAULT_USER_ID,
          channel: window.currentChannel || DEFAULT_CHANNEL,
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
    const pluginSuggestions = extLists[ChatList.senderSuggestions].flatMap(
      (e) => {
        const resolved = resolveLocalized(e.item.items, locale) ?? [];
        return resolved.map((s) => ({ label: s.label, value: s.value }));
      },
    );

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

    const baseSuggestions = [...commandSuggestions, ...skillSuggestions].map(
      (item) => ({
        label: renderSuggestionLabel(item.command, item.description),
        value: item.value,
      }),
    );

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
        leftHeader: mergedLeftHeader,
        rightHeader: (
          <>
            <ChatSessionInitializer />
            <RuntimeLoadingBridge
              bridgeRef={runtimeLoadingBridgeRef}
              onLoadingChange={setChatLoading}
            />
            <ChatHeaderTitle />
            <span style={{ flex: 1 }} />
            <ModelSelector />
            <ChatActionGroup
              planEnabled={planEnabled}
              onToggleHistory={isFullMode ? toggleHistoryPanel : undefined}
              historyOpen={isFullMode ? historyPanelOpen : false}
              isWideMode={isWideMode}
              onToggleWideMode={toggleWideMode}
            />
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
        allowSpeech: whisperChecked && !whisperEnabled,
        beforeUI:
          !isOwner || messageQueue.length > 0 ? (
            <>
              {null}
              {messageQueue.length > 0 ? (
                <MessageQueuePanel
                  items={messageQueue}
                  runState={runState}
                  onRemove={handleQueueRemove}
                  onEdit={handleQueueEdit}
                  onReorder={handleQueueReorder}
                  onInterruptAndSend={handleQueueInterruptAndSend}
                  onClear={handleQueueClear}
                  onPauseResume={handleQueuePauseResume}
                  onRetry={handleQueueRetry}
                  onSkip={handleQueueSkip}
                />
              ) : null}
            </>
          ) : undefined,
        prefix:
          whisperEnabled || pluginSenderPrefix.length > 0 ? (
            <>
              {whisperEnabled ? (
                <WhisperSpeechButton
                  ref={whisperSpeechRef}
                  onTranscription={handleWhisperTranscription}
                />
              ) : null}
              {pluginSenderPrefix}
            </>
          ) : undefined,
        attachments: {
          multiple: true,
          trigger: function (props: any) {
            const uploadLimit = useUploadLimitStore.getState().uploadMaxSizeMb;
            const tooltipKey = multimodalCaps.supportsMultimodal
              ? multimodalCaps.supportsImage && !multimodalCaps.supportsVideo
                ? "chat.attachments.tooltipImageOnly"
                : "chat.attachments.tooltip"
              : "chat.attachments.tooltipNoMultimodal";
            const tooltipTitle =
              uploadLimit !== null
                ? `${t(tooltipKey)}, ${t("chat.attachments.fileSizeLimit", {
                    limit: uploadLimit,
                  })}`
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
        placeholder: extPlaceholder ?? t("chat.inputPlaceholder"),
        ...(extDisclaimer !== undefined ? { disclaimer: extDisclaimer } : {}),
        suggestions: [...baseSuggestions, ...pluginSuggestions],
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

          if (payloadCompletesResponse(payload)) {
            const output = payload.output;
            if (!output || (Array.isArray(output) && output.length === 0)) {
              const errorMsg =
                (payload.error as any)?.message || t("chat.emptyOutputError");
              payload.output = [
                {
                  type: "message",
                  role: "assistant",
                  content: [{ type: "text", text: errorMsg }],
                },
              ];
            }
          }

          if (payload.type === "turn_usage") {
            return null;
          }

          if (payload.type === "rate_limited") {
            const alts =
              (payload.alternatives as typeof rateLimitAlternatives) || [];
            setRateLimitAlternatives(alts);
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
          const resolvedChatId =
            sessionApi.getRealIdForSession(data.session_id) ?? data.session_id;
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

          const sessionId = window.currentSessionId || data.session_id;
          const response = await fetch(getApiUrl("/console/chat"), {
            method: "POST",
            headers,
            body: JSON.stringify({
              reconnect: true,
              session_id: sessionId,
              user_id: window.currentUserId || DEFAULT_USER_ID,
              channel: window.currentChannel || DEFAULT_CHANNEL,
            }),
            signal: data.signal,
          });

          return wrapChatResponseUsageStream(response, chatRef);
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
            render: ({
              data,
            }: {
              data: { data?: Record<string, unknown> };
            }) => <TurnUsageAction data={data} />,
          },
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
              data: { data?: { created_at?: number } };
            }) => {
              return (
                <span style={timestampStyle}>
                  {formatMessageTime(data?.data?.created_at ?? 0)}
                </span>
              );
            },
          },
          ...pluginActions,
        ],
        replace: true,
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
    consoleSkills,
    selectedAgent,
    onFileCardClick,
    whisperChecked,
    whisperEnabled,
    handleWhisperTranscription,
    isWideMode,
    toggleWideMode,
    messageQueue,
    handleQueueRemove,
    handleQueueEdit,
    handleQueueReorder,
    handleQueueInterruptAndSend,
    handleQueueClear,
    handleQueuePauseResume,
    handleQueueRetry,
    handleQueueSkip,
    runState,
    isOwner,
  ]);

  return (
    <div className={styles.chatPageRoot}>
      {/* Main chat area */}
      <div className={styles.chatMainArea}>
        <div
          className={
            isWideMode
              ? `${styles.chatMessagesArea} ${styles.wideMode}`
              : styles.chatMessagesArea
          }
        >
          <AgentScopeRuntimeWebUI
            ref={chatRef}
            key={refreshKey}
            options={options}
          />
        </div>

        {/* Rate-limit guidance banner */}
        {rateLimitAlternatives.length > 0 && (
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
                      await providerApi.setActiveLlm({
                        provider_id: alt.provider_id,
                        model: alt.model_id,
                        scope: "agent",
                        agent_id: selectedAgent,
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
        {Array.from(approvalRequests.values()).map((request) => (
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
            <ApprovalCard
              requestId={request.requestId}
              agentId={request.agentId}
              toolName={request.toolName}
              severity={request.severity}
              findingsCount={request.findingsCount}
              findingsSummary={request.findingsSummary}
              toolParams={request.toolParams}
              createdAt={request.createdAt}
              timeoutSeconds={request.timeoutSeconds}
              sessionId={request.sessionId}
              rootSessionId={request.rootSessionId}
              onApprove={handleApprove}
              onDeny={handleDeny}
              onCancel={() => {
                const sessionId =
                  request.rootSessionId || window.currentSessionId || "";
                const resolvedChatId =
                  sessionApi.getRealIdForSession(sessionId) ??
                  chatIdRef.current ??
                  sessionId;

                if (resolvedChatId) {
                  console.log("[Chat] Calling stopChat with:", resolvedChatId);
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
          </div>
        ))}

        <Modal
          open={showModelPrompt}
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
              </Button>,
            ]}
          />
        </Modal>
      </div>
      {/* End of main chat area */}

      {/* Right-side history panel (full mode only) */}
      {isFullMode && historyPanelOpen && (
        <div className={styles.historyPanel}>
          <ChatSessionDrawer
            open={historyPanelOpen}
            onClose={toggleHistoryPanel}
            embedded
          />
        </div>
      )}
    </div>
  );
}
