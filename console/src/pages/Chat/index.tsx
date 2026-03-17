import {
  AgentScopeRuntimeWebUI,
  IAgentScopeRuntimeWebUIOptions,
} from "@agentscope-ai/chat";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Button, Modal, Result, message } from "antd";
import {
  ExclamationCircleOutlined,
  PaperClipOutlined,
  SettingOutlined,
} from "@ant-design/icons";
import { SparkCopyLine } from "@agentscope-ai/icons";
import { useTranslation } from "react-i18next";
import { useLocation, useNavigate } from "react-router-dom";
import { createPortal } from "react-dom";
import sessionApi from "./sessionApi";
import defaultConfig, { getDefaultConfig } from "./OptionsPanel/defaultConfig";
import Weather from "./Weather";
import { getApiToken, getApiUrl } from "../../api/config";
import { providerApi } from "../../api/modules/provider";
import ModelSelector from "./ModelSelector";
import { useTheme } from "../../contexts/ThemeContext";
import { useAgentStore } from "../../stores/agentStore";
import styles from "./index.module.less";

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

interface CustomWindow extends Window {
  currentSessionId?: string;
  currentUserId?: string;
  currentChannel?: string;
}

declare const window: CustomWindow;

const MAX_UPLOAD_SIZE = 100 * 1024 * 1024;
const FILE_UPLOAD_MESSAGE_KEY = "chat-file-upload";

function getSelectedAgentId(): string | null {
  try {
    const agentStorage = localStorage.getItem("copaw-agent-storage");
    if (!agentStorage) return null;
    const parsed = JSON.parse(agentStorage);
    return parsed?.state?.selectedAgent || null;
  } catch (error) {
    console.warn("Failed to get selected agent from storage:", error);
    return null;
  }
}

function buildRequestHeaders(contentType?: string): Headers {
  const headers = new Headers();
  if (contentType) {
    headers.set("Content-Type", contentType);
  }

  const token = getApiToken();
  if (token) {
    headers.set("Authorization", `Bearer ${token}`);
  }

  const selectedAgentId = getSelectedAgentId();
  if (selectedAgentId) {
    headers.set("X-Agent-Id", selectedAgentId);
  }

  return headers;
}

function findSenderActionsMountNode(root: ParentNode = document): HTMLElement | null {
  const exactMatch = root.querySelector(
    ".agentscope-runtime-webui-sender-actions-list-presets",
  );
  if (exactMatch instanceof HTMLElement) {
    return exactMatch;
  }

  const fuzzyMatch = root.querySelector('[class*="sender-actions-list-presets"]');
  return fuzzyMatch instanceof HTMLElement ? fuzzyMatch : null;
}

async function consumeEventStream(response: Response): Promise<void> {
  if (!response.body) return;

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let streamError: string | null = null;

  const processChunk = (chunk: string) => {
    const events = chunk.split("\n\n");
    buffer = events.pop() || "";

    for (const event of events) {
      const lines = event
        .split("\n")
        .map((line) => line.trim())
        .filter(Boolean);

      for (const line of lines) {
        if (!line.startsWith("data:")) continue;

        const payload = line.slice(5).trim();
        if (!payload) continue;

        try {
          const parsed = JSON.parse(payload);
          if (typeof parsed?.error === "string" && parsed.error) {
            streamError = parsed.error;
          }
        } catch {
          continue;
        }
      }
    }
  };

  while (true) {
    const { value, done } = await reader.read();
    buffer += decoder.decode(value || new Uint8Array(), { stream: !done });
    processChunk(buffer);
    if (done) break;
  }

  if (buffer.trim()) {
    processChunk(`${buffer}\n\n`);
  }

  if (streamError) {
    throw new Error(streamError);
  }
}

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
  const [isUploadingFile, setIsUploadingFile] = useState(false);
  const [uploadButtonMountNode, setUploadButtonMountNode] =
    useState<HTMLElement | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const isComposingRef = useRef(false);
  const isChatActiveRef = useRef(false);
  isChatActiveRef.current =
    location.pathname === "/" || location.pathname.startsWith("/chat");

  const lastSessionIdRef = useRef<string | null>(null);
  const chatIdRef = useRef(chatId);
  const navigateRef = useRef(navigate);
  chatIdRef.current = chatId;
  navigateRef.current = navigate;

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
        if (isComposingRef.current || (e as any).isComposing) {
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
    let mountNode: HTMLSpanElement | null = null;
    let frameId = 0;
    let cancelled = false;
    let observer: MutationObserver | null = null;

    const ensureMounted = () => {
      if (cancelled || mountNode?.isConnected) return;

      const actionsNode = findSenderActionsMountNode();
      if (!actionsNode) return;

      mountNode = document.createElement("span");
      mountNode.className = styles.senderUploadButton;
      actionsNode.insertBefore(mountNode, actionsNode.firstChild);
      setUploadButtonMountNode(mountNode);
    };

    const startObserver = () => {
      observer = new MutationObserver(() => {
        ensureMounted();
      });

      observer.observe(document.body, {
        childList: true,
        subtree: true,
      });
    };

    frameId = window.requestAnimationFrame(() => {
      ensureMounted();
      startObserver();
    });

    return () => {
      cancelled = true;
      window.cancelAnimationFrame(frameId);
      observer?.disconnect();
      setUploadButtonMountNode(null);
      if (mountNode?.parentNode) {
        mountNode.parentNode.removeChild(mountNode);
      }
    };
  }, [refreshKey]);

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
    const newSessionId = result[0]?.id;
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

  const ensureModelConfigured = useCallback(async () => {
    try {
      const activeModels = await providerApi.getActiveModels();
      if (
        !activeModels?.active_llm?.provider_id ||
        !activeModels?.active_llm?.model
      ) {
        setShowModelPrompt(true);
        return false;
      }
      return true;
    } catch {
      setShowModelPrompt(true);
      return false;
    }
  }, []);

  const ensureActiveSessionId = useCallback(async () => {
    const currentSessionId = window.currentSessionId || chatIdRef.current;
    if (
      currentSessionId &&
      currentSessionId !== "undefined" &&
      currentSessionId !== "null"
    ) {
      return currentSessionId;
    }

    const sessions = await sessionApi.createSession({});
    const newSessionId = sessions[0]?.id;
    if (!newSessionId) {
      throw new Error("Failed to create chat session");
    }

    lastSessionIdRef.current = newSessionId;
    navigateRef.current(`/chat/${newSessionId}`, { replace: true });
    return newSessionId;
  }, []);

  const handleFileUpload = useCallback(
    async (file: File) => {
      if (!(await ensureModelConfigured())) {
        if (fileInputRef.current) {
          fileInputRef.current.value = "";
        }
        return;
      }

      if (file.size > MAX_UPLOAD_SIZE) {
        message.error(
          t("chat.fileTooLarge", {
            size: (file.size / (1024 * 1024)).toFixed(2),
          }),
        );
        if (fileInputRef.current) {
          fileInputRef.current.value = "";
        }
        return;
      }

      setIsUploadingFile(true);
      message.open({
        type: "loading",
        content: t("chat.fileUploading", { name: file.name }),
        key: FILE_UPLOAD_MESSAGE_KEY,
        duration: 0,
      });

      try {
        const sessionId = await ensureActiveSessionId();
        const formData = new FormData();
        formData.append("file", file);
        formData.append("session_id", sessionId);
        formData.append("user_id", window.currentUserId || "default");
        formData.append("channel", window.currentChannel || "console");

        const response = await fetch(
          defaultConfig?.api?.baseURL || getApiUrl("/console/chat-upload"),
          {
            method: "POST",
            headers: buildRequestHeaders(),
            body: formData,
          },
        );

        if (!response.ok) {
          const errorText = await response.text().catch(() => "");
          throw new Error(
            errorText || `Upload failed: ${response.status} ${response.statusText}`,
          );
        }

        await consumeEventStream(response);
        await sessionApi.updateSession({ id: sessionId });
        await sessionApi.getSession(sessionId);
        setRefreshKey((prev) => prev + 1);

        message.success({
          content: t("chat.fileUploadSuccess", { name: file.name }),
          key: FILE_UPLOAD_MESSAGE_KEY,
        });
      } catch (error) {
        console.error("File upload failed:", error);
        const errorMessage =
          error instanceof Error ? error.message : t("chat.fileUploadFailed");
        message.error({
          content: `${t("chat.fileUploadFailed")}: ${errorMessage}`,
          key: FILE_UPLOAD_MESSAGE_KEY,
        });
      } finally {
        setIsUploadingFile(false);
        if (fileInputRef.current) {
          fileInputRef.current.value = "";
        }
      }
    },
    [ensureActiveSessionId, ensureModelConfigured, t],
  );

  const handleFileInputChange = useCallback(
    (event: React.ChangeEvent<HTMLInputElement>) => {
      const file = event.target.files?.[0];
      if (!file) return;
      void handleFileUpload(file);
    },
    [handleFileUpload],
  );

  const customFetch = useCallback(
    async (data: {
      input: any[];
      biz_params?: any;
      signal?: AbortSignal;
    }): Promise<Response> => {
      if (!(await ensureModelConfigured())) {
        return buildModelError();
      }

      const { input, biz_params } = data;
      const session = input[input.length - 1]?.session || {};

      const requestBody = {
        input: input.slice(-1),
        session_id: window.currentSessionId || session?.session_id || "",
        user_id: window.currentUserId || session?.user_id || "default",
        channel: window.currentChannel || session?.channel || "console",
        stream: true,
        ...biz_params,
      };

      return fetch(defaultConfig?.api?.baseURL || getApiUrl("/console/chat"), {
        method: "POST",
        headers: buildRequestHeaders("application/json"),
        body: JSON.stringify(requestBody),
        signal: data.signal,
      });
    },
    [ensureModelConfigured],
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
        rightHeader: <ModelSelector />,
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
      },
      session: { multiple: true, api: wrappedSessionApi },
      api: {
        ...defaultConfig.api,
        fetch: customFetch,
        cancel(data: { session_id: string }) {
          console.log(data);
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
      customToolRenderConfig: {
        "weather search mock": Weather,
      },
    } as unknown as IAgentScopeRuntimeWebUIOptions;
  }, [wrappedSessionApi, customFetch, copyResponse, t, isDark]);

  return (
    <div
      className={showModelPrompt ? styles.chatDisabledOverlay : styles.chatPage}
    >
      <AgentScopeRuntimeWebUI key={refreshKey} options={options} />

      {uploadButtonMountNode
        ? createPortal(
            <Button
              type="text"
              shape="circle"
              title={t("chat.uploadButton")}
              aria-label={t("chat.uploadButton")}
              icon={<PaperClipOutlined />}
              onClick={() => fileInputRef.current?.click()}
              loading={isUploadingFile}
              disabled={isUploadingFile || showModelPrompt}
            />,
            uploadButtonMountNode,
          )
        : null}

      <input
        ref={fileInputRef}
        type="file"
        onChange={handleFileInputChange}
        style={{ display: "none" }}
      />

      <Modal open={showModelPrompt} closable={false} footer={null} width={480}>
        <Result
          icon={<ExclamationCircleOutlined style={{ color: "#faad14" }} />}
          title={t("modelConfig.promptTitle")}
          subTitle={t("modelConfig.promptMessage")}
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
