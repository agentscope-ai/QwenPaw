import {
  AgentScopeRuntimeWebUI,
  IAgentScopeRuntimeWebUIOptions,
  type IAgentScopeRuntimeWebUIMessage,
  type IAgentScopeRuntimeWebUIRef,
  Stream,
} from "@agentscope-ai/chat";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Button, Modal, Result, Tooltip, message } from "antd";
import { ExclamationCircleOutlined, SettingOutlined } from "@ant-design/icons";
import { SparkCopyLine } from "@agentscope-ai/icons";
import { useTranslation } from "react-i18next";
import { useLocation, useNavigate } from "react-router-dom";
import sessionApi from "./sessionApi";
import defaultConfig, { getDefaultConfig } from "./OptionsPanel/defaultConfig";
import { chatApi } from "../../api/modules/chat";
import { getApiToken, getApiUrl } from "../../api/config";
import { providerApi } from "../../api/modules/provider";
import type { ProviderInfo, ModelInfo } from "../../api/types";
import ModelSelector from "./ModelSelector";
import { useTheme } from "../../contexts/ThemeContext";
import { useAgentStore } from "../../stores/agentStore";
import AgentScopeRuntimeResponseBuilder from "@agentscope-ai/chat/lib/AgentScopeRuntimeWebUI/core/AgentScopeRuntime/Response/Builder.js";
import { AgentScopeRuntimeRunStatus } from "@agentscope-ai/chat/lib/AgentScopeRuntimeWebUI/core/AgentScopeRuntime/types.js";
import { useChatAnywhereInput } from "@agentscope-ai/chat/lib/AgentScopeRuntimeWebUI/core/Context/ChatAnywhereInputContext.js";
import "./index.module.less";
import { IconButton } from "@agentscope-ai/design";
import { SparkAttachmentLine } from "@agentscope-ai/icons";
import { trackNavigation } from "../../utils/navigationTelemetry";
import { shouldAutoSyncChatUrl } from "./navigationGuards";

type CopyableContent = {
  type?: string;
  text?: string;
  refusal?: string;
};

type CopyableMessage = {
  role?: string;
  content?: string | CopyableContent[];
};

type CopyableResponse = {
  output?: CopyableMessage[];
};

type RuntimeUiMessage = IAgentScopeRuntimeWebUIMessage & {
  msgStatus?: string;
  role?: string;
  cards?: Array<{
    code: string;
    data: unknown;
  }>;
  history?: boolean;
};

type StreamResponseData = {
  status?: string;
  output?: Array<{
    content?: unknown[];
  }>;
};

type RuntimeLoadingBridgeApi = {
  getLoading?: () => boolean | string;
  setLoading?: (loading: boolean | string) => void;
};

type SessionContext = {
  session_id?: string;
  user_id?: string;
  channel?: string;
};

type ChatInputContentPart = {
  type?: string;
  text?: string;
  image_url?: string;
  file_url?: string;
  audio_url?: string;
  video_url?: string;
  data?: string;
  [key: string]: unknown;
};

type ChatInputItem = {
  session?: SessionContext;
  content?: ChatInputContentPart[];
  [key: string]: unknown;
};

type BizParams = Record<string, unknown> & {
  reconnect?: boolean;
};

type CustomFetchData = {
  input?: ChatInputItem[];
  biz_params?: BizParams;
  signal?: AbortSignal;
  reconnect?: boolean;
  session_id?: string;
  user_id?: string;
  channel?: string;
};

type AttachmentTriggerProps = {
  disabled?: boolean;
};

type AttachmentUploadOptions = {
  file: File;
  onSuccess: (body: { url?: string; thumbUrl?: string }) => void;
  onError?: (error: Error) => void;
  onProgress?: (event: { percent?: number }) => void;
};

type SenderConfigShape = {
  sender?: Record<string, unknown>;
};

interface CustomWindow extends Window {
  currentSessionId?: string;
  currentUserId?: string;
  currentChannel?: string;
}

declare const window: CustomWindow;

function extractCopyableText(response: CopyableResponse): string {
  const collectText = (assistantOnly: boolean) => {
    const chunks = (response.output || []).flatMap((item: CopyableMessage) => {
      if (assistantOnly && item.role !== "assistant") return [];

      if (typeof item.content === "string") {
        return [item.content];
      }

      if (!Array.isArray(item.content)) {
        return [];
      }

      return item.content.flatMap((content: CopyableContent) => {
        if (content.type === "text" && typeof content.text === "string") {
          return [content.text];
        }

        if (content.type === "refusal" && typeof content.refusal === "string") {
          return [content.refusal];
        }

        return [];
      });
    });

    return chunks.filter(Boolean).join("\n\n").trim();
  };

  return collectText(true) || JSON.stringify(response);
}

async function copyText(text: string) {
  if (navigator.clipboard && window.isSecureContext) {
    await navigator.clipboard.writeText(text);
    return;
  }

  const textarea = document.createElement("textarea");
  textarea.value = text;
  textarea.setAttribute("readonly", "");
  textarea.style.position = "absolute";
  textarea.style.left = "-9999px";
  document.body.appendChild(textarea);

  let copied = false;
  try {
    textarea.focus();
    textarea.select();
    copied = document.execCommand("copy");
  } finally {
    document.body.removeChild(textarea);
  }

  if (!copied) {
    throw new Error("Failed to copy text");
  }
}

function buildModelError(): Response {
  return new Response(
    JSON.stringify({
      error: "Model not configured",
      message: "Please configure a model first",
    }),
    { status: 400, headers: { "Content-Type": "application/json" } },
  );
}

function cloneRuntimeMessages(
  messages: RuntimeUiMessage[],
): RuntimeUiMessage[] {
  return JSON.parse(JSON.stringify(messages)) as RuntimeUiMessage[];
}

function cloneValue<T>(value: T): T {
  return JSON.parse(JSON.stringify(value)) as T;
}

function isFinalResponseStatus(status?: string): boolean {
  return (
    status === AgentScopeRuntimeRunStatus.Completed ||
    status === AgentScopeRuntimeRunStatus.Failed ||
    status === AgentScopeRuntimeRunStatus.Canceled
  );
}

function hasRenderableOutput(response: StreamResponseData): boolean {
  if (response.status === AgentScopeRuntimeRunStatus.Failed) {
    return true;
  }

  return (
    response.output?.some((message) => (message.content?.length ?? 0) > 0) ??
    false
  );
}

function getResponseCardData(
  message?: RuntimeUiMessage,
): StreamResponseData | null {
  const responseCard = message?.cards?.find(
    (card) => card.code === "AgentScopeRuntimeResponseCard",
  );

  if (!responseCard?.data) {
    return null;
  }

  return cloneValue(responseCard.data as StreamResponseData);
}

function getStreamingAssistantMessageId(
  messages: RuntimeUiMessage[],
): string | null {
  return (
    [...messages]
      .reverse()
      .find(
        (message) =>
          message.role === "assistant" &&
          (message.msgStatus === "generating" ||
            (message.cards?.length ?? 0) === 0),
      )?.id ||
    [...messages].reverse().find((message) => message.role === "assistant")
      ?.id ||
    null
  );
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

function extractLatestUserText(input: ChatInputItem[] = []): string {
  const latest = input[input.length - 1];
  const content = latest?.content;
  if (!Array.isArray(content)) return "";
  return content
    .filter((item) => item?.type === "text" && typeof item?.text === "string")
    .map((item) => item.text as string)
    .join("\n")
    .trim();
}

function shouldSuggestPipelineOpportunity(text: string): boolean {
  if (!text) return false;
  if (text.length < 16) return false;
  const patterns = [
    /多步|流程|pipeline|管线/i,
    /批量|自动化|反复|复用/i,
    /抽取|对齐|校验|分析|报告/i,
  ];
  return patterns.some((pattern) => pattern.test(text));
}

function isPipelineDesignBootstrapText(text: string): boolean {
  if (!text) return false;
  return (
    text.includes("pipeline-create-guide") ||
    text.includes("我想创建一个新的 Pipeline") ||
    text.includes("I want to create a new Pipeline")
  );
}

function buildPipelineOpportunityInlineHint(): string {
  return [
    "",
    "[PipelineDesignHint]",
    "请把当前需求当作可复用多步骤流程，先用简短问题补齐关键槽位（目标、输入、步骤、质量指标、失败重试、产出物），",
    "然后给出一个可执行的 Pipeline Draft，并继续在当前会话中迭代，不要要求用户切换到新会话。",
  ].join("\n");
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
  const [, setChatStatus] = useState<"idle" | "running">("idle");
  const [, setReconnectStreaming] = useState(false);
  const runtimeLoadingBridgeRef = useRef<RuntimeLoadingBridgeApi | null>(null);

  const isComposingRef = useRef(false);
  const isChatActiveRef = useRef(false);

  // Multimodal capability state for the active model
  const [multimodalCaps, setMultimodalCaps] = useState<{
    supportsMultimodal: boolean;
    supportsImage: boolean;
    supportsVideo: boolean;
  }>({ supportsMultimodal: false, supportsImage: false, supportsVideo: false });
  isChatActiveRef.current =
    location.pathname === "/" || location.pathname.startsWith("/chat");

  const lastSessionIdRef = useRef<string | null>(null);
  const chatIdRef = useRef(chatId);
  const navigateRef = useRef(navigate);
  const chatRef = useRef<IAgentScopeRuntimeWebUIRef>(null);
  chatIdRef.current = chatId;
  navigateRef.current = navigate;

  useEffect(() => {
    sessionApi.setChatRef(chatRef);
    return () => sessionApi.setChatRef(null);
  }, []);

  useEffect(() => {
    const handleCompositionStart = () => {
      if (!isChatActiveRef.current) return;
      isComposingRef.current = true;
    };

    const handleCompositionEnd = () => {
      if (!isChatActiveRef.current) return;
      setTimeout(() => {
        isComposingRef.current = false;
      }, 150);
    };

    const handleKeyPress = (e: KeyboardEvent) => {
      if (!isChatActiveRef.current) return;
      const target = e.target as HTMLElement;
      if (target?.tagName === "TEXTAREA" && e.key === "Enter" && !e.shiftKey) {
        if (isComposingRef.current || e.isComposing) {
          e.stopPropagation();
          e.stopImmediatePropagation();
          return false;
        }
      }
    };

    document.addEventListener("compositionstart", handleCompositionStart, true);
    document.addEventListener("compositionend", handleCompositionEnd, true);
    document.addEventListener("keypress", handleKeyPress, true);

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
      document.removeEventListener("keypress", handleKeyPress, true);
    };
  }, []);

  useEffect(() => {
    sessionApi.onSessionIdResolved = (tempId, realId) => {
      if (!isChatActiveRef.current) return;
      if (chatIdRef.current === tempId) {
        lastSessionIdRef.current = realId;
        trackNavigation({
          source: "chat.onSessionIdResolved",
          from: `/chat/${tempId}`,
          to: `/chat/${realId}`,
          reason: "resolve-temp-session-id",
        });
        navigateRef.current(`/chat/${realId}`, { replace: true });
      }
    };

    sessionApi.onSessionRemoved = (removedId) => {
      if (!isChatActiveRef.current) return;
      if (chatIdRef.current === removedId) {
        lastSessionIdRef.current = null;
        trackNavigation({
          source: "chat.onSessionRemoved",
          from: `/chat/${removedId}`,
          to: "/chat",
          reason: "removed-current-session",
        });
        navigateRef.current("/chat", { replace: true });
      }
    };

    return () => {
      sessionApi.onSessionIdResolved = null;
      sessionApi.onSessionRemoved = null;
    };
  }, []);

  // Refresh chat when selectedAgent changes
  const prevSelectedAgentRef = useRef(selectedAgent);
  useEffect(() => {
    // Only refresh if selectedAgent actually changed (not initial mount)
    if (
      prevSelectedAgentRef.current !== selectedAgent &&
      prevSelectedAgentRef.current !== undefined
    ) {
      // Force re-render by updating refresh key
      setRefreshKey((prev) => prev + 1);
    }
    prevSelectedAgentRef.current = selectedAgent;
  }, [selectedAgent]);

  useEffect(() => {
    if (!chatId) {
      return;
    }

    let cancelled = false;
    let attempts = 0;
    const maxAttempts = 24;
    const intervalMs = 1500;

    const pollSessionHydration = async () => {
      if (cancelled) {
        return;
      }

      attempts += 1;

      try {
        const session = await sessionApi.getSession(chatId);
        const messages = (session.messages as RuntimeUiMessage[] | undefined) || [];
        const hasAssistantMessage = messages.some(
          (message) => message.role === "assistant",
        );
        const isIdle =
          (session as { status?: "idle" | "running" }).status === "idle";

        if (hasAssistantMessage || isIdle) {
          setRefreshKey((prev) => prev + 1);
          return;
        }
      } catch {
        // Ignore transient polling failures and continue retrying.
      }

      if (!cancelled && attempts < maxAttempts) {
        setTimeout(() => {
          void pollSessionHydration();
        }, intervalMs);
      }
    };

    void pollSessionHydration();

    return () => {
      cancelled = true;
    };
  }, [chatId]);

  // Fetch multimodal capabilities for the active model
  const fetchMultimodalCaps = useCallback(async () => {
    try {
      const [providers, activeModels] = await Promise.all([
        providerApi.listProviders(),
        providerApi.getActiveModels(),
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
  }, []);

  // Fetch caps on mount and whenever refreshKey changes (model switch triggers refreshKey++)
  useEffect(() => {
    fetchMultimodalCaps();
  }, [fetchMultimodalCaps, refreshKey]);

  // Also poll caps when navigating back to chat (model may have been changed on settings page)
  useEffect(() => {
    if (isChatActiveRef.current) {
      fetchMultimodalCaps();
    }
  }, [location.pathname, fetchMultimodalCaps]);

  // Listen for model-switched event from ModelSelector
  useEffect(() => {
    const handler = () => {
      fetchMultimodalCaps();
    };
    window.addEventListener("model-switched", handler);
    return () => window.removeEventListener("model-switched", handler);
  }, [fetchMultimodalCaps]);

  const getSessionListWrapped = useCallback(async () => {
    const sessions = await sessionApi.getSessionList();
    const currentChatId = chatIdRef.current;

    if (currentChatId) {
      const idx = sessions.findIndex((s) => s.id === currentChatId);
      if (idx > 0) {
        return [
          sessions[idx],
          ...sessions.slice(0, idx),
          ...sessions.slice(idx + 1),
        ];
      }
    }

    return sessions;
  }, []);

  const getSessionWrapped = useCallback(async (sessionId: string) => {
    const currentChatId = chatIdRef.current;
    const canAutoSyncUrl = shouldAutoSyncChatUrl(currentChatId);

    if (
      isChatActiveRef.current &&
      canAutoSyncUrl &&
      sessionId &&
      sessionId !== lastSessionIdRef.current &&
      sessionId !== currentChatId
    ) {
      const urlId = sessionApi.getRealIdForSession(sessionId) ?? sessionId;
      lastSessionIdRef.current = urlId;
      trackNavigation({
        source: "chat.getSessionWrapped",
        from: currentChatId ? `/chat/${currentChatId}` : "/chat",
        to: `/chat/${urlId}`,
        reason: "sync-session-selection",
        meta: {
          requestedSessionId: sessionId,
        },
      });
      navigateRef.current(`/chat/${urlId}`, { replace: true });
    }

    return sessionApi.getSession(sessionId);
  }, []);

  const createSessionWrapped = useCallback(
    async (session: Partial<{ id: string }>) => {
    const result = await sessionApi.createSession(session);
    const newSessionId = session?.id || result[0]?.id;
    if (isChatActiveRef.current && newSessionId) {
      lastSessionIdRef.current = newSessionId;
      trackNavigation({
        source: "chat.createSessionWrapped",
        from: chatIdRef.current ? `/chat/${chatIdRef.current}` : "/chat",
        to: `/chat/${newSessionId}`,
        reason: "create-new-session",
      });
      navigateRef.current(`/chat/${newSessionId}`, { replace: true });
    }
    return result;
    },
    [],
  );

  const wrappedSessionApi = useMemo(
    () => ({
      getSessionList: getSessionListWrapped,
      getSession: getSessionWrapped,
      createSession: createSessionWrapped,
      updateSession: sessionApi.updateSession.bind(sessionApi),
      removeSession: sessionApi.removeSession.bind(sessionApi),
    }),
    [createSessionWrapped, getSessionListWrapped, getSessionWrapped],
  );

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

  const persistSessionMessages = useCallback(
    async (sessionId: string, messages: RuntimeUiMessage[]) => {
      if (!sessionId) return;
      await sessionApi.updateSession({
        id: sessionId,
        messages: cloneRuntimeMessages(messages),
      });
    },
    [],
  );

  const releaseStaleLoadingState = useCallback((sessionId: string) => {
    const activeChatId = chatIdRef.current;
    const realSessionId = sessionApi.getRealIdForSession(sessionId);
    const isBackgroundSession =
      activeChatId !== sessionId && activeChatId !== realSessionId;

    if (!isBackgroundSession) {
      return;
    }

    if (sessionApi.hasLiveMessagesForSession(activeChatId)) {
      return;
    }

    runtimeLoadingBridgeRef.current?.setLoading?.(false);
  }, []);

  const persistStreamSession = useCallback(
    (sessionId: string, readableStream: ReadableStream<Uint8Array>) => {
      const initialMessages = cloneRuntimeMessages(
        (chatRef.current?.messages.getMessages() as RuntimeUiMessage[]) || [],
      );
      const assistantMessageId =
        getStreamingAssistantMessageId(initialMessages) ||
        `stream-${sessionId}`;
      const responseBuilder = new AgentScopeRuntimeResponseBuilder({
        id: "",
        status: AgentScopeRuntimeRunStatus.Created,
        created_at: 0,
      });

      void (async () => {
        let cachedMessages = initialMessages;
        let hasStreamActivity = false;
        let didReleaseLoading = false;

        try {
          for await (const chunk of Stream({ readableStream })) {
            let chunkData: unknown;
            try {
              chunkData = JSON.parse(chunk.data);
            } catch {
              continue;
            }

            hasStreamActivity = true;
            const responseData = responseBuilder.handle(
              chunkData as never,
            ) as StreamResponseData;
            const isFinalChunk = isFinalResponseStatus(responseData.status);
            const existingAssistantMessage = cachedMessages.find(
              (message) => message.id === assistantMessageId,
            );
            const previousResponseData = getResponseCardData(
              existingAssistantMessage,
            );

            let nextResponseData: StreamResponseData | null = null;
            if (hasRenderableOutput(responseData)) {
              nextResponseData = cloneValue(responseData);
            } else if (isFinalChunk && previousResponseData) {
              nextResponseData = {
                ...previousResponseData,
                status: responseData.status ?? previousResponseData.status,
              };
            }

            if (nextResponseData) {
              const assistantMessage: RuntimeUiMessage = {
                ...(existingAssistantMessage || {
                  id: assistantMessageId,
                  role: "assistant",
                }),
                id: assistantMessageId,
                role: "assistant",
                cards: [
                  {
                    code: "AgentScopeRuntimeResponseCard",
                    data: nextResponseData,
                  },
                ],
                msgStatus: isFinalChunk ? "finished" : "generating",
              };

              const assistantIndex = cachedMessages.findIndex(
                (message) => message.id === assistantMessageId,
              );
              cachedMessages =
                assistantIndex >= 0
                  ? [
                      ...cachedMessages.slice(0, assistantIndex),
                      assistantMessage,
                      ...cachedMessages.slice(assistantIndex + 1),
                    ]
                  : [...cachedMessages, assistantMessage];

              await persistSessionMessages(sessionId, cachedMessages);
            }

            if (!isFinalChunk) {
              continue;
            }

            releaseStaleLoadingState(sessionId);
            didReleaseLoading = true;
          }
        } catch (error) {
          console.error("Failed to persist background chat stream:", error);
        } finally {
          if (hasStreamActivity && !didReleaseLoading) {
            releaseStaleLoadingState(sessionId);
          }
        }
      })();
    },
    [persistSessionMessages, releaseStaleLoadingState],
  );

  const customFetch = useCallback(
    async (data: CustomFetchData): Promise<Response> => {
      const headers: Record<string, string> = {
        "Content-Type": "application/json",
      };
      const token = getApiToken();
      if (token) headers.Authorization = `Bearer ${token}`;
      try {
        const agentStorage = localStorage.getItem("copaw-agent-storage");
        if (agentStorage) {
          const parsed = JSON.parse(agentStorage);
          const selectedAgent = parsed?.state?.selectedAgent;
          if (selectedAgent) {
            headers["X-Agent-Id"] = selectedAgent;
          }
        }
      } catch (error) {
        console.warn("Failed to get selected agent from storage:", error);
      }

      const shouldReconnect =
        data.reconnect || data.biz_params?.reconnect === true;
      const reconnectSessionId =
        data.session_id ?? window.currentSessionId ?? "";
      if (shouldReconnect && reconnectSessionId) {
        setReconnectStreaming(true);
        const res = await fetch(getApiUrl("/console/chat"), {
          method: "POST",
          headers,
          body: JSON.stringify({
            reconnect: true,
            session_id: reconnectSessionId,
            user_id: data.user_id ?? window.currentUserId ?? "default",
            channel: data.channel ?? window.currentChannel ?? "console",
          }),
        });

        // Reconnect has a small race window: status endpoint can still read
        // "running" while the stream task has just finished.
        // Backend then returns 404 "No running chat for this session".
        // Treat it as a benign idle transition instead of surfacing an error.
        if (!res.ok || !res.body) {
          setChatStatus("idle");
          setReconnectStreaming(false);

          if (res.status === 404) {
            try {
              const payload = await res.clone().json();
              if (payload?.detail === "No running chat for this session") {
                return new Response(
                  JSON.stringify({
                    status: AgentScopeRuntimeRunStatus.Completed,
                    output: [],
                  }),
                  {
                    status: 200,
                    headers: { "Content-Type": "application/json" },
                  },
                );
              }
            } catch {
              // Ignore parse errors and keep original response below.
            }
          }

          return res;
        }
        const onStreamEnd = () => {
          setChatStatus("idle");
          setReconnectStreaming(false);
        };
        const stream = res.body;
        const transformed = new ReadableStream({
          start(controller) {
            const reader = stream.getReader();
            function pump() {
              reader.read().then(({ done, value }) => {
                if (done) {
                  controller.close();
                  onStreamEnd();
                  return;
                }
                controller.enqueue(value);
                return pump();
              });
            }
            pump();
          },
        });
        return new Response(transformed, {
          headers: res.headers,
          status: res.status,
        });
      }

      try {
        const activeModels = await providerApi.getActiveModels();
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
      const latestUserText = extractLatestUserText(input);
      const bootstrapText = isPipelineDesignBootstrapText(latestUserText);
      const shouldInlinePipelineGuide =
        !bootstrapText && shouldSuggestPipelineOpportunity(latestUserText);

      if (shouldInlinePipelineGuide) {
        const now = Date.now();
        const cooldownKey = "copaw.pipeline.opportunity.lastAt";
        const lastAt = Number(localStorage.getItem(cooldownKey) || "0");
        if (now - lastAt > 30 * 60 * 1000) {
          localStorage.setItem(cooldownKey, String(now));
        }
      }

      const session = input[input.length - 1]?.session || {};
      const lastInput = input.slice(-1);
      const lastMsg = lastInput[0];
      const rewrittenInput =
        lastMsg?.content && Array.isArray(lastMsg.content)
          ? [
              {
                ...lastMsg,
                content: [
                  ...lastMsg.content.map((part: ChatInputContentPart) => {
                    const p = { ...part };
                    const toStoredName = (v: string) => {
                      const m1 = v.match(/\/console\/files\/[^/]+\/(.+)$/);
                      if (m1) return m1[1];
                      const m2 = v.match(/^[^/]+\/(.+)$/);
                      if (m2) return m2[1];
                      return v;
                    };
                    if (p.type === "image" && typeof p.image_url === "string")
                      p.image_url = toStoredName(p.image_url);
                    if (p.type === "file" && typeof p.file_url === "string")
                      p.file_url = toStoredName(p.file_url);
                    if (p.type === "audio" && typeof p.audio_url === "string")
                      p["data"] = toStoredName(p.audio_url);
                    if (p.type === "video" && typeof p.video_url === "string")
                      p.video_url = toStoredName(p.video_url);

                    return p;
                  }),
                  ...(shouldInlinePipelineGuide
                    ? [
                        {
                          type: "text",
                          text: buildPipelineOpportunityInlineHint(),
                        },
                      ]
                    : []),
                ],
              },
            ]
          : lastInput;

      const requestBody = {
        input: rewrittenInput,
        session_id: window.currentSessionId || session?.session_id || "",
        user_id: window.currentUserId || session?.user_id || "default",
        channel: window.currentChannel || session?.channel || "console",
        stream: true,
        ...biz_params,
      };

      const backendChatId =
        sessionApi.getRealIdForSession(requestBody.session_id) ??
        chatIdRef.current ??
        requestBody.session_id;
      if (backendChatId) {
        const userText = rewrittenInput
          .filter((message) => message.role === "user")
          .map((message) => {
            if (typeof message.content === "string") return message.content;
            if (!Array.isArray(message.content)) return "";
            return message.content
              .filter((part) => part.type === "text")
              .map((part) => (typeof part.text === "string" ? part.text : ""))
              .join("\n");
          })
          .join("\n")
          .trim();
        if (userText) {
          if (requestBody.session_id) {
            sessionApi.setLastUserMessage(requestBody.session_id, userText);
          }
          sessionApi.setLastUserMessage(backendChatId, userText);
        }
      }

      const response = await fetch(getApiUrl("/console/chat"), {
        method: "POST",
        headers,
        body: JSON.stringify(requestBody),
        signal: data.signal,
      });

      if (!response.ok || !response.body || !requestBody.session_id) {
        return response;
      }

      const [uiStream, cacheStream] = response.body.tee();
      persistStreamSession(requestBody.session_id, cacheStream);

      return new Response(uiStream, {
        status: response.status,
        statusText: response.statusText,
        headers: response.headers,
      });
    },
    [persistStreamSession, setChatStatus, setReconnectStreaming],
  );

  const options = useMemo(() => {
    const i18nConfig = getDefaultConfig(t);
    const senderConfig = (i18nConfig as SenderConfigShape).sender || {};

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
            <RuntimeLoadingBridge bridgeRef={runtimeLoadingBridgeRef} />
            <ModelSelector />
          </>
        ),
      },
      welcome: {
        ...i18nConfig.welcome,
        avatar: isDark
          ? `${import.meta.env.BASE_URL}copaw-dark.png`
          : `${import.meta.env.BASE_URL}copaw-symbol.svg`,
      },
      sender: {
        ...senderConfig,
        beforeSubmit: handleBeforeSubmit,
        allowSpeech: true,
        attachments: {
          trigger: function (props: AttachmentTriggerProps) {
            const tooltipKey = multimodalCaps.supportsMultimodal
              ? multimodalCaps.supportsImage && !multimodalCaps.supportsVideo
                ? "chat.attachments.tooltipImageOnly"
                : "chat.attachments.tooltip"
              : "chat.attachments.tooltipNoMultimodal";
            return (
              <Tooltip title={t(tooltipKey)}>
                <IconButton
                  disabled={props?.disabled}
                  icon={<SparkAttachmentLine />}
                  bordered={false}
                />
              </Tooltip>
            );
          },
          accept: "*/*",
          customRequest: async (options: AttachmentUploadOptions) => {
            try {
              // Warn when model has no multimodal support
              if (!multimodalCaps.supportsMultimodal) {
                message.warning(t("chat.attachments.multimodalWarning"));
              } else if (
                multimodalCaps.supportsImage &&
                !multimodalCaps.supportsVideo &&
                !options.file.type.startsWith("image/")
              ) {
                // Warn (not block) when only image is supported
                message.warning(t("chat.attachments.imageOnlyWarning"));
              }

              // Check file size limit (10MB)
              const file = options.file as File;
              const isLt10M = file.size / 1024 / 1024 < 10;
              if (!isLt10M) {
                message.error(t("chat.attachments.fileSizeLimit"));
                return options.onError?.(new Error("File size exceeds 10MB"));
              }

              options.onProgress?.({ percent: 0 });
              const res = await chatApi.uploadFile(options.file);
              options.onProgress?.({ percent: 100 });
              options.onSuccess({ url: chatApi.fileUrl(res.url) });
            } catch (e) {
              options.onError?.(e instanceof Error ? e : new Error(String(e)));
            }
          },
        },
      },
      session: { multiple: true, api: wrappedSessionApi },
      api: {
        ...defaultConfig.api,
        fetch: customFetch,
        cancel(data: { session_id: string }) {
          const chatIdForStop = data?.session_id
            ? sessionApi.getRealIdForSession(data.session_id) ?? data.session_id
            : "";
          if (chatIdForStop) {
            chatApi.stopConsoleChat(chatIdForStop).then(
              () => setChatStatus("idle"),
              (err) => {
                console.error("stopConsoleChat failed:", err);
              },
            );
          }
        },
      },
      actions: {
        list: [
          {
            key: "copy",
            icon: (
              <span key="copy-action-icon" title={t("common.copy")}>
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
    wrappedSessionApi,
    customFetch,
    copyResponse,
    t,
    isDark,
    multimodalCaps,
    setChatStatus,
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
      <div style={{ flex: 1, minHeight: 0 }}>
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
                trackNavigation({
                  source: "chat.modelPrompt",
                  from: location.pathname,
                  to: "/models",
                  reason: "configure-model-from-chat",
                });
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
