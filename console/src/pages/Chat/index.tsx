import {
  AgentScopeRuntimeWebUI,
  IAgentScopeRuntimeWebUIOptions,
  type IAgentScopeRuntimeWebUIRef,
} from "@agentscope-ai/chat";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Button, Modal, Result, message } from "antd";
import { ExclamationCircleOutlined, SettingOutlined } from "@ant-design/icons";
import { SparkCopyLine } from "@agentscope-ai/icons";
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
import { useChatAnywhereInput } from "@agentscope-ai/chat/lib/AgentScopeRuntimeWebUI/core/Context/ChatAnywhereInputContext.js";
import styles from "./index.module.less";
import { Tooltip } from "antd";
import { IconButton } from "@agentscope-ai/design";
import { SparkAttachmentLine } from "@agentscope-ai/icons";

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

type RuntimeLoadingBridgeApi = {
  getLoading?: () => boolean | string;
  setLoading?: (loading: boolean | string) => void;
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
    const handleCompositionStart = () => {
      if (!isChatActiveRef.current) return;
      isComposingRef.current = true;
    };

    const handleCompositionEnd = () => {
      if (!isChatActiveRef.current) return;
      // Use a slightly longer delay for Safari on macOS, which fires keydown
      // after compositionend within the same event loop tick.
      setTimeout(() => {
        isComposingRef.current = false;
      }, 200);
    };

    const suppressImeEnter = (e: KeyboardEvent) => {
      if (!isChatActiveRef.current) return;
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
  }, []);

  useEffect(() => {
    sessionApi.onSessionIdResolved = (tempId, realId) => {
      if (!isChatActiveRef.current) return;
      if (chatIdRef.current === tempId) {
        lastSessionIdRef.current = realId;
        navigateRef.current(`/chat/${realId}`, { replace: true });
      }
    };

    sessionApi.onSessionRemoved = (removedId) => {
      if (!isChatActiveRef.current) return;
      if (chatIdRef.current === removedId) {
        lastSessionIdRef.current = null;
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

    if (
      isChatActiveRef.current &&
      sessionId &&
      sessionId !== lastSessionIdRef.current &&
      sessionId !== currentChatId
    ) {
      const urlId = sessionApi.getRealIdForSession(sessionId) ?? sessionId;
      lastSessionIdRef.current = urlId;
      navigateRef.current(`/chat/${urlId}`, { replace: true });
    }

    return sessionApi.getSession(sessionId);
  }, []);

  const createSessionWrapped = useCallback(async (session: any) => {
    const result = await sessionApi.createSession(session);
    const newSessionId = session?.id || result[0]?.id;
    if (isChatActiveRef.current && newSessionId) {
      lastSessionIdRef.current = newSessionId;
      navigateRef.current(`/chat/${newSessionId}`, { replace: true });
    }
    return result;
  }, []);

  const wrappedSessionApi = useMemo(
    () => ({
      getSessionList: getSessionListWrapped,
      getSession: getSessionWrapped,
      createSession: createSessionWrapped,
      updateSession: sessionApi.updateSession.bind(sessionApi),
      removeSession: sessionApi.removeSession.bind(sessionApi),
    }),
    [],
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

  const customFetch = useCallback(
    async (data: {
      input?: any[];
      biz_params?: any;
      signal?: AbortSignal;
    }): Promise<Response> => {
      const headers: Record<string, string> = {
        "Content-Type": "application/json",
        ...buildAuthHeaders(),
      };

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
      const session = input[input.length - 1]?.session || {};
      const lastInput = input.slice(-1);
      const lastMsg = lastInput[0];
      const rewrittenInput =
        lastMsg?.content && Array.isArray(lastMsg.content)
          ? [
              {
                ...lastMsg,
                content: lastMsg.content.map((part: any) => {
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
                  if (p.type === "audio" && typeof p.data === "string")
                    p.data = toStoredName(p.data);
                  if (p.type === "video" && typeof p.video_url === "string")
                    p.video_url = toStoredName(p.video_url);

                  return p;
                }),
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
          .filter((m: any) => m.role === "user")
          .map((m: any) => {
            if (typeof m.content === "string") return m.content;
            if (!Array.isArray(m.content)) return "";
            return m.content
              .filter((p: any) => p.type === "text")
              .map((p: any) => p.text || "")
              .join("\n");
          })
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
    [],
  );

  const options = useMemo(() => {
    const i18nConfig = getDefaultConfig(t);

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
          customRequest: async (options: {
            file: File;
            onSuccess: (body: { url?: string; thumbUrl?: string }) => void;
            onError?: (e: Error) => void;
            onProgress?: (e: { percent?: number }) => void;
          }) => {
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
              user_id: window.currentUserId || "default",
              channel: window.currentChannel || "console",
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
  }, [wrappedSessionApi, customFetch, copyResponse, t, isDark, multimodalCaps]);

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
