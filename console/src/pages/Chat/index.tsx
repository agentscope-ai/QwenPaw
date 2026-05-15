import {
  AgentScopeRuntimeWebUI,
  IAgentScopeRuntimeWebUIOptions,
  type IAgentScopeRuntimeWebUIRef,
  type IAgentScopeRuntimeWebUIMessage,
} from "@agentscope-ai/chat";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import ReactDOM from "react-dom";
import { Button, Modal, Result, Tooltip } from "antd";
import { useAppMessage } from "../../hooks/useAppMessage";
import { ExclamationCircleOutlined, SettingOutlined } from "@ant-design/icons";
import { SparkCopyLine, SparkAttachmentLine } from "@agentscope-ai/icons";
import { usePlugins } from "../../plugins/PluginContext";
import { useTranslation } from "react-i18next";
import { useLocation, useNavigate } from "react-router-dom";
import sessionApi from "./sessionApi";
import defaultConfig, { getDefaultConfig } from "./OptionsPanel/defaultConfig";
import { chatApi } from "../../api/modules/chat";
import { agentApi } from "../../api/modules/agent";
import { getApiUrl } from "../../api/config";
import { buildAuthHeaders } from "../../api/authHeaders";
import { providerApi } from "../../api/modules/provider";
import type { ProviderInfo, ModelInfo } from "../../api/types";
import ModelSelector from "./ModelSelector";
import { useTheme } from "../../contexts/ThemeContext";
import { useAgentStore } from "../../stores/agentStore";
import { useChatAnywhereInput, useChatAnywhereSessionsState } from "@agentscope-ai/chat";
import styles from "./index.module.less";
import { IconButton } from "@agentscope-ai/design";
import ChatActionGroup from "./components/ChatActionGroup";
import ChatHeaderTitle from "./components/ChatHeaderTitle";
import ChatSessionInitializer from "./components/ChatSessionInitializer";
import { ApprovalCard } from "../../components/ApprovalCard/ApprovalCard";
import { commandsApi } from "../../api/modules/commands";
import { useApprovalContext } from "../../contexts/ApprovalContext";
import { planApi } from "../../api/modules/plan";
import TokenUsageBadge, {
  loadTokenBadgeSnapshot,
  migrateTokenBadgeSnapshot,
  resolveTokenBadgeStorageKey,
  saveTokenBadgeSnapshot,
} from "./components/TokenUsageBadge";
import type { TokenUsageBadgeSnapshot } from "./components/TokenUsageBadge";

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
  copyText,
  extractCopyableText,
  buildModelError,
  normalizeContentUrls,
  extractUserMessageText,
  extractTextFromMessage,
  setTextareaValue,
  type CopyableResponse,
  type RuntimeLoadingBridgeApi,
} from "./utils";

const CHAT_ATTACHMENT_MAX_MB = 10;

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

function toSnapshotFromUsagePayload(
  usage: unknown,
  ctx: unknown,
): TokenUsageBadgeSnapshot | null {
  // Normalize usage: ensure it has at least one meaningful token field
  const hasUsage =
    usage &&
    typeof usage === "object" &&
    (typeof (usage as Record<string, unknown>).total_tokens === "number" ||
      typeof (usage as Record<string, unknown>).prompt_tokens === "number" ||
      typeof (usage as Record<string, unknown>).completion_tokens === "number");

  const hasCtx =
    ctx &&
    typeof ctx === "object" &&
    typeof (ctx as Record<string, unknown>).estimated_tokens === "number";

  if (!hasUsage && !hasCtx) return null;

  return {
    usage: hasUsage ? (usage as TokenUsageBadgeSnapshot["usage"]) : null,
    context: hasCtx ? (ctx as TokenUsageBadgeSnapshot["context"]) : null,
    receivedAt: Date.now(),
  };
}

function renderSuggestionLabel(command: string, description: string) {
  return (
    <div className={styles.suggestionLabel}>
      <span className={styles.suggestionCommand}>{command}</span>
      <span className={styles.suggestionDescription}>{description}</span>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const DEFAULT_USER_ID = "default";
const DEFAULT_CHANNEL = "console";

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

/** Fetch and track multimodal capabilities for the active model. */
function useMultimodalCapabilities(
  refreshKey: number,
  locationPathname: string,
  isChatActive: () => boolean,
  selectedAgent: string,
) {
  const [multimodalCaps, setMultimodalCaps] = useState<{
    supportsMultimodal: boolean;
    supportsImage: boolean;
    supportsVideo: boolean;
  }>({ supportsMultimodal: false, supportsImage: false, supportsVideo: false });

  const fetchMultimodalCaps = useCallback(async () => {
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
        setMultimodalCaps({
          supportsMultimodal: false,
          supportsImage: false,
          supportsVideo: false,
        });
        return;
      }
      const provider = (providers as ProviderInfo[]).find(
        (p) => p.id === activeProviderId,
      );
      if (!provider) {
        setMultimodalCaps({
          supportsMultimodal: false,
          supportsImage: false,
          supportsVideo: false,
        });
        return;
      }
      const allModels: ModelInfo[] = [
        ...(provider.models ?? []),
        ...(provider.extra_models ?? []),
      ];
      const model = allModels.find((m) => m.id === activeModelId);
      setMultimodalCaps({
        supportsMultimodal: model?.supports_multimodal ?? false,
        supportsImage: model?.supports_image ?? false,
        supportsVideo: model?.supports_video ?? false,
      });
    } catch {
      setMultimodalCaps({
        supportsMultimodal: false,
        supportsImage: false,
        supportsVideo: false,
      });
    }
  }, [selectedAgent]);

  // Fetch caps on mount and whenever refreshKey changes
  useEffect(() => {
    fetchMultimodalCaps();
  }, [fetchMultimodalCaps, refreshKey]);

  // Also poll caps when navigating back to chat
  useEffect(() => {
    if (isChatActive()) {
      fetchMultimodalCaps();
    }
  }, [locationPathname, fetchMultimodalCaps, isChatActive]);

  // Listen for model-switched event from ModelSelector
  useEffect(() => {
    const handler = () => {
      fetchMultimodalCaps();
    };
    window.addEventListener("model-switched", handler);
    return () => window.removeEventListener("model-switched", handler);
  }, [fetchMultimodalCaps]);

  return multimodalCaps;
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

function RuntimeLoadingBridge({
  bridgeRef,
}: {
  bridgeRef: { current: RuntimeLoadingBridgeApi | null };
}) {
  const { setLoading, getLoading } = useChatAnywhereInput(
    (value) =>
      ({
        setLoading: value.setLoading,
        getLoading: value.getLoading,
      }) as RuntimeLoadingBridgeApi,
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

  return null;
}

export default function ChatPage() {
  const { t, i18n } = useTranslation();
  const navigate = useNavigate();
  const location = useLocation();
  const { isDark } = useTheme();
  const chatId = useMemo(() => {
    const match = location.pathname.match(/^\/chat\/(.+)$/);
    return match?.[1];
  }, [location.pathname]);

  /** Canonical id for token-badge sessionStorage (UUID when resolved). */
  const storageIdForTokenBadge = useCallback((raw: string) => {
    if (!raw) return "";
    return sessionApi.getRealIdForSession(raw) ?? raw;
  }, []);

  const { sessions } = useChatAnywhereSessionsState();

  const [showModelPrompt, setShowModelPrompt] = useState(false);
  const { selectedAgent } = useAgentStore();
  const { toolRenderConfig } = usePlugins();
  const [refreshKey, setRefreshKey] = useState(0);
  const runtimeLoadingBridgeRef = useRef<RuntimeLoadingBridgeApi | null>(null);
  const { message } = useAppMessage();
  const { approvals } = useApprovalContext();
  const [approvalRequests, setApprovalRequests] = useState<
    Map<string, ApprovalMessageData>
  >(new Map());
  const [planEnabled, setPlanEnabled] = useState(false);
  const [tokenSnapshot, setTokenSnapshot] =
    useState<TokenUsageBadgeSnapshot | null>(null);
    const tokenSnapshotRef = useRef<TokenUsageBadgeSnapshot | null>(null);
  tokenSnapshotRef.current = tokenSnapshot;
  const collectTokenBadgeAliases = useCallback(
    (rawSessionId: string): string[] => {
      const aliases = new Set<string>();
      if (rawSessionId) aliases.add(rawSessionId);
      aliases.add(window.currentSessionId || "");
      aliases.add(chatIdRef.current || "");
      for (const id of [...aliases]) {
        if (!id) continue;
        const key = resolveTokenBadgeStorageKey(id);
        if (!key) continue;
        try {
          const raw = sessionStorage.getItem(key);
          if (raw) {
            const data = JSON.parse(raw);
            if (data?._relatedKeys && Array.isArray(data._relatedKeys)) {
              for (const k of data._relatedKeys) aliases.add(k);
            }
          }
        } catch {
          // ignore parse errors
        }
      }
      return [...aliases];
    },
    [],
  );
  const readTokenSnapshotForSession = useCallback(
    (rawSessionId: string) => {
      const aliasList = collectTokenBadgeAliases(rawSessionId);
      let latest: TokenUsageBadgeSnapshot | null = null;
      for (const id of aliasList) {
        const loaded = loadTokenBadgeSnapshot(id);
        if (!loaded) continue;
        if (!latest || (loaded.receivedAt || 0) >= (latest.receivedAt || 0)) {
          latest = loaded;
        }
      }
      return latest;
    },
    [collectTokenBadgeAliases],
  );
  const saveTokenSnapshotForSession = useCallback(
    (rawSessionId: string, snapshot: TokenUsageBadgeSnapshot) => {
      for (const id of collectTokenBadgeAliases(rawSessionId)) {
        const key = resolveTokenBadgeStorageKey(id);
        if (key) saveTokenBadgeSnapshot(key, snapshot);
      }
    },
    [collectTokenBadgeAliases],
  );
  const applyTokenSnapshotUpdate = useCallback(
    (
      usage: unknown,
      ctx: unknown,
      preferredSessionId?: string,
      fallbackToPrev = true,
    ) => {
      const base = toSnapshotFromUsagePayload(usage, ctx);
      if (!base) return;
      setTokenSnapshot((prev: TokenUsageBadgeSnapshot | null) => {
        const next: TokenUsageBadgeSnapshot = {
          usage: base.usage ?? (fallbackToPrev ? prev?.usage ?? null : null),
          context: base.context ?? (fallbackToPrev ? prev?.context ?? null : null),
          receivedAt: Date.now(),
        };
        const id =
          preferredSessionId ||
          chatIdRef.current ||
          window.currentSessionId ||
          "";
        if (id) saveTokenSnapshotForSession(id, next);
        return next;
      });
    },
    [saveTokenSnapshotForSession],
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

  const isChatActiveRef = useRef(false);
  isChatActiveRef.current =
    location.pathname === "/" || location.pathname.startsWith("/chat");

  const isChatActive = useCallback(() => isChatActiveRef.current, []);

  useEffect(() => {
    if (!isChatActiveRef.current) return;
    const id = storageIdForTokenBadge(chatId || "");
    const loaded = readTokenSnapshotForSession(id);
    if (loaded) setTokenSnapshot(loaded);
  }, [chatId, storageIdForTokenBadge, sessions, readTokenSnapshotForSession]);

  // Consume approvals from Context and filter by current session
  useEffect(() => {
    // Get current session ID from multiple sources
    // During new session creation, chatId may be empty but window.currentSessionId gets set
    const currentSessionId = window.currentSessionId || chatId || "";

    // Filter approvals by root_session_id (includes children sessions)
    console.debug(
      "[Approval] Filtering approvals:",
      "currentSessionId=",
      currentSessionId,
      "chatId=",
      chatId,
      "window.currentSessionId=",
      window.currentSessionId,
      "approvals=",
      approvals.map((a) => ({
        tool: a.tool_name,
        session: a.session_id.slice(0, 8),
        root: a.root_session_id.slice(0, 8),
      })),
    );

    // If no session ID yet, check if we have approvals that could tell us the session
    // (e.g., first message sent, approval arrives before session ID is set in window)
    let effectiveSessionId = currentSessionId;
    if (!effectiveSessionId && approvals.length > 0) {
      // Use the root_session_id from the first approval as a hint
      // This handles the race condition where approval arrives before session ID is propagated
      effectiveSessionId = approvals[0].root_session_id;
      console.log(
        "[Approval] No session ID yet, using first approval's root_session_id:",
        effectiveSessionId,
      );
    }

    const sessionApprovals = effectiveSessionId
      ? approvals.filter(
          (approval) => approval.root_session_id === effectiveSessionId,
        )
      : approvals; // Show all if no session ID (fallback)

    console.debug(
      "[Approval] After filtering:",
      sessionApprovals.length,
      "approval(s)",
    );

    // Convert to map for display
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
      console.log("[Approval] handleApprove called:", requestId);
      console.log(
        "[Approval] Current requests map size:",
        approvalRequests.size,
      );
      const request = approvalRequests.get(requestId);
      if (!request) {
        console.error("[Approval] Request not found:", requestId);
        return;
      }

      // Use currentSessionId (root session) instead of request.sessionId (sub-agent session)
      const rootSessionId = window.currentSessionId || chatId || "";
      console.log("[Approval] Sending approve command:", {
        requestId,
        rootSessionId,
        subAgentSessionId: request.sessionId,
      });

      try {
        // Add exit animation class
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
        console.log("[Approval] Approve command sent successfully");
        message.success(t("approval.approved"));

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
        message.error(t("approval.approveFailed"));
        console.error("[Approval] Failed to approve:", error);
      }
    },
    [approvalRequests, chatId, t, message],
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
    [approvalRequests, chatId, t, message],
  );

  // Use custom hooks for better separation of concerns
  const isComposingRef = useIMEComposition(isChatActive);
  const multimodalCaps = useMultimodalCapabilities(
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
  const pendingClearHistoryRef = useRef(false);
  const whisperSpeechRef = useRef<WhisperSpeechButtonRef>(null);
  const [whisperEnabled, setWhisperEnabled] = useState(false);

  // Check if Whisper transcription is configured
  useEffect(() => {
    agentApi
      .getTranscriptionProviderType()
      .then((res) => {
        setWhisperEnabled(res.transcription_provider_type !== "disabled");
      })
      .catch(() => setWhisperEnabled(false));
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
    sessionApi.onSessionIdResolved = (tempId, resolvedRealId) => {
      if (!isChatActiveRef.current) return;
      // Update URL when realId is resolved, regardless of current chatId
      // (chatId may be undefined if URL was cleared in onSessionCreated)
      lastSessionIdRef.current = resolvedRealId;
      migrateTokenBadgeSnapshot(tempId, resolvedRealId);
      const fromStorage = readTokenSnapshotForSession(resolvedRealId);
      if (!fromStorage && tokenSnapshotRef.current) {
        saveTokenSnapshotForSession(resolvedRealId, tokenSnapshotRef.current);
        setTokenSnapshot(tokenSnapshotRef.current);
      } else {
        setTokenSnapshot(fromStorage);
      }
      navigateRef.current(`/chat/${resolvedRealId}`, { replace: true });
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
        setTokenSnapshot(null);
        navigateRef.current("/chat", { replace: true });
      }
    };

    sessionApi.onSessionSelected = (
      sessionId: string | null | undefined,
      realId: string | null,
    ) => {
      if (!isChatActiveRef.current) return;
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
        const storeId = storageIdForTokenBadge(targetId);
        setTokenSnapshot(readTokenSnapshotForSession(storeId));
        navigateRef.current(`/chat/${targetId}`, { replace: true });
      }
    };

    sessionApi.onSessionCreated = () => {
      if (!isChatActiveRef.current) return;
      // Clear URL when creating new session, wait for realId resolution to update
      lastSessionIdRef.current = null;
      setTokenSnapshot(null);
      navigateRef.current("/chat", { replace: true });
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
      // Save current chat ID for the agent we're leaving
      const currentChatId =
        chatIdRef.current || lastSessionIdRef.current || undefined;
      if (currentChatId && prevAgent) {
        setLastChatId(prevAgent, currentChatId);
      }

      // Restore last chat ID for the agent we're switching to
      const restored = getLastChatId(selectedAgent);
      if (restored) {
        navigateRef.current(`/chat/${restored}`, { replace: true });
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

      const requestBody = {
        input: rewrittenInput,
        session_id: window.currentSessionId || session?.session_id || "",
        user_id: window.currentUserId || session?.user_id || DEFAULT_USER_ID,
        channel: window.currentChannel || session?.channel || DEFAULT_CHANNEL,
        language: i18n.resolvedLanguage || i18n.language,
        stream: true,
        ...biz_params,
      };

      const backendChatId =
        sessionApi.getRealIdForSession(requestBody.session_id) ??
        chatIdRef.current ??
        requestBody.session_id;
      if (backendChatId) {
        const userText = rewrittenInput
          .filter((m: any) => m.role === "user")
          .map(extractUserMessageText)
          .join("\n")
          .trim();
        if (userText) {
          sessionApi.setLastUserMessage(backendChatId, userText);
        }
      }

      const response = await fetch(getApiUrl("/console/chat"), {
        method: "POST",
        headers,
        body: JSON.stringify(requestBody),
        signal: data.signal,
      });

      return response;
    },
    [i18n.language, i18n.resolvedLanguage, selectedAgent],
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
        const isWithinLimit = sizeMb < CHAT_ATTACHMENT_MAX_MB;

        if (!isWithinLimit) {
          message.error(
            t("chat.attachments.fileSizeExceeded", {
              limit: CHAT_ATTACHMENT_MAX_MB,
              size: sizeMb.toFixed(2),
            }),
          );
          onError?.(new Error(`File size exceeds ${CHAT_ATTACHMENT_MAX_MB}MB`));
          return;
        }

        const res = await chatApi.uploadFile(file);
        onProgress?.({ percent: 100 });
        onSuccess({ url: chatApi.filePreviewUrl(res.url) });
      } catch (e) {
        onError?.(e instanceof Error ? e : new Error(String(e)));
      }
    },
    [multimodalCaps, t],
  );

  const handleStopChat = useCallback(
    (sessionId: string) => {
      const chatId =
        sessionApi.getRealIdForSession(sessionId) ?? sessionId;
      console.log("[Stop] session_id=%s resolved chat_id=%s", sessionId, chatId);
      if (!chatId) {
        console.warn("[Stop] No chat_id found, cannot stop");
        return;
      }
      chatApi
        .stopChat(chatId, i18n.language)
        .then((res: any) => {
          applyTokenSnapshotUpdate(
            res?.usage,
            res?.context_usage,
            chatId,
            false,
          );
          if (res?.usage_note) {
            const messagesApi = chatRef.current?.messages;
            if (!messagesApi) {
              console.warn("[Stop] messagesApi not available, saving note for next load");
              sessionApi.setLastStopUsageNote(chatId, res.usage_note);
              if (sessionId && sessionId !== chatId) {
                sessionApi.setLastStopUsageNote(sessionId, res.usage_note);
              }
              return;
            }

            const allMessages = messagesApi.getMessages() || [];
            // Find the last assistant message
            let lastAssistantMsg: IAgentScopeRuntimeWebUIMessage | null = null;
            for (let i = allMessages.length - 1; i >= 0; i--) {
              if (allMessages[i].role === "assistant") {
                lastAssistantMsg = allMessages[i];
                break;
              }
            }

            if (!lastAssistantMsg) {
              console.warn("[Stop] No assistant message found, saving note for next load");
              sessionApi.setLastStopUsageNote(chatId, res.usage_note);
              if (sessionId && sessionId !== chatId) {
                sessionApi.setLastStopUsageNote(sessionId, res.usage_note);
              }
              return;
            }

            // Save the preceding user message text so patchLastUserMessage can
            // reconstruct it on session reload when backend history lags behind.
            let interruptedTurnUserText = "";
            for (let i = allMessages.length - 1; i >= 0; i--) {
              if (allMessages[i].role === "user") {
                const userInput = allMessages[i].cards?.[0]?.data?.input;
                if (Array.isArray(userInput) && userInput.length > 0) {
                  const content = userInput[0].content;
                  const text =
                    typeof content === "string"
                      ? content
                      : Array.isArray(content)
                        ? content
                            .filter(
                              (c: Record<string, unknown>) => c.type === "text",
                            )
                            .map((c: Record<string, unknown>) => c.text || "")
                            .join("")
                        : "";
                  if (text) {
                    interruptedTurnUserText = text.trim();
                    console.log("[Debug] handleStopChat setLastUserMessage chatId=%s sessionId=%s", chatId, sessionId);
                    sessionApi.setLastUserMessage(chatId, text);
                    if (sessionId && sessionId !== chatId) {
                      sessionApi.setLastUserMessage(sessionId, text);
                    }
                  }
                }
                break;
              }
            }

            // Guard against duplicate cancel calls (the library fires cancel twice)
            const alreadyHasNote = lastAssistantMsg.cards?.some((card) => {
              if (card?.code !== "AgentScopeRuntimeResponseCard") return false;
              const output = card?.data?.output;
              if (!Array.isArray(output)) return false;
              return output.some((item: Record<string, unknown>) => {
                const content = item?.content;
                if (typeof content === "string") return content.includes(res.usage_note);
                if (Array.isArray(content)) {
                  return content.some(
                    (c: Record<string, unknown>) =>
                      typeof c?.text === "string" &&
                      c.text.includes(res.usage_note),
                  );
                }
                return false;
              });
            });

            // Deep clone so we don't mutate library state
            const updatedMsg = JSON.parse(
              JSON.stringify(lastAssistantMsg),
            ) as IAgentScopeRuntimeWebUIMessage;

            if (alreadyHasNote) {
              console.log("[Stop] Usage note already present, skipping duplicate append");
              sessionApi.saveInterruptedTurn(
                chatId,
                updatedMsg,
                interruptedTurnUserText,
              );
              if (sessionId && sessionId !== chatId) {
                sessionApi.saveInterruptedTurn(
                  sessionId,
                  updatedMsg,
                  interruptedTurnUserText,
                );
              }
              return;
            }
            const responseCard = (
              updatedMsg.cards as Array<{
                code?: string;
                data?: { output?: Array<Record<string, unknown>> };
              }>
            )?.find(
              (card) => card?.code === "AgentScopeRuntimeResponseCard",
            );
            if (responseCard?.data) {
              if (!Array.isArray(responseCard.data.output)) {
                responseCard.data.output = [];
              }
              responseCard.data.output.push({
                id: `stop-usage-${Date.now()}-${Math.random().toString(36).substr(2, 9)}`,
                type: "message",
                role: "assistant",
                content: [
                  {
                    type: "text",
                    text: res.usage_note,
                    status: "completed",
                  },
                ],
                status: "completed",
              });
              ReactDOM.flushSync(() => {
                messagesApi.updateMessage(updatedMsg);
              });

              // Save per user-turn so round 2+ interrupts do not overwrite round 1.
              console.log("[Debug] handleStopChat saveInterruptedTurn chatId=%s sessionId=%s msg.id=%s", chatId, sessionId, updatedMsg.id);
              sessionApi.saveInterruptedTurn(
                chatId,
                updatedMsg,
                interruptedTurnUserText,
              );
              if (sessionId && sessionId !== chatId) {
                console.log("[Debug] handleStopChat saveInterruptedTurn also as sessionId=%s", sessionId);
                sessionApi.saveInterruptedTurn(
                  sessionId,
                  updatedMsg,
                  interruptedTurnUserText,
                );
              }
            }
          }

          sessionApi.setLastStopUsageNote(chatId, res.usage_note);
          if (sessionId && sessionId !== chatId) {
            sessionApi.setLastStopUsageNote(sessionId, res.usage_note);
          }
          console.log("[Debug] handleStopChat setLastStopUsageNote chatId=%s sessionId=%s", chatId, sessionId);
          console.log("[Stop] stopChat API succeeded");
        })
        .catch((err) => {
          console.error("[Stop] Failed to stop chat:", err);
        });
    },
    [i18n.language, applyTokenSnapshotUpdate],
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

    const handleBeforeSubmit = async () => {
      if (isComposingRef.current) return false;
      return true;
    };

    return {
      ...i18nConfig,
      theme: {
        ...defaultConfig.theme,
        darkMode: isDark,
        leftHeader: {
          ...defaultConfig.theme.leftHeader,
        },
        rightHeader: (
          <>
            <ChatSessionInitializer />
            <RuntimeLoadingBridge bridgeRef={runtimeLoadingBridgeRef} />
            <ChatHeaderTitle />
            <span style={{ flex: 1 }} />
            <ModelSelector />
            <ChatActionGroup />
          </>
        ),
      },
      welcome: {
        ...i18nConfig.welcome,
        nick: "QwenPaw",
        avatar: "/qwenpaw.png",
      },
      sender: {
        ...(i18nConfig as any)?.sender,
        beforeSubmit: handleBeforeSubmit,
        allowSpeech: !whisperEnabled,
        prefix: whisperEnabled ? (
          <WhisperSpeechButton
            ref={whisperSpeechRef}
            onTranscription={handleWhisperTranscription}
          />
        ) : undefined,
        attachments: {
          trigger: function (props: any) {
            const tooltipKey = multimodalCaps.supportsMultimodal
              ? multimodalCaps.supportsImage && !multimodalCaps.supportsVideo
                ? "chat.attachments.tooltipImageOnly"
                : "chat.attachments.tooltip"
              : "chat.attachments.tooltipNoMultimodal";
            return (
              <Tooltip title={t(tooltipKey, { limit: CHAT_ATTACHMENT_MAX_MB })}>
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
        placeholder: t("chat.inputPlaceholder"),
        suggestions: commandSuggestions.map((item) => ({
          label: renderSuggestionLabel(item.command, item.description),
          value: item.value,
        })),
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
          const nested =
            payload &&
            typeof payload.data === "object" &&
            payload.data !== null &&
            !Array.isArray(payload.data)
              ? (payload.data as Record<string, unknown>)
              : null;

          const usage = (nested?.usage ?? payload.usage) as
            | TokenUsageBadgeSnapshot["usage"]
            | undefined;
          const ctx = (nested?.context_usage ??
            nested?.contextUsage ??
            payload.context_usage ??
            payload.contextUsage) as
            | TokenUsageBadgeSnapshot["context"]
            | undefined;
          applyTokenSnapshotUpdate(usage, ctx);

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
        cancel(data: { session_id: string }) {
          handleStopChat(data.session_id);
        },
        async reconnect(data: { session_id: string; signal?: AbortSignal }) {
          const headers: Record<string, string> = {
            "Content-Type": "application/json",
            ...buildAuthHeaders(),
          };

          return fetch(getApiUrl("/console/chat"), {
            method: "POST",
            headers,
            body: JSON.stringify({
              reconnect: true,
              session_id: window.currentSessionId || data.session_id,
              user_id: window.currentUserId || DEFAULT_USER_ID,
              channel: window.currentChannel || DEFAULT_CHANNEL,
              language: i18n.resolvedLanguage || i18n.language,
            }),
            signal: data.signal,
          });
        },
      },
      customToolRenderConfig:
        Object.keys(toolRenderConfig).length > 0 ? toolRenderConfig : undefined,
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
        ],
        replace: true,
      },
    } as unknown as IAgentScopeRuntimeWebUIOptions;
  }, [
    customFetch,
    copyResponse,
    handleFileUpload,
    t,
    isDark,
    multimodalCaps,
    toolRenderConfig,
    scheduleHistoryClear,
    planEnabled,
    applyTokenSnapshotUpdate,
    handleStopChat,
  ]);

  return (
    <div
      style={{
        height: "100%",
        width: "100%",
        display: "flex",
        flexDirection: "column",
      }}
    >
      <div className={styles.chatMessagesArea} style={{ position: "relative" }}>
        <AgentScopeRuntimeWebUI
          ref={chatRef}
          key={refreshKey}
          options={options}
        />
        <TokenUsageBadge snapshot={tokenSnapshot} />
              </div>

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
              handleStopChat(window.currentSessionId || "");
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
            ? { background: "#1f1f1f", boxShadow: "0 8px 32px rgba(0,0,0,0.5)" }
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
  );
}
