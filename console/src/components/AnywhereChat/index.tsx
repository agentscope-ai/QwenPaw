import {
  AgentScopeRuntimeWebUI,
  Stream,
  type IAgentScopeRuntimeWebUIOptions,
  type IAgentScopeRuntimeWebUIRef,
} from "@agentscope-ai/chat";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Button, Popover, message } from "antd";
import { DashboardOutlined } from "@ant-design/icons";
import { useTranslation } from "react-i18next";
import defaultConfig, { getDefaultConfig } from "../../pages/Chat/OptionsPanel/defaultConfig";
import ModelSelector from "../../pages/Chat/ModelSelector";
import sessionApi from "../../pages/Chat/sessionApi";
import { chatApi } from "../../api/modules/chat";
import { providerApi } from "../../api/modules/provider";
import { agentApi } from "../../api/modules/agent";
import { getApiToken, getApiUrl } from "../../api/config";
import { useTheme } from "../../contexts/ThemeContext";
import { useAgentStore } from "../../stores/agentStore";
import AgentScopeRuntimeResponseBuilder from "@agentscope-ai/chat/lib/AgentScopeRuntimeWebUI/core/AgentScopeRuntime/Response/Builder.js";
import { AgentScopeRuntimeRunStatus } from "@agentscope-ai/chat/lib/AgentScopeRuntimeWebUI/core/AgentScopeRuntime/types.js";
import type {
  ActiveModelsInfo,
  AgentsRunningConfig,
  ChatHistory,
  Message,
  ChatRuntimeStatus,
  ProviderInfo,
} from "../../api/types";
import {
  deriveRuntimeStatusSnapshot,
  formatTokenCount,
  mergeRuntimeStatusSnapshot,
} from "../../utils/chatRuntimeStatus";

type SessionContext = {
  session_id?: string;
  user_id?: string;
  channel?: string;
};

type ChatInputItem = {
  session?: SessionContext;
  content?: unknown[];
  role?: string;
  [key: string]: unknown;
};

type SenderConfigShape = {
  sender?: Record<string, unknown>;
};

type WelcomePrompt = {
  value: string;
};

type WelcomeConfigShape = {
  greeting?: string;
  description?: string;
  prompts?: WelcomePrompt[];
};

const RUNTIME_STATUS_RETRY_DELAY_MS = 1500;
const RUNTIME_STATUS_MAX_RETRIES = 2;

interface AnywhereChatProps {
  sessionId: string;
  hostClassName?: string;
  inputPlaceholder?: string;
  welcomeGreeting?: string;
  welcomeDescription?: string;
  welcomePrompts?: string[];
  onNewChat?: () => void;
  onAssistantTurnCompleted?: (payload: {
    text: string;
    response: Record<string, unknown> | null;
  }) => void;
  autoAttachRequest?: {
    id: string;
    mode?: "submit" | "draft";
    fileName?: string;
    content?: string;
    mimeType?: string;
    files?: Array<{
      fileName: string;
      content: string;
      mimeType?: string;
    }>;
    note?: string;
  } | null;
  onAutoAttachHandled?: (payload: {
    id: string;
    ok: boolean;
    error?: string;
  }) => void;
}

type StreamResponseData = {
  status?: string;
  output?: Array<{
    role?: string;
    content?: Array<{ type?: string; text?: string; refusal?: string }>;
  }>;
};

function extractUserTextFromInput(input?: ChatInputItem): string {
  if (!input || !Array.isArray(input.content)) return "";

  return input.content
    .flatMap((part) => {
      if (!part || typeof part !== "object") return [];
      const typed = part as { type?: string; text?: string };
      if (typed.type === "text" && typeof typed.text === "string") {
        return [typed.text.trim()];
      }
      return [];
    })
    .filter(Boolean)
    .join("\n")
    .trim();
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

function extractAssistantText(response: StreamResponseData | null): string {
  if (!response || !Array.isArray(response.output)) return "";

  return response.output
    .flatMap((message) => {
      if (!Array.isArray(message.content)) return [];
      return message.content.flatMap((part) => {
        if (part.type === "text" && typeof part.text === "string") {
          return [part.text];
        }
        if (part.type === "refusal" && typeof part.refusal === "string") {
          return [part.refusal];
        }
        return [];
      });
    })
    .filter(Boolean)
    .join("\n\n")
    .trim();
}

export default function AnywhereChat({
  sessionId,
  hostClassName = "pipeline-anywhere-chat-host",
  inputPlaceholder,
  welcomeGreeting,
  welcomeDescription,
  welcomePrompts,
  onNewChat,
  onAssistantTurnCompleted,
  autoAttachRequest,
  onAutoAttachHandled,
}: AnywhereChatProps) {
  const { t } = useTranslation();
  const { isDark } = useTheme();
  const { selectedAgent } = useAgentStore();
  const [refreshKey, setRefreshKey] = useState(0);
  const [providerList, setProviderList] = useState<ProviderInfo[]>([]);
  const [activeModels, setActiveModels] = useState<ActiveModelsInfo | null>(null);
  const [runningConfig, setRunningConfig] = useState<AgentsRunningConfig | null>(null);
  const [chatHistory, setChatHistory] = useState<ChatHistory | null>(null);
  const [runtimeStatusFromApi, setRuntimeStatusFromApi] = useState<ChatRuntimeStatus | null>(null);
  const [runtimeStatusOpen, setRuntimeStatusOpen] = useState(false);
  const [isChatStreaming, setIsChatStreaming] = useState(false);
  const [lastRuntimeStatusUpdatedAt, setLastRuntimeStatusUpdatedAt] = useState<number | null>(null);
  const [runtimeStatusError, setRuntimeStatusError] = useState<string | null>(null);
  const [transientMessages, setTransientMessages] = useState<Message[]>([]);
  const chatRef = useRef<IAgentScopeRuntimeWebUIRef>(null);
  const runtimeStatusRequestInFlight = useRef(false);
  const sessionIdRef = useRef(sessionId);
  const runtimeStatusRetryTimerRef = useRef<number | null>(null);
  const runtimeStatusRetryCountRef = useRef(0);
  const handledAutoAttachIdRef = useRef("");

  const updateTransientMessages = useCallback((messages: Message[]) => {
    setTransientMessages(messages);
    setLastRuntimeStatusUpdatedAt(Date.now());
  }, []);

  const loadRuntimeInputs = useCallback(async () => {
    try {
      const [providers, activeModelConfig, runtimeConfig] = await Promise.all([
        providerApi.listProviders(),
        providerApi.getActiveModels(),
        agentApi.getAgentRunningConfig(),
      ]);
      setProviderList(Array.isArray(providers) ? providers : []);
      setActiveModels(activeModelConfig ?? null);
      setRunningConfig(runtimeConfig ?? null);
    } catch (error) {
      console.warn("AnywhereChat: failed to load runtime inputs", error);
      setProviderList([]);
      setActiveModels(null);
      setRunningConfig(null);
    }
  }, []);

  const loadChatHistory = useCallback(async () => {
    if (!sessionId) {
      setChatHistory(null);
      return;
    }
    const requestedSessionId = sessionId;
    try {
      const history = await chatApi.getChat(requestedSessionId, { limit: 100 });
      if (sessionIdRef.current !== requestedSessionId) {
        return;
      }
      setChatHistory(history);
      setRuntimeStatusError(null);
      setLastRuntimeStatusUpdatedAt(Date.now());
    } catch (error) {
      console.warn("AnywhereChat: failed to load chat history", error);
      if (sessionIdRef.current !== requestedSessionId) {
        return;
      }
      setRuntimeStatusError(
        error instanceof Error ? error.message : t("chat.runtimeStatusUnknownError", "未知错误"),
      );
      setChatHistory(null);
    }
  }, [sessionId, t]);

  const clearRuntimeStatusRetry = useCallback(() => {
    if (runtimeStatusRetryTimerRef.current !== null) {
      window.clearTimeout(runtimeStatusRetryTimerRef.current);
      runtimeStatusRetryTimerRef.current = null;
    }
  }, []);

  const loadRuntimeStatus = useCallback(async (): Promise<ChatRuntimeStatus | null> => {
    if (!sessionId) {
      setRuntimeStatusFromApi(null);
      return null;
    }
    if (runtimeStatusRequestInFlight.current) {
      return null;
    }
    const requestedSessionId = sessionId;
    runtimeStatusRequestInFlight.current = true;
    try {
      const snapshot = await chatApi.getRuntimeStatus(requestedSessionId);
      if (sessionIdRef.current !== requestedSessionId) {
        return null;
      }
      setRuntimeStatusFromApi(snapshot ?? null);
      setRuntimeStatusError(null);
      setLastRuntimeStatusUpdatedAt(Date.now());
      return snapshot ?? null;
    } catch (error) {
      console.warn("AnywhereChat: failed to load runtime status", error);
      if (sessionIdRef.current !== requestedSessionId) {
        return null;
      }
      setRuntimeStatusError(
        error instanceof Error ? error.message : t("chat.runtimeStatusUnknownError", "未知错误"),
      );
      setRuntimeStatusFromApi(null);
      return null;
    } finally {
      runtimeStatusRequestInFlight.current = false;
    }
  }, [sessionId, t]);

  const loadRuntimeStatusWithRetry = useCallback(async () => {
    clearRuntimeStatusRetry();
    const snapshot = await loadRuntimeStatus();
    const shouldRetry =
      runtimeStatusOpen &&
      sessionIdRef.current === sessionId &&
      !isChatStreaming &&
      !!snapshot &&
      snapshot.snapshot_source === "empty_baseline" &&
      runtimeStatusRetryCountRef.current < RUNTIME_STATUS_MAX_RETRIES;

    if (!shouldRetry) {
      return snapshot;
    }

    runtimeStatusRetryCountRef.current += 1;
    runtimeStatusRetryTimerRef.current = window.setTimeout(() => {
      void loadRuntimeStatusWithRetry();
    }, RUNTIME_STATUS_RETRY_DELAY_MS);
    return snapshot;
  }, [clearRuntimeStatusRetry, isChatStreaming, loadRuntimeStatus, runtimeStatusOpen, sessionId]);

  useEffect(() => {
    sessionIdRef.current = sessionId;
    clearRuntimeStatusRetry();
    runtimeStatusRetryCountRef.current = 0;
    setRefreshKey((prev) => prev + 1);
    setChatHistory(null);
    setRuntimeStatusFromApi(null);
    setRuntimeStatusError(null);
    setTransientMessages([]);

  }, [clearRuntimeStatusRetry, sessionId]);

  useEffect(() => {
    if (!autoAttachRequest?.id) {
      return;
    }
    if (handledAutoAttachIdRef.current === autoAttachRequest.id) {
      return;
    }
    handledAutoAttachIdRef.current = autoAttachRequest.id;

    const attach = async () => {
      try {
        const mode = autoAttachRequest.mode || "submit";
        if (mode === "draft") {
          const root = document.querySelector(`.${hostClassName}`) as HTMLElement | null;
          const draftText =
            autoAttachRequest.note ||
            "I attached files as context. Please review them and wait for my next instruction.";

          const textArea = root?.querySelector("textarea") as HTMLTextAreaElement | null;
          if (textArea) {
            const prototype = Object.getPrototypeOf(textArea) as {
              value?: PropertyDescriptor;
            };
            const descriptor = Object.getOwnPropertyDescriptor(prototype, "value");
            if (descriptor?.set) {
              descriptor.set.call(textArea, draftText);
            } else {
              textArea.value = draftText;
            }
            textArea.dispatchEvent(new Event("input", { bubbles: true }));
            textArea.focus();

            onAutoAttachHandled?.({
              id: autoAttachRequest.id,
              ok: true,
            });
            return;
          }

          throw new Error("chat_input_not_found");
        }

        const sourceFiles = Array.isArray(autoAttachRequest.files) && autoAttachRequest.files.length > 0
          ? autoAttachRequest.files
          : autoAttachRequest.fileName && autoAttachRequest.content
            ? [{
                fileName: autoAttachRequest.fileName,
                content: autoAttachRequest.content,
                mimeType: autoAttachRequest.mimeType,
              }]
            : [];

        if (sourceFiles.length === 0) {
          throw new Error("auto_attach_no_files");
        }

        const uploadedFiles = await Promise.all(
          sourceFiles.map(async (source, index) => {
            const file = new File([source.content], source.fileName, {
              type: source.mimeType || "text/plain",
            });
            const uploaded = await chatApi.uploadFile(file);
            const uploadUrl = chatApi.filePreviewUrl(uploaded.url);

            return {
              uid: `${autoAttachRequest.id}-${index}`,
              name: source.fileName,
              status: "done" as const,
              type: source.mimeType || "text/plain",
              size: file.size,
              file_id: uploaded.stored_name || uploaded.url,
              response: {
                url: uploadUrl,
              },
            };
          }),
        );

        if (!chatRef.current) {
          throw new Error("chat_input_not_ready");
        }

        chatRef.current.input.submit({
          query:
            autoAttachRequest.note ||
            `Please use the attached files as the current context and infer the likely task intent.`,
          fileList: uploadedFiles,
        });

        onAutoAttachHandled?.({
          id: autoAttachRequest.id,
          ok: true,
        });
      } catch (error) {
        onAutoAttachHandled?.({
          id: autoAttachRequest.id,
          ok: false,
          error: error instanceof Error ? error.message : String(error),
        });
      }
    };

    void attach();
  }, [autoAttachRequest, hostClassName, onAutoAttachHandled]);

  useEffect(() => {
    void loadRuntimeInputs();

    const handleModelSwitched = () => {
      void loadRuntimeInputs();
    };

    window.addEventListener("model-switched", handleModelSwitched);
    return () => {
      window.removeEventListener("model-switched", handleModelSwitched);
    };
  }, [loadRuntimeInputs]);

  useEffect(() => {
    if (!runtimeStatusOpen) {
      clearRuntimeStatusRetry();
      runtimeStatusRetryCountRef.current = 0;
      return;
    }

    runtimeStatusRetryCountRef.current = 0;
    void loadRuntimeStatusWithRetry();
    void loadChatHistory();

    return () => {
      clearRuntimeStatusRetry();
    };
  }, [
    clearRuntimeStatusRetry,
    loadChatHistory,
    loadRuntimeStatusWithRetry,
    runtimeStatusOpen,
    sessionId,
  ]);

  const transientHistory = useMemo<ChatHistory | null>(
    () =>
      transientMessages.length > 0
        ? {
            messages: transientMessages,
            status: isChatStreaming ? "running" : chatHistory?.status,
            total: transientMessages.length,
          }
        : null,
    [chatHistory?.status, isChatStreaming, transientMessages],
  );

  const fallbackHistory = useMemo<ChatHistory | null>(() => {
    if (!transientMessages.length) {
      return chatHistory;
    }
    return {
      ...chatHistory,
      messages: [...(chatHistory?.messages || []), ...transientMessages],
      total: (chatHistory?.messages?.length || 0) + transientMessages.length,
    };
  }, [chatHistory, transientMessages]);

  const runtimeStatus = useMemo(() => {
    if (runtimeStatusFromApi) {
      return mergeRuntimeStatusSnapshot(runtimeStatusFromApi, {
        providers: providerList,
        activeModels,
        runningConfig,
        chatHistory: transientHistory,
      }, {
        expectedAgentId: selectedAgent || null,
        expectedChatId: sessionId || null,
        expectedSnapshotStage: "pre_model_call",
      });
    }

    return deriveRuntimeStatusSnapshot({
      providers: providerList,
      activeModels,
      runningConfig,
      chatHistory: fallbackHistory,
    });
  }, [
    activeModels,
    fallbackHistory,
    providerList,
    runningConfig,
    runtimeStatusFromApi,
    selectedAgent,
    sessionId,
    transientHistory,
  ]);

  const runtimeStatusMeta = runtimeStatusFromApi || runtimeStatus;

  const singleSessionApi = useMemo(
    () => ({
      getSessionList: async () => {
        if (!sessionId) return [];
        try {
          const sessions = await sessionApi.getSessionList();
          const matched = sessions.find((item) => {
            const ext = item as { realId?: string; sessionId?: string };
            return (
              item.id === sessionId ||
              ext.realId === sessionId ||
              ext.sessionId === sessionId
            );
          });
          if (matched) {
            return [matched];
          }

          const session = await sessionApi.getSession(sessionId);
          return [session];
        } catch {
          return [];
        }
      },
      getSession: async () => {
        if (!sessionId) {
          throw new Error("session id missing");
        }
        return sessionApi.getSession(sessionId);
      },
      createSession: async (session: Partial<{ id: string }>) => {
        if (sessionId) {
          try {
            const current = await sessionApi.getSession(sessionId);
            return [current];
          } catch {
            return [];
          }
        }
        return sessionApi.createSession(session);
      },
      updateSession: sessionApi.updateSession.bind(sessionApi),
      removeSession: sessionApi.removeSession.bind(sessionApi),
    }),
    [sessionId],
  );

  const customFetch = useCallback(
    async (data: {
      input?: ChatInputItem[];
      signal?: AbortSignal;
      session_id?: string;
      user_id?: string;
      channel?: string;
    }) => {
      if (!sessionId) {
        return new Response(JSON.stringify({ error: "session id missing" }), {
          status: 400,
          headers: { "Content-Type": "application/json" },
        });
      }

      const headers: Record<string, string> = {
        "Content-Type": "application/json",
      };
      const token = getApiToken();
      if (token) headers.Authorization = `Bearer ${token}`;
      if (selectedAgent) {
        headers["X-Agent-Id"] = selectedAgent;
      }

      const input = data.input || [];
      const lastInput = input.slice(-1);
      const session = lastInput[0]?.session || {};
      const optimisticText = extractUserTextFromInput(lastInput[0]);
      const optimisticContent = lastInput[0]?.content;
      const pendingUserMessage: Message | null =
        optimisticText || Array.isArray(optimisticContent)
          ? {
              role: String(lastInput[0]?.role || "user"),
              content: Array.isArray(optimisticContent)
                ? optimisticContent
                : optimisticText,
            }
          : null;
      if (optimisticText) {
        sessionApi.setLastUserMessage(sessionId, optimisticText);
        const resolvedSessionId = sessionApi.getRealIdForSession(sessionId);
        if (resolvedSessionId && resolvedSessionId !== sessionId) {
          sessionApi.setLastUserMessage(resolvedSessionId, optimisticText);
        }
      }

      const response = await fetch(getApiUrl("/console/chat"), {
        method: "POST",
        headers,
        signal: data.signal,
        body: JSON.stringify({
          input: lastInput,
          session_id: sessionId || data.session_id || session?.session_id || "",
          user_id: data.user_id || session?.user_id || "default",
          channel: data.channel || session?.channel || "console",
          stream: true,
        }),
      });

      setIsChatStreaming(true);
      updateTransientMessages(pendingUserMessage ? [pendingUserMessage] : []);

      if (!response.ok || !response.body || !onAssistantTurnCompleted) {
        setIsChatStreaming(false);
        updateTransientMessages([]);
        return response;
      }

      const [uiStream, cacheStream] = response.body.tee();
      void (async () => {
        const responseBuilder = new AgentScopeRuntimeResponseBuilder({
          id: "",
          status: AgentScopeRuntimeRunStatus.Created,
          created_at: 0,
        });
        let latestRenderable: StreamResponseData | null = null;

        try {
          for await (const chunk of Stream({ readableStream: cacheStream })) {
            let chunkData: unknown;
            try {
              chunkData = JSON.parse(chunk.data);
            } catch {
              continue;
            }

            const responseData = responseBuilder.handle(
              chunkData as never,
            ) as StreamResponseData;

            if (hasRenderableOutput(responseData)) {
              latestRenderable = JSON.parse(
                JSON.stringify(responseData),
              ) as StreamResponseData;

              const partialAssistantText = extractAssistantText(latestRenderable);
              updateTransientMessages(
                [
                  pendingUserMessage,
                  partialAssistantText
                    ? {
                        role: "assistant",
                        content: partialAssistantText,
                      }
                    : null,
                ].filter(Boolean) as Message[],
              );
            }

            if (!isFinalResponseStatus(responseData.status)) {
              continue;
            }

            const finalPayload = latestRenderable || responseData;
            onAssistantTurnCompleted({
              text: extractAssistantText(finalPayload),
              response: finalPayload as Record<string, unknown>,
            });
            setIsChatStreaming(false);
            await loadChatHistory();
            if (runtimeStatusOpen) {
              runtimeStatusRetryCountRef.current = 0;
              await loadRuntimeStatusWithRetry();
            }
            updateTransientMessages([]);
            break;
          }
        } catch (error) {
          setIsChatStreaming(false);
          updateTransientMessages([]);
          console.warn("AnywhereChat stream side-channel parse failed", error);
        }
      })();

      return new Response(uiStream, {
        status: response.status,
        statusText: response.statusText,
        headers: response.headers,
      });
    },
    [
      loadChatHistory,
      loadRuntimeStatusWithRetry,
      onAssistantTurnCompleted,
      runtimeStatusOpen,
      selectedAgent,
      sessionId,
      updateTransientMessages,
    ],
  );

  const options = useMemo(() => {
    const i18nConfig = getDefaultConfig(t);
    const senderConfig = (i18nConfig as SenderConfigShape).sender || {};
    const welcomeConfig = (i18nConfig.welcome || {}) as WelcomeConfigShape;
    const prompts =
      Array.isArray(welcomePrompts) && welcomePrompts.length > 0
        ? welcomePrompts.map((value) => ({ value }))
        : (welcomeConfig.prompts || []);

    return {
      ...i18nConfig,
      theme: {
        ...defaultConfig.theme,
        darkMode: isDark,
        leftHeader: null,
        rightHeader: null,
      },
      sender: {
        ...senderConfig,
        attachments: undefined,
        placeholder: inputPlaceholder || senderConfig.placeholder,
      },
      welcome: {
        ...welcomeConfig,
        greeting: welcomeGreeting || welcomeConfig.greeting,
        description: welcomeDescription || welcomeConfig.description,
        prompts,
      },
      session: {
        multiple: false,
        api: singleSessionApi,
      },
      api: {
        ...defaultConfig.api,
        fetch: customFetch,
        cancel(data: { session_id?: string }) {
          const chatIdForStop = data?.session_id || sessionId;
          if (chatIdForStop) {
            void chatApi.stopConsoleChat(chatIdForStop).catch((err) => {
              console.error("stopConsoleChat failed:", err);
              message.error(t("chat.stopFailed", "Failed to stop chat."));
            });
          }
        },
      },
      actions: {
        list: [],
        replace: true,
      },
    } as unknown as IAgentScopeRuntimeWebUIOptions;
  }, [
    customFetch,
    inputPlaceholder,
    isDark,
    sessionId,
    singleSessionApi,
    t,
    welcomeDescription,
    welcomeGreeting,
    welcomePrompts,
  ]);

  const runtimeStatusContent = useMemo(() => {
    const systemItems = runtimeStatus.breakdown.filter((item) => item.section === "system");
    const userItems = runtimeStatus.breakdown.filter((item) => item.section === "user");
    const hasFrontendLiveContribution = transientMessages.length > 0;
    const hasPreciseBackendSnapshot = runtimeStatusFromApi?.snapshot_source === "runtime_push";
    const hasEmptyBackendBaseline = runtimeStatusFromApi?.snapshot_source === "empty_baseline";
    const snapshotAgentLabel = runtimeStatusMeta.agent_id || t("chat.runtimeStatusFrontendLive", "frontend-live");
    const snapshotChatLabel = runtimeStatusMeta.chat_id || t("chat.runtimeStatusFrontendLive", "frontend-live");
    const snapshotScopeLabel = runtimeStatusMeta.scope_level || "unknown";
    const snapshotStageLabel = runtimeStatusMeta.snapshot_stage || "unknown";
    const snapshotSourceRawLabel = runtimeStatusMeta.snapshot_source || "unknown";
    const samplingStatusLabel = runtimeStatusError
      ? t("chat.runtimeStatusError", "采集异常")
      : hasEmptyBackendBaseline
        ? t("chat.runtimeStatusWaitingBackend", "等待后端采样")
        : lastRuntimeStatusUpdatedAt
        ? t("chat.runtimeStatusHealthy", "采集正常")
        : t("chat.runtimeStatusPending", "等待首次采样");
    const samplingStatusColor = runtimeStatusError
      ? "#ff7875"
      : hasEmptyBackendBaseline
        ? "#faad14"
        : lastRuntimeStatusUpdatedAt
        ? "#95de64"
        : "rgba(255,255,255,0.5)";
    const statusSourceLabel = hasPreciseBackendSnapshot
      ? hasFrontendLiveContribution
        ? t("chat.runtimeStatusHybrid", "后端 + 前端实时")
        : t("chat.runtimeStatusPrecise", "后端精确统计")
      : hasEmptyBackendBaseline
        ? t("chat.runtimeStatusEstimatedPendingBackend", "前端估算（等待后端采样）")
      : t("chat.runtimeStatusEstimated", "前端估算");
    const statusSourceColor = hasPreciseBackendSnapshot
      ? hasFrontendLiveContribution
        ? "#69b1ff"
        : "#95de64"
      : hasEmptyBackendBaseline
        ? "#faad14"
      : "#faad14";
    const lastUpdatedLabel = lastRuntimeStatusUpdatedAt
      ? new Date(lastRuntimeStatusUpdatedAt).toLocaleTimeString([], {
          hour12: false,
          hour: "2-digit",
          minute: "2-digit",
          second: "2-digit",
        })
      : t("chat.runtimeStatusPending", "等待首次采样");

    const renderItem = (label: string, tokens: number, ratio: number) => (
      <div
        key={label}
        style={{
          display: "grid",
          gridTemplateColumns: "1fr auto auto",
          gap: 8,
          alignItems: "center",
          fontSize: 12,
        }}
      >
        <span style={{ color: "rgba(255,255,255,0.88)" }}>{label}</span>
        <span style={{ color: "rgba(255,255,255,0.6)" }}>{formatTokenCount(tokens)}</span>
        <span style={{ color: "rgba(255,255,255,0.88)" }}>{(ratio * 100).toFixed(1)}%</span>
      </div>
    );

    const renderMetaRow = (label: string, value: string, testId: string) => (
      <div
        key={label}
        style={{
          display: "grid",
          gridTemplateColumns: "92px 1fr",
          gap: 8,
          alignItems: "start",
          fontSize: 11,
        }}
      >
        <span style={{ color: "rgba(255,255,255,0.5)" }}>{label}</span>
        <span
          data-testid={testId}
          style={{
            color: "rgba(255,255,255,0.82)",
            fontFamily: 'ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", "Courier New", monospace',
            wordBreak: "break-all",
          }}
        >
          {value}
        </span>
      </div>
    );

    return (
      <div style={{ width: 340, display: "flex", flexDirection: "column", gap: 12 }}>
        <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
          <span style={{ fontSize: 12, color: "rgba(255,255,255,0.6)", textTransform: "uppercase", letterSpacing: 0.6 }}>
            {t("chat.runtimeStatusWindow", "上下文窗口")}
          </span>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline" }}>
            <span style={{ fontSize: 18, fontWeight: 600, color: "#fff" }}>
              {formatTokenCount(runtimeStatus.used_tokens)}/{formatTokenCount(runtimeStatus.context_window_tokens)} {t("chat.runtimeStatusTokens", "个令牌")}
            </span>
            <span style={{ fontSize: 18, fontWeight: 700, color: runtimeStatus.used_ratio >= 0.8 ? "#ff7875" : "#95de64" }}>
              {Math.round(runtimeStatus.used_ratio * 100)}%
            </span>
          </div>
          <div style={{ height: 8, borderRadius: 999, background: "rgba(255,255,255,0.12)", overflow: "hidden" }}>
            <div
              style={{
                width: `${Math.min(100, runtimeStatus.used_ratio * 100)}%`,
                height: "100%",
                background: runtimeStatus.used_ratio >= 0.8 ? "#ff7875" : "linear-gradient(90deg, #69b1ff, #95de64)",
              }}
            />
          </div>
          <div style={{ display: "flex", justifyContent: "space-between", fontSize: 12, color: "rgba(255,255,255,0.72)" }}>
            <span>{t("chat.runtimeStatusReserved", "保留用于响应")}</span>
            <span>{formatTokenCount(runtimeStatus.reserved_response_tokens)}</span>
          </div>
          <div style={{ display: "flex", justifyContent: "space-between", fontSize: 12, color: "rgba(255,255,255,0.72)" }}>
            <span>{t("chat.runtimeStatusRemaining", "剩余可用")}</span>
            <span>{formatTokenCount(runtimeStatus.remaining_tokens)}</span>
          </div>
        </div>

        <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
          <span style={{ fontSize: 12, color: "rgba(255,255,255,0.6)", textTransform: "uppercase", letterSpacing: 0.6 }}>
            {t("chat.runtimeStatusSystem", "System")}
          </span>
          {systemItems.map((item) => renderItem(item.label, item.tokens, item.ratio))}
        </div>

        <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
          <span style={{ fontSize: 12, color: "rgba(255,255,255,0.6)", textTransform: "uppercase", letterSpacing: 0.6 }}>
            {t("chat.runtimeStatusUserContext", "User Context")}
          </span>
          {userItems.map((item) => renderItem(item.label, item.tokens, item.ratio))}
        </div>

        <div style={{ display: "flex", justifyContent: "space-between", fontSize: 11, color: "rgba(255,255,255,0.5)" }}>
          <span>{runtimeStatus.profile_label}</span>
          <span>{runtimeStatus.model_id || runtimeStatus.provider_id || "unknown"}</span>
        </div>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", fontSize: 11 }}>
          <span style={{ color: "rgba(255,255,255,0.5)" }}>
            {t("chat.runtimeStatusSource", "统计来源")}
          </span>
          <span
            style={{
              color: statusSourceColor,
              fontWeight: 600,
            }}
          >
            {statusSourceLabel}
          </span>
        </div>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", fontSize: 11 }}>
          <span style={{ color: "rgba(255,255,255,0.5)" }}>
            {t("chat.runtimeStatusUpdatedAt", "上次更新时间")}
          </span>
          <span style={{ color: "rgba(255,255,255,0.72)" }}>
            {lastUpdatedLabel}
          </span>
        </div>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", fontSize: 11 }}>
          <span style={{ color: "rgba(255,255,255,0.5)" }}>
            {t("chat.runtimeStatusSampling", "采集状态")}
          </span>
          <span
            title={runtimeStatusError || undefined}
            style={{ color: samplingStatusColor }}
          >
            {samplingStatusLabel}
          </span>
        </div>

        <div style={{ display: "flex", flexDirection: "column", gap: 8, paddingTop: 4, borderTop: "1px solid rgba(255,255,255,0.08)" }}>
          <span style={{ fontSize: 12, color: "rgba(255,255,255,0.6)", textTransform: "uppercase", letterSpacing: 0.6 }}>
            {t("chat.runtimeStatusSnapshotMeta", "Snapshot Boundary")}
          </span>
          {renderMetaRow(t("chat.runtimeStatusSnapshotSource", "后端源"), snapshotSourceRawLabel, "runtime-status-meta-source")}
          {renderMetaRow(t("chat.runtimeStatusSnapshotStage", "采样阶段"), snapshotStageLabel, "runtime-status-meta-stage")}
          {renderMetaRow(t("chat.runtimeStatusSnapshotScope", "归属层级"), snapshotScopeLabel, "runtime-status-meta-scope")}
          {renderMetaRow(t("chat.runtimeStatusSnapshotAgent", "Agent"), snapshotAgentLabel, "runtime-status-meta-agent")}
          {renderMetaRow(t("chat.runtimeStatusSnapshotChat", "Chat"), snapshotChatLabel, "runtime-status-meta-chat")}
        </div>
      </div>
    );
  }, [
    lastRuntimeStatusUpdatedAt,
    runtimeStatus,
    runtimeStatusError,
    runtimeStatusFromApi,
    runtimeStatusMeta,
    transientMessages,
    t,
  ]);

  const runtimeTriggerTone = runtimeStatusError
    ? "#ff7875"
    : runtimeStatusFromApi?.snapshot_source === "empty_baseline"
      ? "#faad14"
      : lastRuntimeStatusUpdatedAt
      ? "#95de64"
      : isDark
        ? "rgba(255,255,255,0.88)"
        : "rgba(0,0,0,0.88)";

  const runtimeTriggerLabel = runtimeStatusError
    ? t("chat.runtimeStatusErrorShort", "异常")
    : runtimeStatusFromApi?.snapshot_source === "empty_baseline"
      ? t("chat.runtimeStatusPendingShort", "等待")
      : lastRuntimeStatusUpdatedAt
      ? t("chat.runtimeStatusHealthyShort", "正常")
      : t("chat.runtimeStatusPendingShort", "等待");

  return (
    <div
      className={hostClassName}
      style={{
        height: "100%",
        minHeight: 0,
        maxHeight: "100%",
        width: "100%",
        display: "flex",
        flexDirection: "column",
        overflow: "hidden",
      }}
    >
      <div
        className="copaw-chat-anywhere-header"
        style={{
          height: 44,
          minHeight: 44,
          maxHeight: 44,
          flexShrink: 0,
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          gap: 8,
          padding: "4px 8px",
          overflow: "hidden",
        }}
      >
        <ModelSelector />
        <div style={{ display: "flex", alignItems: "center", gap: 8, flexShrink: 0 }}>
          <Popover
            trigger="click"
            placement="bottomRight"
            open={runtimeStatusOpen}
            onOpenChange={(open) => {
              setRuntimeStatusOpen(open);
            }}
            content={runtimeStatusContent}
            overlayInnerStyle={{
              borderRadius: 12,
              background: isDark ? "rgba(20,22,28,0.96)" : "rgba(20,22,28,0.96)",
              boxShadow: "0 16px 48px rgba(0,0,0,0.24)",
              padding: 14,
            }}
          >
            <Button
              data-testid="runtime-status-trigger"
              size="small"
              type="text"
              aria-label={t("chat.runtimeStatus", "运行状态")}
              title={runtimeStatusError || undefined}
              style={{
                display: "inline-flex",
                alignItems: "center",
                gap: 6,
                borderRadius: 999,
                border: "1px solid rgba(255,255,255,0.12)",
                background: isDark ? "rgba(255,255,255,0.04)" : "rgba(0,0,0,0.04)",
                color: runtimeTriggerTone,
                paddingInline: 10,
              }}
            >
              <DashboardOutlined />
              <span style={{ fontSize: 12, fontWeight: 600 }}>
                {Math.round(runtimeStatus.used_ratio * 100)}%
              </span>
              <span style={{ fontSize: 11, fontWeight: 500 }}>
                {runtimeTriggerLabel}
              </span>
            </Button>
          </Popover>
          <Button size="small" onClick={onNewChat}>
            {t("chat.newChat", "New Chat")}
          </Button>
        </div>
      </div>
      <div
        className="copaw-chat-anywhere-chat"
        style={{ flex: 1, minHeight: 0, maxHeight: "100%", overflow: "hidden" }}
      >
        <AgentScopeRuntimeWebUI
          ref={chatRef}
          key={`${sessionId}-${refreshKey}`}
          options={options}
        />
      </div>
    </div>
  );
}