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
  formatMessageTime,
  type CopyableResponse,
  type RuntimeLoadingBridgeApi,
} from "./utils";
import { openExternalLink } from "../../utils/openExternalLink";
import { getLastEditorCopy } from "../Coding/lastEditorCopy";
import { useUploadLimitStore } from "../../stores/uploadLimitStore";

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

  // Redirect to /coding when coding mode is active
  useEffect(() => {
    if (initialized && codingMode) {
      navigate("/coding", { replace: true });
    }
  }, [initialized, codingMode, navigate]);

  const chatId = useMemo(() => {
    const match = location.pathname.match(/^\/chat\/(.+)$/);
    return match?.[1];
  }, [location.pathname]);
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
  const { message } = useAppMessage();
  const { approvals, setApprovals } = useApprovalContext();
  const [approvalRequests, setApprovalRequests] = useState<
    Map<string, ApprovalMessageData>
  >(new Map());
  const [planEnabled, setPlanEnabled] = useState(false);

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
  isChatActiveRef.current =
    location.pathname === "/" || location.pathname.startsWith("/chat");

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
    sessionApi.onSessionIdResolved = (realId) => {
      if (!isChatActiveRef.current) return;
      // Update URL when realId is resolved, regardless of current chatId
      // (chatId may be undefined if URL was cleared in onSessionCreated)
      lastSessionIdRef.current = realId;
      navigateRef.current(`/chat/${realId}`, { replace: true });
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
        navigateRef.current("/chat", { replace: true });
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
        navigateRef.current(`/chat/${targetId}`, { replace: true });
      }
    };

    sessionApi.onSessionCreated = () => {
      if (!isChatActiveRef.current) return;
      // Clear URL when creating new session, wait for realId resolution to update
      lastSessionIdRef.current = null;
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
    [selectedAgent],
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
        onSuccess({ url: chatApi.filePreviewUrl(res.url) });
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
      localStorage.removeItem(getDraftStorageKey(selectedAgent));
      draftSuppressed = true;
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

    const sortByOrder = <T extends { item: { order?: number } }>(arr: T[]) =>
      arr.slice().sort((a, b) => (a.item.order ?? 100) - (b.item.order ?? 100));

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
            <RuntimeLoadingBridge bridgeRef={runtimeLoadingBridgeRef} />
            <ChatHeaderTitle />
            <span style={{ flex: 1 }} />
            <ModelSelector />
            <ChatActionGroup
              planEnabled={planEnabled}
              onToggleHistory={toggleHistoryPanel}
              historyOpen={historyPanelOpen}
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

          return fetch(getApiUrl("/console/chat"), {
            method: "POST",
            headers,
            body: JSON.stringify({
              reconnect: true,
              session_id: window.currentSessionId || data.session_id,
              user_id: window.currentUserId || DEFAULT_USER_ID,
              channel: window.currentChannel || DEFAULT_CHANNEL,
            }),
            signal: data.signal,
          });
        },
      },
      customToolRenderConfig:
        Object.keys(mergedToolRenderers).length > 0
          ? mergedToolRenderers
          : undefined,
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
  ]);

  return (
    <div className={styles.chatPageRoot}>
      {/* Main chat area */}
      <div className={styles.chatMainArea}>
        <div className={styles.chatMessagesArea}>
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

      {/* Right-side history panel */}
      {historyPanelOpen && (
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
