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
import { useTranslation } from "react-i18next";
import { useLocation, useNavigate } from "react-router-dom";
import sessionApi from "./sessionApi";
import defaultConfig, { getDefaultConfig } from "./OptionsPanel/defaultConfig";
import { chatApi } from "../../api/modules/chat";
import { getApiUrl } from "../../api/config";
import { buildAuthHeaders } from "../../api/authHeaders";
import { providerApi } from "../../api/modules/provider";
import type { ProviderInfo, ModelInfo } from "../../api/types";
import ModelSelector from "./ModelSelector";
import { useTheme } from "../../contexts/ThemeContext";
import { useAgentStore } from "../../stores/agentStore";
import { useChatAnywhereInput } from "@agentscope-ai/chat";
import styles from "./index.module.less";
import { IconButton } from "@agentscope-ai/design";
import ChatActionGroup from "./components/ChatActionGroup";
import ChatHeaderTitle from "./components/ChatHeaderTitle";
import ChatSessionInitializer from "./components/ChatSessionInitializer";
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
      // Use a slightly longer delay for Safari on macOS, which fires keydown
      // after compositionend within the same event loop tick.
      setTimeout(() => {
        isComposingRef.current = false;
      }, 200);
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

  const getUserMessagesWithText = useCallback((): string[] => {
    if (!chatRef.current?.messages?.getMessages) return [];

    const allMessages = chatRef.current.messages.getMessages();
    if (!Array.isArray(allMessages)) return [];

    return allMessages
      .filter((msg) => msg.role === "user")
      .map((msg) => extractTextFromMessage(msg))
      .filter((text) => text.trim().length > 0);
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

  const isSuggestionPopupOpen = (textarea: HTMLTextAreaElement): boolean => {
    if (!textarea.value.startsWith("/")) return false;
    const doc = textarea.ownerDocument;
    const menuItems = Array.from(
      doc.querySelectorAll('[role="menuitemcheckbox"], [role="menuitem"]'),
    );
    return menuItems.some((item) =>
      (item.textContent || "").trim().startsWith("/"),
    );
  };

  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (!isChatActive()) return;

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
  const { t } = useTranslation();
  const navigate = useNavigate();
  const location = useLocation();
  const { isDark } = useTheme();
  const chatId = useMemo(() => {
    const match = location.pathname.match(/^\/chat\/(.+)$/);
    return match?.[1];
  }, [location.pathname]);
  const [showModelPrompt, setShowModelPrompt] = useState(false);
  const { selectedAgent } = useAgentStore();
  const [refreshKey, setRefreshKey] = useState(0);
  const runtimeLoadingBridgeRef = useRef<RuntimeLoadingBridgeApi | null>(null);
  const { message } = useAppMessage();

  const isChatActiveRef = useRef(false);
  isChatActiveRef.current =
    location.pathname === "/" || location.pathname.startsWith("/chat");

  const isChatActive = useCallback(() => isChatActiveRef.current, []);

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

  useMessageHistoryNavigation(chatRef, isChatActive, isComposingRef);
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
        command: "/approve",
        value: "approve",
        description: t("chat.commands.approve.description"),
      },
      {
        command: "/deny",
        value: "deny",
        description: t("chat.commands.deny.description"),
      },
      {
        command: "/mission",
        value: "mission",
        description: t("chat.commands.mission.description"),
      },
    ];

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
        avatar:
          "https://gw.alicdn.com/imgextra/i2/O1CN01pyXzjQ1EL1PuZMlSd_!!6000000000334-2-tps-288-288.png",
      },
      sender: {
        ...(i18nConfig as any)?.sender,
        beforeSubmit: handleBeforeSubmit,
        allowSpeech: true,
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
          const chatId =
            sessionApi.getRealIdForSession(data.session_id) ?? data.session_id;
          if (chatId) {
            chatApi.stopChat(chatId).catch((err) => {
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
    scheduleHistoryClear,
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
      <div className={styles.chatMessagesArea}>
        <AgentScopeRuntimeWebUI
          ref={chatRef}
          key={refreshKey}
          options={options}
        />
      </div>

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
