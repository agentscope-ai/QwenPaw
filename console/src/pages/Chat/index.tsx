import {
  AgentScopeRuntimeWebUI,
  IAgentScopeRuntimeWebUIOptions,
} from "@agentscope-ai/chat";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Button, Card, Modal, Result, Select, Space, Switch, Typography, message } from "antd";
import { ExclamationCircleOutlined, SettingOutlined } from "@ant-design/icons";
import { SparkCopyLine } from "@agentscope-ai/icons";
import { useTranslation } from "react-i18next";
import { useLocation, useNavigate } from "react-router-dom";
import api from "../../api";
import type { PendingApproval } from "../../api/modules/approval";
import sessionApi from "./sessionApi";
import type { ExternalAgentMeta } from "./sessionApi";
import defaultConfig, { getDefaultConfig } from "./OptionsPanel/defaultConfig";
import Weather from "./Weather";
import { getApiToken, getApiUrl } from "../../api/config";
import { providerApi } from "../../api/modules/provider";
import ModelSelector from "./ModelSelector";

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

type ExternalAgentState = {
  enabled: boolean;
  harness: "opencode" | "qwen";
  keepSession: boolean;
};

const DEFAULT_EXTERNAL_AGENT: ExternalAgentState = {
  enabled: false,
  harness: "opencode",
  keepSession: false,
};

function isTempSessionId(value?: string): boolean {
  return !!value && /^\d+$/.test(value);
}

function stripQuotedValue(value?: string): string | undefined {
  if (!value) return undefined;
  const trimmed = value.trim();
  if (
    trimmed.length >= 2 &&
    ((trimmed.startsWith('"') && trimmed.endsWith('"')) ||
      (trimmed.startsWith("'") && trimmed.endsWith("'")))
  ) {
    return trimmed.slice(1, -1).trim() || undefined;
  }
  return trimmed || undefined;
}

/**
 * Parse external agent config from natural language or command-line style input.
 * Supported patterns:
 * - ACP slash: "/acp opencode ...", "/acp qwen --cwd . --keep-session ..."
 * - Agent slash: "/opencode 分析...", "/qwen --session 分析..."
 * - Command: "--harness=opencode 分析...", "--harness opencode --cwd . 分析..."
 * - Natural: "用 opencode 分析...", "使用 qwen 在 /tmp 下分析..."
 * 
 * Returns null if no external agent trigger found.
 */
function parseExternalAgentFromText(text: string): {
  harness: "opencode" | "qwen";
  keepSession: boolean;
  keepSessionSpecified: boolean;
  cwd?: string;
  existingSessionId?: string;
  cleanText: string;
} | null {
  if (!text || typeof text !== "string") return null;
  
  const trimmed = text.trim();

  let harness: "opencode" | "qwen" | null = null;
  let working = trimmed;

  const normalizeHarness = (raw?: string): "opencode" | "qwen" | null => {
    const value = raw?.trim().toLowerCase().replace(/\s+/g, " ");
    if (!value) return null;
    if (["opencode", "open-code", "open code"].includes(value)) return "opencode";
    if (["qwen", "qwen-code", "qwen code", "qwencode"].includes(value)) return "qwen";
    return null;
  };

  if (/^\/acp\b/i.test(trimmed)) {
    working = trimmed.replace(/^\/acp\b/i, "").trim();
    const leadingHarness = working.match(
      /^(opencode|open(?:\s|-)?code|qwen(?:\s*code|-code)?|qwencode)\b\s*(.*)$/i,
    );
    if (leadingHarness) {
      harness = normalizeHarness(leadingHarness[1]);
      working = leadingHarness[2]?.trim() || "";
    } else {
      const harnessOption = working.match(
        /(?:^|\s)--harness(?:=|\s+)(".*?"|'.*?'|\S+)/i,
      );
      harness = normalizeHarness(stripQuotedValue(harnessOption?.[1]));
      if (harnessOption) {
        working = `${working.slice(0, harnessOption.index)} ${working.slice((harnessOption.index || 0) + harnessOption[0].length)}`.trim();
      }
    }
    if (!harness) return null;
  } else {
    const slashMatch = trimmed.match(
      /^\/(opencode|open(?:\s|-)?code|qwen(?:\s*code|-code)?|qwencode)\b\s*(.*)$/i,
    );
    const cmdMatch = trimmed.match(
      /^(?:--harness)(?:=|\s+)(opencode|open(?:\s|-)?code|qwen(?:\s*code|-code)?|qwencode)\b\s*(.*)$/i,
    );
    const naturalMatch = trimmed.match(
      /^(?:用|使用|让|通过|调用)\s+(opencode|open(?:\s|-)?code|qwen(?:\s*code|-code)?|qwencode)\b(?:\s*(?:来|去|帮忙|帮助))?\s*(.*)$/i,
    );
    const englishMatch = trimmed.match(
      /^(?:use|with|via|call)\s+(opencode|open(?:\s|-)?code|qwen(?:\s*code|-code)?|qwencode)\b(?:\s+to)?\s*(.*)$/i,
    );
    const match = slashMatch || cmdMatch || naturalMatch || englishMatch;
    if (!match) return null;
    harness = normalizeHarness(match[1]) as "opencode" | "qwen";
    working = match[2]?.trim() || "";
  }

  let keepSession = false;
  let keepSessionSpecified = false;

  const keepFlag = working.match(/(?:^|\s)(--keep-session|--session)\b/i);
  if (keepFlag) {
    keepSession = true;
    keepSessionSpecified = true;
    working = `${working.slice(0, keepFlag.index)} ${working.slice((keepFlag.index || 0) + keepFlag[0].length)}`.trim();
  }

  const sessionMatch = working.match(
    /(?:^|\s)(?:--session-id|--resume-session|--load-session)(?:=|\s+)(".*?"|'.*?'|\S+)/i,
  );
  const naturalSessionMatch =
    sessionMatch ||
    working.match(/(?:继续|复用|加载)\s*(?:session|会话)\s+(".*?"|'.*?'|\S+)/i);
  const existingSessionId = stripQuotedValue(naturalSessionMatch?.[1]);
  if (naturalSessionMatch) {
    keepSession = true;
    keepSessionSpecified = true;
    working = `${working.slice(0, naturalSessionMatch.index)} ${working.slice((naturalSessionMatch.index || 0) + naturalSessionMatch[0].length)}`.trim();
  }

  let cwd = stripQuotedValue(
    working.match(
      /(?:^|\s)(?:--cwd|--workdir|--working-dir|--work-path)(?:=|\s+)(".*?"|'.*?'|\S+)/i,
    )?.[1],
  );
  if (cwd) {
    working = working.replace(
      /(?:^|\s)(?:--cwd|--workdir|--working-dir|--work-path)(?:=|\s+)(".*?"|'.*?'|\S+)/i,
      " ",
    );
  } else {
    const naturalCwd =
      working.match(/(?:工作路径|工作目录|workdir|cwd)\s*(?:是|为|=|:|：)?\s*(".*?"|'.*?'|\S+)/i) ||
      working.match(/在\s+(".*?"|'.*?'|\S+)\s+(?:下|目录下|工作目录下)/i);
    const candidate = stripQuotedValue(naturalCwd?.[1]);
    if (candidate && /[./~\\:]/.test(candidate)) {
      cwd = candidate;
      working = `${working.slice(0, naturalCwd?.index || 0)} ${working.slice((naturalCwd?.index || 0) + (naturalCwd?.[0].length || 0))}`.trim();
    }
  }

  if (/(保持会话|keep session)/i.test(working)) {
    keepSession = true;
    keepSessionSpecified = true;
    working = working.replace(/(保持会话|keep session)/gi, " ");
  }

  if (
    /(?:之前的|上一个|上次的|刚才的|当前的?|现在的?)\s*(?:acp\s*)?(?:session|会话)|(?:previous|last|current)\s+(?:acp\s+)?session/i.test(
      working,
    )
  ) {
    keepSession = true;
    keepSessionSpecified = true;
    working = working.replace(
      /(?:请)?\s*(?:使用|复用|继续用|沿用|在)?\s*(?:之前的|上一个|上次的|刚才的|当前的?|现在的?)\s*(?:acp\s*)?(?:session|会话)(?:\s*用)?|(?:use|reuse|continue with)\s+(?:the\s+)?(?:previous|last|current)\s+(?:acp\s+)?session/gi,
      " ",
    );
  }

  const cleanText = working.trim().replace(/^[,，:：;；。.、\s]+/, "") || "请帮我处理";
  return {
    harness,
    keepSession,
    keepSessionSpecified,
    cwd,
    existingSessionId,
    cleanText,
  };
}

function externalAgentStateFromMeta(
  meta?: ExternalAgentMeta | null,
): ExternalAgentState {
  const harness = meta?.harness === "qwen" ? "qwen" : "opencode";
  return {
    enabled: Boolean(meta?.enabled),
    harness,
    keepSession: Boolean(meta?.keep_session),
  };
}

function ExternalAgentSelector(props: {
  value: ExternalAgentState;
  onChange: (value: ExternalAgentState) => void;
}) {
  const { value, onChange } = props;

  return (
    <Space size={8} align="center">
      <Typography.Text type="secondary">External Agent</Typography.Text>
      <Select
        size="small"
        style={{ width: 130 }}
        value={value.enabled ? value.harness : "off"}
        onChange={(next) => {
          if (next === "off") {
            onChange({ ...value, enabled: false });
            return;
          }
          onChange({
            ...value,
            enabled: true,
            harness: next as "opencode" | "qwen",
          });
        }}
        options={[
          { value: "off", label: "Off" },
          { value: "opencode", label: "OpenCode" },
          { value: "qwen", label: "Qwen Code" },
        ]}
      />
      <Typography.Text type="secondary">Keep Session</Typography.Text>
      <Switch
        size="small"
        checked={value.keepSession}
        disabled={!value.enabled}
        onChange={(checked) => onChange({ ...value, keepSession: checked })}
      />
    </Space>
  );
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
  const chatId = useMemo(() => {
    const match = location.pathname.match(/^\/chat\/(.+)$/);
    return match?.[1];
  }, [location.pathname]);
  const [showModelPrompt, setShowModelPrompt] = useState(false);
  const [externalAgent, setExternalAgent] =
    useState<ExternalAgentState>(DEFAULT_EXTERNAL_AGENT);
  const [pendingApproval, setPendingApproval] = useState<PendingApproval | null>(
    null,
  );
  const [approvalLoading, setApprovalLoading] = useState(false);

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
    let cancelled = false;

    const loadExternalAgentMeta = async () => {
      if (!chatId) {
        if (!cancelled) setExternalAgent(DEFAULT_EXTERNAL_AGENT);
        return;
      }

      await sessionApi.getSessionList();
      if (cancelled) return;

      const meta = sessionApi.getExternalAgentMeta(chatId);
      if (!meta) {
        setExternalAgent(DEFAULT_EXTERNAL_AGENT);
        return;
      }
      setExternalAgent(externalAgentStateFromMeta(meta));
    };

    void loadExternalAgentMeta();

    return () => {
      cancelled = true;
    };
  }, [chatId]);

  const persistExternalAgentMeta = useCallback(
    async (value: ExternalAgentState) => {
      const currentChatId = chatIdRef.current;
      if (!currentChatId) return;

      try {
        await sessionApi.setExternalAgentMeta(currentChatId, {
          enabled: value.enabled,
          harness: value.harness,
          keep_session: value.keepSession,
        });
      } catch (error) {
        console.error("Failed to persist external agent meta", error);
      }
    },
    [],
  );

  const handleExternalAgentChange = useCallback(
    (value: ExternalAgentState) => {
      setExternalAgent(value);
      void persistExternalAgentMeta(value);
    },
    [persistExternalAgentMeta],
  );

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

  const customFetch = useCallback(
    async (data: {
      input: any[];
      biz_params?: any;
      signal?: AbortSignal;
    }): Promise<Response> => {
      const { input, biz_params } = data;
      
      // Try to parse external agent from user input text
      const lastInput = input[input.length - 1];
      const userText = lastInput?.content?.find((c: any) => c.type === "text")?.text || "";
      const parsedAgent = parseExternalAgentFromText(userText);
      const isSlashCommand = /^\s*\/\S+/.test(userText);
      
      // Use parsed agent (from text) or fallback to UI state
      const useExternalAgent = parsedAgent ? true : externalAgent.enabled;
      const harness = parsedAgent?.harness || externalAgent.harness;
      const keepSession = parsedAgent
        ? parsedAgent.keepSessionSpecified
          ? parsedAgent.keepSession
          : externalAgent.keepSession
        : externalAgent.keepSession;
      
      // If parsed from text, clean the input
      let cleanedInput = input;
      if (parsedAgent && lastInput) {
        cleanedInput = input.map((item, idx) => {
          if (idx === input.length - 1 && item.content) {
            return {
              ...item,
              content: item.content.map((c: any) => {
                if (c.type === "text") {
                  return { ...c, text: parsedAgent.cleanText };
                }
                return c;
              }),
            };
          }
          return item;
        });
        
        // Also update UI state for consistency (optional)
        setExternalAgent({
          enabled: true,
          harness: parsedAgent.harness,
          keepSession,
        });
      }

      if (!useExternalAgent && !isSlashCommand) {
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
      }

      const session = input[input.length - 1]?.session || {};

      const externalAgentPayload = useExternalAgent
        ? {
            enabled: true,
            harness,
            keep_session: keepSession,
            ...(parsedAgent?.cwd ? { cwd: parsedAgent.cwd } : {}),
            ...(parsedAgent?.existingSessionId
              ? { existing_session_id: parsedAgent.existingSessionId }
              : {}),
          }
        : {
            enabled: false,
          };

      const requestBody = {
        input: cleanedInput.slice(-1),
        session_id: window.currentSessionId || session?.session_id || "",
        user_id: window.currentUserId || session?.user_id || "default",
        channel: window.currentChannel || session?.channel || "console",
        stream: true,
        ...biz_params,
        biz_params: {
          ...(biz_params || {}),
          external_agent: externalAgentPayload,
        },
        external_agent: externalAgentPayload,
      };

      const headers: Record<string, string> = {
        "Content-Type": "application/json",
      };
      const token = getApiToken();
      if (token) headers.Authorization = `Bearer ${token}`;

      return fetch(defaultConfig?.api?.baseURL || getApiUrl("/agent/process"), {
        method: "POST",
        headers,
        body: JSON.stringify(requestBody),
        signal: data.signal,
      });
    },
    [externalAgent, setExternalAgent],
  );

  useEffect(() => {
    let cancelled = false;

    const pollPendingApproval = async () => {
      const sessionId = window.currentSessionId || "";
      if (!sessionId || isTempSessionId(sessionId)) {
        if (!cancelled) setPendingApproval(null);
        return;
      }

      try {
        const pending = await api.getPendingApproval(sessionId);
        if (!cancelled) {
          setPendingApproval(pending);
        }
      } catch (error) {
        if (!cancelled) {
          setPendingApproval(null);
        }
      }
    };

    void pollPendingApproval();
    const timer = window.setInterval(() => {
      void pollPendingApproval();
    }, 2000);

    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [chatId]);

  const resolvePendingApproval = useCallback(
    async (decision: "approve" | "deny") => {
      if (!pendingApproval) return;
      setApprovalLoading(true);
      try {
        if (decision === "approve") {
          await api.approveRequest(pendingApproval.request_id);
          message.success("Approved");
        } else {
          await api.denyRequest(pendingApproval.request_id);
          message.success("Denied");
        }
        setPendingApproval(null);
      } catch (error) {
        message.error("Failed to update approval");
      } finally {
        setApprovalLoading(false);
      }
    },
    [pendingApproval],
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
        rightHeader: (
          <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
            <ModelSelector />
            <ExternalAgentSelector
              value={externalAgent}
              onChange={handleExternalAgentChange}
            />
          </div>
        ),
      },
      sender: {
        ...(i18nConfig as any)?.sender,
        beforeSubmit: handleBeforeSubmit,
      },
      session: { multiple: true, api: wrappedSessionApi },
      welcome: {
        ...(i18nConfig as any)?.welcome,
        prompts: [
          { value: "/acp opencode --cwd . 分析当前仓库" },
          { value: "/opencode 分析一下代码结构" },
          { value: "用 qwen 帮我写个函数" },
          { value: "--harness=opencode 重构这个文件" },
        ],
      },
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
  }, [
    wrappedSessionApi,
    customFetch,
    copyResponse,
    externalAgent,
    handleExternalAgentChange,
    t,
  ]);

  return (
    <div style={{ height: "100%", width: "100%" }}>
      <AgentScopeRuntimeWebUI options={options} />

      {pendingApproval ? (
        <Card
          size="small"
          style={{
            position: "fixed",
            right: 24,
            bottom: 24,
            width: 420,
            zIndex: 20,
            boxShadow: "0 8px 24px rgba(0,0,0,0.12)",
          }}
          title="Pending Approval"
          extra={<Typography.Text type="secondary">{pendingApproval.tool_name}</Typography.Text>}
        >
          <Typography.Paragraph style={{ whiteSpace: "pre-wrap", marginBottom: 12 }}>
            {String(
              pendingApproval.extra?.approval_message ||
                pendingApproval.result_summary ||
                "External agent is waiting for approval.",
            )}
          </Typography.Paragraph>
          <Space>
            <Button
              type="primary"
              loading={approvalLoading}
              onClick={() => {
                void resolvePendingApproval("approve");
              }}
            >
              Allow
            </Button>
            <Button
              danger
              loading={approvalLoading}
              onClick={() => {
                void resolvePendingApproval("deny");
              }}
            >
              Deny
            </Button>
          </Space>
        </Card>
      ) : null}

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
