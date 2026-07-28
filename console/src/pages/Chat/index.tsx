import {
  AgentScopeRuntimeWebUI,
  IAgentScopeRuntimeWebUIOptions,
  type IAgentScopeRuntimeWebUIMessage,
  type IAgentScopeRuntimeWebUIQueueSessionContext,
  type IAgentScopeRuntimeWebUIRef,
} from "@agentscope-ai/chat";
import {
  useCallback,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { Button, Modal, Result, Tooltip } from "antd";
import { useAppMessage } from "../../hooks/useAppMessage";
import { useIsMobile } from "../../hooks/useIsMobile";
import { ExclamationCircleOutlined, SettingOutlined } from "@ant-design/icons";
import { SparkCopyLine, SparkAttachmentLine } from "@agentscope-ai/icons";
import { usePlugins } from "../../plugins/PluginContext";
import { useTranslation } from "react-i18next";
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
import {
  beginLoopModeSubmission,
  fetchActiveLoopMode,
  fetchAvailableLoopModes,
  markLoopModeRunning,
  useLoopStore,
} from "../../stores/loopStore";
import { LoopModeSelector } from "../../components/LoopInput";
import { useChatAnywhereInput } from "@agentscope-ai/chat";
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
import { useTurnUsageStore } from "./turnUsageStore";
import ChatHeaderTitle from "./components/ChatHeaderTitle";
import ChatSessionInitializer from "./components/ChatSessionInitializer";
import { ApprovalCard } from "../../components/ApprovalCard/ApprovalCard";
import { commandsApi } from "../../api/modules/commands";
import { useApprovalContext } from "../../contexts/ApprovalContext";
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
import {
  buildAgentScopedQueueSessionId,
  getQueueAgentId,
  resolveAgentScopedQueueSessionId,
  resolveBackendChatSessionId,
  stripQueueAgentPrefix,
} from "./chatSessionIds";
import { buildChatSessionOptions } from "./chatSessionOptions";
import {
  resolveChatRequestContext,
  type QueuedChatRequestData,
} from "./chatRequestContext";
import {
  clearStoredInputQueue,
  hasStoredInputQueueItems,
  migrateInputQueueStorage,
} from "./inputQueueStorage";
import {
  resolveRuntimeChatId,
  resolveSessionInitializerChatId,
  type PendingAgentChatScope,
} from "./agentSwitchScope";
import { applyApprovalLevelToRequestBody } from "./approvalPayload";
import {
  createHeadlineFilterState,
  filterHeadlineDelta,
  flushHeadlineFilter,
  type HeadlineStreamFilterState,
  stripScrollHeadlineTextBlocks,
} from "./headlineFilter";
import {
  getQueueRequestId,
  INTERNAL_QUEUE_REQUEST_ID_PARAM,
  shouldRestoreQueuedInputAfterError,
} from "./queueRequestLifecycle";
import { createSecureRandomHex } from "./secureRandom";

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
}

import WhisperSpeechButton, {
  WhisperSpeechButtonRef,
} from "./components/WhisperSpeechButton";

import {
  toDisplayUrl,
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
import ApprovalLevelToggle from "./components/ApprovalLevelToggle";
import HarnessApprovalToggle from "./components/HarnessApprovalToggle";
import HarnessModelSelector from "./components/HarnessModelSelector";
import { useAgentRunningConfigApprovalLevel } from "../../hooks/useAgentRunningConfigApprovalLevel";
import type { ToolExecutionLevel } from "../../utils/approval";
import {
  requiresQwenPawModel,
  supportsAgentAttachments,
} from "../../utils/agentBackend";

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
const AGENT_SWITCH_QUEUE_SETTLE_MS = 1500;
const ACCEPTED_QUEUE_TOMBSTONE_TTL_MS = 5 * 60 * 1000;
const WIDE_MODE_STORAGE_KEY = "qwenpaw_chat_wide_mode";
const CHAT_STREAM_SNAPSHOT_CHANNEL = "qwenpaw:chat-stream-snapshot";

function clearAcceptedQueueRequestOnStreamCompletion(
  response: Response,
  onComplete: () => void,
) {
  if (!response.body || typeof TransformStream === "undefined") {
    onComplete();
    return response;
  }

  const body = response.body.pipeThrough(
    new TransformStream<Uint8Array, Uint8Array>({
      transform(chunk, controller) {
        controller.enqueue(chunk);
      },
      flush() {
        onComplete();
      },
    }),
  );
  return new Response(body, {
    status: response.status,
    statusText: response.statusText,
    headers: response.headers,
  });
}

let queueRequestSequence = 0;

function createQueueRequestId() {
  queueRequestSequence += 1;
  return `qwenpaw-queue-${Date.now().toString(
    36,
  )}-${queueRequestSequence.toString(36)}`;
}

interface ChatStreamSnapshotPayload {
  type: "request" | "snapshot";
  sessionId: string;
  sourceTabId: string;
  messages?: IAgentScopeRuntimeWebUIMessage[];
  createdAt?: number;
}

function isSkillAvailableInConsole(skill: SkillSpec): boolean {
  if (!skill.enabled) return false;
  const channels = skill.channels?.length ? skill.channels : ["all"];
  return channels.includes("all") || channels.includes(DEFAULT_CHANNEL);
}

function createChatStreamSnapshotTabId() {
  return `chat-tab-${Date.now().toString(36)}-${createSecureRandomHex()}`;
}

function isChatStreamSnapshotPayload(
  payload: unknown,
): payload is ChatStreamSnapshotPayload {
  if (!payload || typeof payload !== "object") return false;
  const record = payload as Partial<ChatStreamSnapshotPayload>;
  return (
    (record.type === "request" || record.type === "snapshot") &&
    typeof record.sessionId === "string" &&
    typeof record.sourceTabId === "string"
  );
}

function hasGeneratingAssistantMessage(
  messages: IAgentScopeRuntimeWebUIMessage[] | undefined,
) {
  return !!messages?.some(
    (item) => item?.role === "assistant" && item?.msgStatus === "generating",
  );
}

function replaceChatMessages(
  chatRef: React.RefObject<IAgentScopeRuntimeWebUIRef | null>,
  messages: IAgentScopeRuntimeWebUIMessage[],
) {
  const api = chatRef.current?.messages;
  if (!api || messages.length === 0) return;
  api.removeAllMessages();
  for (const item of messages) {
    api.updateMessage(item);
  }
}

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
  }, [selectedAgent, updateCapsIfChanged, usesQwenPawBackend]);

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

function clearSenderTextareaOnNextTick() {
  window.setTimeout(() => {
    const sender = document.querySelector('[class*="sender"]');
    const textarea = sender?.querySelector(
      "textarea",
    ) as HTMLTextAreaElement | null;
    if (textarea) {
      setTextareaValue(textarea, "");
    }
  }, 0);
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
  const loopAvailableModes = useLoopStore((state) => state.availableModes);

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
  const { selectedAgent, agents } = useAgentStore();
  // selectedAgent changes before the route is restored. Keep the SDK on the
  // previous agent until the switch effect has saved the old route, otherwise
  // one render briefly scopes the old chat to the new agent's input queue.
  const runtimeAgentRef = useRef(selectedAgent);
  const pendingAgentChatScopeRef = useRef<PendingAgentChatScope | null>(null);
  const runtimeAgent = runtimeAgentRef.current;
  const queueDrainBlockedUntilRef = useRef(new Map<string, number>());
  const acceptedQueuedInputRef = useRef(new Set<string>());
  // sessionApi is a module singleton, so it must be re-scoped synchronously
  // before this render resolves route/session aliases for the runtime agent.
  // Otherwise agent switches can reuse another agent's chat mapping and make
  // its input queue appear under the wrong storage key.
  sessionApi.setActiveAgent(runtimeAgent);
  const runtimeChatId = resolveRuntimeChatId(
    chatId,
    runtimeAgent,
    pendingAgentChatScopeRef.current,
  );
  const resolveInitializerChatId = useCallback(
    (routeChatId: string | undefined) =>
      resolveSessionInitializerChatId(
        routeChatId,
        runtimeAgentRef.current,
        pendingAgentChatScopeRef.current,
        sessionApi.userInitiatedCreate || sessionApi.suppressBaseAutoSelect,
      ),
    [],
  );
  const inputQueueEnabled = runtimeChatId
    ? !sessionApi.isUnresolvedLocalSession(runtimeChatId)
    : false;
  // Backend capabilities must follow the same runtime scope as the chat SDK.
  // During an Agent switch, selectedAgent changes one render before the SDK
  // remounts, so deriving these from selectedAgent would mix two Agents.
  const runtimeAgentInfo = agents.find((agent) => agent.id === runtimeAgent);
  const selectedAgentBackend = runtimeAgentInfo?.backend ?? "qwenpaw";
  const backendCapabilities = runtimeAgentInfo?.backend_capabilities;
  const usesQwenPawBackend = requiresQwenPawModel(selectedAgentBackend);
  const backendCommands = backendCapabilities?.commands ?? [];
  const approvalPresets = backendCapabilities?.approval_presets ?? [];
  const supportsAttachments = supportsAgentAttachments(
    selectedAgentBackend,
    backendCapabilities,
  );
  const { toolRenderConfig } = usePlugins();
  const extScalar = useChatScalarSnapshot();
  const extLists = useChatListSnapshot();
  const [refreshKey, setRefreshKey] = useState(0);
  const controlledSdkSessionId = sessionApi.getLibrarySessionId(runtimeChatId);
  const scopedSessionApi = useMemo(
    () => sessionApi.createScopedApi(runtimeAgent, controlledSdkSessionId),
    [controlledSdkSessionId, runtimeAgent],
  );
  const headlineStreamFilterRef = useRef<HeadlineStreamFilterState>(
    createHeadlineFilterState(),
  );
  // Keep approval overrides stable while a local session resolves to its
  // backend ID. This is separate from the agent-scoped SDK queue key.
  const approvalSessionId =
    runtimeChatId ?? sessionApi.lastActiveChatId ?? "new";
  const sessionApprovalLevelRef = useRef<ToolExecutionLevel | null>(null);
  const backendControlsRef = useRef<Record<string, unknown>>({});
  const runningConfigApprovalLevel = useAgentRunningConfigApprovalLevel();
  const runtimeLoadingBridgeRef = useRef<RuntimeLoadingBridgeApi | null>(null);

  const syncLoopModeStatus = useCallback(() => {
    const backendSessionId =
      window.currentSessionId ||
      (runtimeChatId ? sessionApi.getBackendSessionId(runtimeChatId) : "");
    return fetchActiveLoopMode({
      chatId: runtimeChatId,
      sessionId: backendSessionId,
    });
  }, [runtimeChatId]);

  useEffect(() => {
    const controller = new AbortController();
    useLoopStore.getState().resetSessionMode();
    void fetchAvailableLoopModes(controller.signal);
    if (runtimeChatId) {
      void fetchActiveLoopMode({
        chatId: runtimeChatId,
        sessionId:
          window.currentSessionId ||
          sessionApi.getBackendSessionId(runtimeChatId),
        signal: controller.signal,
      });
    }
    return () => controller.abort();
  }, [runtimeChatId, selectedAgent]);

  const [chatLoading, setChatLoading] = useState<boolean | string>(false);
  const prevChatLoadingRef = useRef<boolean | string>(false);
  const { message } = useAppMessage();
  const { approvals, setApprovals } = useApprovalContext();
  const [approvalRequests, setApprovalRequests] = useState<
    Map<string, ApprovalMessageData>
  >(new Map());
  const { mode: sidebarMode } = useSidebarModeStore();
  const isFullMode = sidebarMode === "full";

  // On mobile viewports the right-side history panel should always be
  // available regardless of the sidebar mode setting.
  const isMobile = useIsMobile();
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
  const [chatSkills, setChatSkills] = useState<SkillSpec[]>([]);
  const consoleSkills = useMemo(
    () => chatSkills.filter(isSkillAvailableInConsole),
    [chatSkills],
  );

  useEffect(() => {
    if (!usesQwenPawBackend) {
      setChatSkills([]);
      return;
    }
    let cancelled = false;
    skillApi
      .listSkills(runtimeAgent)
      .then((skills) => {
        if (cancelled) return;
        const nextSkills = Array.isArray(skills) ? skills : [];
        setChatSkills(nextSkills);
      })
      .catch((error) => {
        console.warn("[ChatSkills] failed to load slash skills", {
          selectedAgent: runtimeAgent,
          error,
        });
        if (!cancelled) setChatSkills([]);
      });
    return () => {
      cancelled = true;
    };
  }, [runtimeAgent, usesQwenPawBackend]);

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
    const currentSessionId = window.currentSessionId || runtimeChatId || "";

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
      });
    }

    setApprovalRequests(newMap);
  }, [approvals, runtimeChatId]);

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
    [approvalRequests, t, message, setApprovals],
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
    [approvalRequests, t, message, setApprovals],
  );

  // Use custom hooks for better separation of concerns
  const isComposingRef = useIMEComposition(isChatActive);
  const { multimodalCaps, fetchMultimodalCaps } = useMultimodalCapabilities(
    refreshKey,
    location.pathname,
    isChatActive,
    runtimeAgent,
    usesQwenPawBackend,
  );

  const { setLastChatId, getLastChatId } = useAgentStore();
  const setLastChatIdRef = useRef(setLastChatId);
  setLastChatIdRef.current = setLastChatId;
  const selectedAgentRef = runtimeAgentRef;

  const resolveBackendSessionId = useCallback(
    (sessionId?: string) =>
      resolveBackendChatSessionId(sessionId, (rawSessionId) =>
        sessionApi.getBackendSessionId(rawSessionId),
      ),
    [],
  );

  const resolveInputQueueSessionId = useCallback(
    (sessionId?: string) =>
      resolveAgentScopedQueueSessionId(
        sessionId,
        runtimeAgent,
        (rawSessionId) => sessionApi.getQueueSessionId(rawSessionId),
      ),
    [runtimeAgent],
  );

  const lastSessionIdRef = useRef<string | null>(null);
  /** Tracks the stale auto-selected session ID that was skipped on init, so we can suppress its late-arriving onSessionSelected callback. */
  const staleAutoSelectedIdRef = useRef<string | null>(null);
  const chatIdRef = useRef(runtimeChatId);
  const navigateRef = useRef(navigate);
  const chatRef = useRef<IAgentScopeRuntimeWebUIRef>(null);
  const streamSnapshotTabIdRef = useRef(createChatStreamSnapshotTabId());

  const isFrontendChatRunning = useCallback(() => {
    const hasStopLoadingControl =
      typeof document !== "undefined" &&
      !!document.querySelector(
        'button img[alt="Stop Loading"], button [aria-label="Stop Loading"], button[aria-label="Stop Loading"]',
      );
    if (hasStopLoadingControl) return true;

    const messages = chatRef.current?.messages?.getMessages?.();
    return (
      Array.isArray(messages) &&
      messages.some(
        (message: any) =>
          message?.role === "assistant" && message?.msgStatus === "generating",
      )
    );
  }, []);

  useEffect(() => {
    if (!inputQueueEnabled || !runtimeChatId) return;
    if (typeof BroadcastChannel === "undefined") return;

    const queueSessionId = resolveInputQueueSessionId(runtimeChatId);
    if (!queueSessionId) return;

    const sourceTabId = streamSnapshotTabIdRef.current;
    let closed = false;
    let channel: BroadcastChannel;

    try {
      channel = new BroadcastChannel(CHAT_STREAM_SNAPSHOT_CHANNEL);
    } catch {
      return;
    }

    const currentMessages = () =>
      chatRef.current?.messages?.getMessages?.() ?? [];

    const postSnapshot = () => {
      if (closed) return;
      const messages = currentMessages();
      if (!hasGeneratingAssistantMessage(messages)) return;
      channel.postMessage({
        type: "snapshot",
        sessionId: queueSessionId,
        sourceTabId,
        messages,
        createdAt: Date.now(),
      } satisfies ChatStreamSnapshotPayload);
    };

    channel.onmessage = (event) => {
      const payload = event.data;
      if (!isChatStreamSnapshotPayload(payload)) return;
      if (payload.sourceTabId === sourceTabId) return;
      if (payload.sessionId !== queueSessionId) return;

      if (payload.type === "request") {
        window.setTimeout(postSnapshot, 0);
        return;
      }

      const incomingMessages = payload.messages;
      if (
        !incomingMessages ||
        !hasGeneratingAssistantMessage(incomingMessages)
      ) {
        return;
      }
      if (hasGeneratingAssistantMessage(currentMessages())) return;
      replaceChatMessages(chatRef, incomingMessages);
    };

    const requestSnapshot = () => {
      if (closed) return;
      channel.postMessage({
        type: "request",
        sessionId: queueSessionId,
        sourceTabId,
      } satisfies ChatStreamSnapshotPayload);
    };

    const timers = [150, 700, 1500].map((delay) =>
      window.setTimeout(requestSnapshot, delay),
    );

    return () => {
      closed = true;
      timers.forEach((timer) => window.clearTimeout(timer));
      channel.close();
    };
  }, [runtimeChatId, inputQueueEnabled, resolveInputQueueSessionId]);

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

  // Refresh the active loop status after the SDK finishes a response.
  useEffect(() => {
    const wasLoading = prevChatLoadingRef.current;
    prevChatLoadingRef.current = chatLoading;

    const responseJustCompleted = wasLoading && !chatLoading;
    if (responseJustCompleted) {
      void syncLoopModeStatus();
    }
  }, [chatLoading, syncLoopModeStatus]);

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
  chatIdRef.current = runtimeChatId;
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
  const effectiveChatId =
    sessionApi.getRoutableSessionId(runtimeChatId) ||
    (sessionApi.suppressBaseAutoSelect
      ? undefined
      : sessionApi.getRoutableSessionId(sessionApi.lastActiveChatId) ||
        getLastChatId(runtimeAgent));
  if (effectiveChatId && sessionApi.preferredChatId !== effectiveChatId) {
    sessionApi.preferredChatId = effectiveChatId;
  }

  // Register session API event callbacks for URL synchronization

  useEffect(() => {
    const getCurrentRouteMode = (): SessionRouteMode =>
      codingModeRef.current ? "coding" : "chat";

    const buildCurrentSessionPath = (sessionId: string) =>
      buildSessionPath(getCurrentRouteMode(), sessionId);

    const buildCurrentBasePath = () => buildBasePath(getCurrentRouteMode());

    sessionApi.onSessionIdResolved = async (_tempId, realId, owningAgentId) => {
      if (!isChatActiveRef.current) return;
      // Use the owning agent (captured at POST time), not the currently
      // selected agent. Otherwise an Agent switch between POST success and
      // realId resolution would migrate the queue into the wrong agent's
      // scope, orphaning the original queue and risking cross-agent delivery.
      const agentId = owningAgentId ?? selectedAgentRef.current;
      await migrateInputQueueStorage(
        buildAgentScopedQueueSessionId(_tempId, agentId),
        buildAgentScopedQueueSessionId(realId, agentId),
      );
      // Only navigate the URL when the owning agent is still the active
      // runtime agent. If the user has switched away, navigating to the
      // resolved realId would hijack the destination agent's route. The
      // user can switch back to the original agent to restore this chat.
      if (isChatActiveRef.current && agentId === selectedAgentRef.current) {
        lastSessionIdRef.current = realId;
        sessionApi.trackNavigatedSession(
          realId,
          setLastChatIdRef.current,
          selectedAgentRef.current,
        );
        navigateRef.current(buildCurrentSessionPath(realId), { replace: true });
      }
    };

    sessionApi.onSessionRemoved = (removedId) => {
      const agentId = selectedAgentRef.current;
      const queueSessionId = resolveAgentScopedQueueSessionId(
        removedId,
        agentId,
        (rawSessionId) => sessionApi.getQueueSessionId(rawSessionId),
      );
      clearStoredInputQueue(queueSessionId);
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

      const resolvedTarget = sessionApi.getRoutableSessionId(targetId, realId);
      if (!resolvedTarget) return;

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
      lastSessionIdRef.current = null;
      sessionApi.lastActiveChatId = sessionId;
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
  const prevSelectedAgentRef = useRef(selectedAgent);
  // Switch the runtime scope before the browser paints the newly selected
  // Agent. With a passive effect, a long conversation can leave the previous
  // Agent's sender briefly interactive after the selector already shows the
  // destination Agent; inputs queued in that window are then hidden when the
  // SDK remounts under the correct scope.
  useLayoutEffect(() => {
    const prevAgent = prevSelectedAgentRef.current;
    if (prevAgent !== selectedAgent && prevAgent !== undefined) {
      // Keep loop-status tracking busy until the remounted SDK reports its
      // loading state for the destination agent.
      setChatLoading(true);

      // Window identity globals are only rewritten when another session
      // loads, so reset them explicitly — otherwise the new agent inherits
      // the previous agent's session/channel (possibly a deleted channel)
      // and the first message of a fresh chat would carry it.
      sessionApi.resetWindowIdentity();

      // Save current chat ID for the agent we're leaving
      const currentChatId =
        chatIdRef.current || lastSessionIdRef.current || undefined;
      if (currentChatId && prevAgent) {
        setLastChatId(prevAgent, currentChatId);
      }

      // Restore last chat ID for the agent we're switching to
      const restored = getLastChatId(selectedAgent);
      // Mark the current session as stale before replacing the runtime scope,
      // so late callbacks from the old SDK instance cannot navigate back.
      staleAutoSelectedIdRef.current =
        lastSessionIdRef.current || chatIdRef.current || null;
      lastSessionIdRef.current = null;

      // React Router applies navigation on a later render. Pin the destination
      // chat to the destination agent until that route catches up, and reset
      // the singleton before restoring its preferred chat.
      pendingAgentChatScopeRef.current = {
        agentId: selectedAgent,
        chatId: restored,
      };
      runtimeAgentRef.current = selectedAgent;
      sessionApi.setActiveAgent(selectedAgent, restored ?? null);
      chatIdRef.current = restored;

      if (restored) {
        navigateRef.current(buildSessionPath("chat", restored), {
          replace: true,
        });
      } else {
        navigateRef.current("/chat", { replace: true });
      }

      queueDrainBlockedUntilRef.current.set(
        selectedAgent,
        Date.now() + AGENT_SWITCH_QUEUE_SETTLE_MS,
      );
      setRefreshKey((prev) => prev + 1);
    }
    prevSelectedAgentRef.current = selectedAgent;
  }, [selectedAgent, setLastChatId, getLastChatId]);

  useEffect(() => {
    const pendingScope = pendingAgentChatScopeRef.current;
    if (
      pendingScope?.agentId === runtimeAgent &&
      pendingScope.chatId === chatId
    ) {
      pendingAgentChatScopeRef.current = null;
    }
  }, [chatId, runtimeAgent]);

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
    async (
      data: QueuedChatRequestData & {
        input?: Array<Record<string, unknown>>;
        biz_params?: Record<string, unknown>;
        signal?: AbortSignal;
      },
    ): Promise<Response> => {
      const { input = [], biz_params: rawBizParams } = data;
      const bizParams =
        rawBizParams && typeof rawBizParams === "object"
          ? rawBizParams
          : undefined;
      const queuedSessionId =
        typeof data.session_id === "string" && data.session_id.trim()
          ? data.session_id
          : undefined;
      const queuedAgentId =
        typeof data.agent_id === "string" && data.agent_id
          ? data.agent_id
          : undefined;
      const queuedRequestId = getQueueRequestId(data);
      const requestBizParams = bizParams
        ? Object.fromEntries(
            Object.entries(bizParams).filter(
              ([key]) => key !== INTERNAL_QUEUE_REQUEST_ID_PARAM,
            ),
          )
        : undefined;
      const session: SessionInfo = input[input.length - 1]?.session || {};
      const requestContext = resolveChatRequestContext({
        data,
        session,
        selectedAgent: runtimeAgent,
        getSessionIdentity: (sessionId?: string) =>
          sessionApi.getSessionIdentity(sessionId),
        defaultUserId: DEFAULT_USER_ID,
        defaultChannel: DEFAULT_CHANNEL,
      });
      const requestAgentId = requestContext.agentId;

      const headers: Record<string, string> = {
        "Content-Type": "application/json",
        ...buildAuthHeaders(),
        "X-Agent-Id": requestAgentId,
      };

      if (usesQwenPawBackend) {
        let activeModels: Awaited<
          ReturnType<typeof providerApi.getActiveModels>
        >;
        try {
          activeModels = await providerApi.getActiveModels({
            scope: "effective",
            agent_id: requestAgentId,
          });
        } catch (error) {
          if (queuedRequestId) {
            throw error;
          }
          setShowModelPrompt(true);
          return buildModelError();
        }
        if (
          !activeModels?.active_llm?.provider_id ||
          !activeModels?.active_llm?.model
        ) {
          setShowModelPrompt(true);
          if (queuedRequestId) {
            throw new Error("Model not configured");
          }
          return buildModelError();
        }
      }

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
      const userText = rewrittenInput
        .filter((message: any) => message.role === "user")
        .map(extractUserMessageText)
        .join("\n")
        .trim();
      let requestBody: Record<string, unknown> = {
        input: rewrittenInput,
        session_id: requestContext.sessionId,
        user_id: requestContext.userId,
        channel: requestContext.channel,
        agent_id: requestAgentId,
        stream: true,
        ...requestBizParams,
      };

      for (const entry of sortByOrder(
        extLists[ChatList.requestPayloadTransforms],
      )) {
        const next = entry.item.transform({
          payload: requestBody,
          sessionId: String(requestBody.session_id || ""),
          selectedAgent: requestAgentId,
        });
        if (next && typeof next === "object") {
          requestBody = next;
        }
      }

      if (usesQwenPawBackend) {
        applyApprovalLevelToRequestBody(
          requestBody,
          sessionApprovalLevelRef.current,
          runningConfigApprovalLevel,
        );
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
        (data.session_id
          ? String(requestBody.session_id || "")
          : chatIdRef.current) ??
        String(requestBody.session_id || "");
      if (backendChatId && userText) {
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

      headlineStreamFilterRef.current = createHeadlineFilterState();

      const response = await fetch(getApiUrl("/console/chat"), {
        method: "POST",
        headers,
        body: JSON.stringify(requestBody),
        signal: data.signal,
      });

      if (!response.ok && queuedRequestId) {
        let errorMessage = `Queue request failed (${response.status})`;
        try {
          errorMessage = (await response.clone().text()) || errorMessage;
        } catch {
          // Keep the HTTP status when the response body cannot be read.
        }
        throw new Error(errorMessage);
      }

      const localIdToResolve =
        queuedSessionId || sessionApi.lastActiveChatId || chatIdRef.current;
      if (response.ok && localIdToResolve) {
        // Always attempt resolution: triggerResolve now captures the owning
        // agent and survives a subsequent Agent switch (it falls back to an
        // agent-scoped listChats when the singleton has been re-scoped).
        // Skipping resolution here used to strand the temp queue forever.
        sessionApi.triggerResolve(localIdToResolve, runtimeAgent);
      }

      const wrappedResponse = wrapChatResponseUsageStream(response, chatRef);
      if (!response.ok || !queuedAgentId || !queuedRequestId) {
        return wrappedResponse;
      }

      acceptedQueuedInputRef.current.add(queuedRequestId);
      // If the stream is aborted by an Agent switch, the SDK consults this
      // short-lived acceptance marker and consumes the item instead of
      // restoring and sending it twice. Normal completion clears it eagerly.
      window.setTimeout(
        () => acceptedQueuedInputRef.current.delete(queuedRequestId),
        ACCEPTED_QUEUE_TOMBSTONE_TTL_MS,
      );
      return clearAcceptedQueueRequestOnStreamCompletion(wrappedResponse, () =>
        acceptedQueuedInputRef.current.delete(queuedRequestId),
      );
    },
    [extLists, runtimeAgent, runningConfigApprovalLevel, usesQwenPawBackend],
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

        const res = await chatApi.uploadFile(file);
        onProgress?.({ percent: 100 });
        const previewUrl = chatApi.filePreviewUrl(res.url);
        onSuccess({ url: previewUrl });
      } catch (e) {
        onError?.(e instanceof Error ? e : new Error(String(e)));
      }
    },
    [multimodalCaps, t, usesQwenPawBackend],
  );

  const options = useMemo(() => {
    const i18nConfig = getDefaultConfig(t);
    const hostCommands: CommandSuggestion[] = [
      {
        command: "/new",
        value: "new",
        description: "",
      },
      {
        command: "/clear",
        value: "clear",
        description: t("chat.commands.clear.description"),
      },
    ];
    const nativeCommands: CommandSuggestion[] = usesQwenPawBackend
      ? [
          {
            command: "/compact",
            value: "compact",
            description: t("chat.commands.compact.description"),
          },
          {
            command: "/skills",
            value: "skills",
            description: t("chat.commands.skills.description"),
          },
        ]
      : backendCommands.map((item) => ({
          command: `/${item.name}`,
          value: item.name,
          description: t(
            `chat.commands.${item.name}.description`,
            item.description,
          ),
        }));
    const commandSuggestions = [...hostCommands, ...nativeCommands];
    const reservedCommands = new Set(
      commandSuggestions.map((item) => item.command.slice(1).trim()),
    );
    const loopCommandNames = new Set(
      loopAvailableModes.map((mode) => mode.slash_command).filter(Boolean),
    );
    const skillSuggestions: CommandSuggestion[] = consoleSkills
      .filter(
        (skill) =>
          !reservedCommands.has(skill.name) &&
          !loopCommandNames.has(skill.name),
      )
      .sort((a, b) => a.name.localeCompare(b.name))
      .map((skill) => ({
        command: `/${skill.name}`,
        value: skill.name,
        description: "",
      }));
    const handleBeforeSubmit = async () => {
      if (isComposingRef.current) return false;
      localStorage.removeItem(getDraftStorageKey(runtimeAgent));
      draftSuppressed = true;
      if (!inputQueueEnabled) {
        clearSenderTextareaOnNextTick();
      }

      const textarea = document
        .querySelector('[class*="sender"]')
        ?.querySelector("textarea") as HTMLTextAreaElement | null;
      if (textarea) {
        const prepared = usesQwenPawBackend
          ? beginLoopModeSubmission(textarea.value)
          : textarea.value;
        if (prepared !== textarea.value) {
          setTextareaValue(textarea, prepared);
        }
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

    const baseSuggestions = [...commandSuggestions, ...skillSuggestions].map(
      (item) => ({
        label: renderSuggestionLabel(item.command, item.description),
        value: item.value,
      }),
    );
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
            <ChatSessionInitializer resolveChatId={resolveInitializerChatId} />
            <RuntimeLoadingBridge
              bridgeRef={runtimeLoadingBridgeRef}
              onLoadingChange={setChatLoading}
            />
            <ChatHeaderTitle />
            <span style={{ flex: 1 }} />
            {usesQwenPawBackend ? (
              <ModelSelector />
            ) : backendCapabilities?.model_selection ? (
              <HarnessModelSelector providerId={selectedAgentBackend} />
            ) : null}
            <ChatActionGroup
              onToggleHistory={
                effectiveIsFullMode ? toggleHistoryPanel : undefined
              }
              historyOpen={effectiveIsFullMode ? historyPanelOpen : false}
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
        prefix: (
          <>
            {whisperEnabled ? (
              <WhisperSpeechButton
                ref={whisperSpeechRef}
                onTranscription={handleWhisperTranscription}
              />
            ) : null}
            {usesQwenPawBackend && <LoopModeSelector />}
            {pluginSenderPrefix}
          </>
        ),
        actionAffix: (
          <span
            style={{
              display: "inline-flex",
              alignItems: "center",
              gap: 4,
            }}
          >
            {(usesQwenPawBackend || backendCapabilities?.context_usage) && (
              <ContextUsageIndicator
                onCompact={handleCompactCommand}
                onNew={handleNewCommand}
              />
            )}
            {usesQwenPawBackend ? (
              <ApprovalLevelToggle
                sessionId={approvalSessionId}
                runningConfigApprovalLevel={runningConfigApprovalLevel}
                onChange={(sessionOverride) => {
                  sessionApprovalLevelRef.current = sessionOverride;
                }}
              />
            ) : approvalPresets.length > 0 ? (
              <HarnessApprovalToggle
                backend={selectedAgentBackend}
                sessionId={approvalSessionId}
                presets={approvalPresets}
                onChange={(settings) => {
                  backendControlsRef.current = settings;
                }}
              />
            ) : null}
          </span>
        ),
        ...(supportsAttachments
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
        placeholder: extPlaceholder ?? t("chat.inputPlaceholder"),
        ...(extDisclaimer !== undefined ? { disclaimer: extDisclaimer } : {}),
        suggestions: [...baseSuggestions, ...activePluginSuggestions],
        queue: {
          enable: inputQueueEnabled,
          // Scope the SDK input queue by agent plus CoPaw's stable backend session_id.
          // The visible route may switch from a local timestamp to a chat UUID
          // after the first response, but both IDs map back to the same session.
          // The backend still receives the raw session_id through getRequestContext.
          getSessionId: resolveInputQueueSessionId,
          getRequestContext: (sessionId?: string) => {
            const rawSessionId = stripQueueAgentPrefix(sessionId);
            const backendSessionId = rawSessionId
              ? resolveBackendSessionId(rawSessionId)
              : "";
            const identity = sessionApi.getSessionIdentity(
              rawSessionId || backendSessionId,
            );
            const queueRequestId = createQueueRequestId();
            return {
              session_id: backendSessionId || identity.sessionId,
              user_id: identity.userId,
              channel: identity.channel,
              agent_id: getQueueAgentId(sessionId) || runtimeAgent,
              // Persist a stable ID inside the SDK queue item. The host records
              // backend acceptance against this exact request, so the SDK can
              // decide whether an Agent-switch abort should restore or consume
              // the item without confusing duplicate text.
              qwenpaw_queue_request_id: queueRequestId,
              // The SDK narrows queued data before customFetch to its public
              // request fields. Carry the same ID through biz_params, then
              // strip it before the backend payload is built above.
              biz_params: {
                [INTERNAL_QUEUE_REQUEST_ID_PARAM]: queueRequestId,
              },
            };
          },
          shouldRestoreOnError: ({ data }: { data: QueuedChatRequestData }) => {
            return shouldRestoreQueuedInputAfterError(
              data,
              acceptedQueuedInputRef.current,
            );
          },
          isSessionRunning: async ({
            sessionId,
            queueSessionId,
          }: IAgentScopeRuntimeWebUIQueueSessionContext) => {
            const queueAgentId =
              getQueueAgentId(queueSessionId) ||
              getQueueAgentId(sessionId) ||
              runtimeAgent;
            const queueDrainBlockedUntil =
              queueDrainBlockedUntilRef.current.get(queueAgentId) ?? 0;
            if (
              Date.now() < queueDrainBlockedUntil &&
              hasStoredInputQueueItems(queueSessionId)
            ) {
              return true;
            }

            const currentQueueSessionId = chatIdRef.current
              ? resolveInputQueueSessionId(chatIdRef.current)
              : undefined;
            const visibleQueueMatches =
              !!queueSessionId &&
              !!currentQueueSessionId &&
              queueSessionId === currentQueueSessionId;
            const visibleSessionMatches =
              !queueSessionId &&
              !!sessionId &&
              stripQueueAgentPrefix(sessionId) === chatIdRef.current;

            if (
              (visibleQueueMatches || visibleSessionMatches) &&
              isFrontendChatRunning()
            ) {
              return true;
            }

            const candidates = [
              stripQueueAgentPrefix(queueSessionId),
              stripQueueAgentPrefix(sessionId),
              ...(visibleQueueMatches || visibleSessionMatches
                ? [chatIdRef.current, sessionApi.lastActiveChatId]
                : []),
            ]
              .flatMap((id) => [
                sessionApi.getRoutableSessionId(id),
                id ? sessionApi.getQueueSessionId(id) : "",
              ])
              .filter(
                (id): id is string =>
                  !!id &&
                  !sessionApi.isLocalSessionId(id) &&
                  !sessionApi.isUnresolvedLocalSession(id),
              );

            for (const statusChatId of Array.from(new Set(candidates))) {
              try {
                const chat = await chatApi.getChat(statusChatId, {
                  agentId: queueAgentId,
                });
                if (chat.status === "running") return true;
              } catch {
                // Try the next alias; queue/session ids can arrive before
                // the local-id to backend-id mapping has propagated.
              }
            }
            return false;
          },
        },
      },
      session: buildChatSessionOptions(
        controlledSdkSessionId,
        scopedSessionApi,
      ),
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

          const reconnectIdentity = sessionApi.getSessionIdentity();
          headlineStreamFilterRef.current = createHeadlineFilterState();
          const response = await fetch(getApiUrl("/console/chat"), {
            method: "POST",
            headers,
            body: JSON.stringify({
              reconnect: true,
              session_id: sessionApi.getBackendSessionId(data.session_id),
              user_id: reconnectIdentity.userId,
              channel: reconnectIdentity.channel,
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
    consoleSkills,
    loopAvailableModes,
    runtimeAgent,
    runtimeChatId,
    resolveInitializerChatId,
    inputQueueEnabled,
    isFrontendChatRunning,
    controlledSdkSessionId,
    scopedSessionApi,
    resolveBackendSessionId,
    resolveInputQueueSessionId,
    selectedAgentBackend,
    backendCapabilities,
    backendCommands,
    approvalPresets,
    usesQwenPawBackend,
    supportsAttachments,
    runningConfigApprovalLevel,
    approvalSessionId,
    onFileCardClick,
    whisperChecked,
    whisperEnabled,
    handleWhisperTranscription,
    isWideMode,
    toggleWideMode,
    effectiveIsFullMode,
    historyPanelOpen,
    toggleHistoryPanel,
    handleCompactCommand,
    handleNewCommand,
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
            key={`${runtimeAgent}:${refreshKey}`}
            options={options}
          />
        </div>

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
