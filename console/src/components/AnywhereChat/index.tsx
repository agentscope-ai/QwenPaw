import {
  AgentScopeRuntimeWebUI,
  Stream,
  type IAgentScopeRuntimeWebUIOptions,
  type IAgentScopeRuntimeWebUIRef,
} from "@agentscope-ai/chat";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { message } from "antd";
import { useTranslation } from "react-i18next";
import defaultConfig, { getDefaultConfig } from "../../pages/Chat/OptionsPanel/defaultConfig";
import sessionApi from "../../pages/Chat/sessionApi";
import { chatApi } from "../../api/modules/chat";
import { getApiToken, getApiUrl } from "../../api/config";
import { useTheme } from "../../contexts/ThemeContext";
import { useAgentStore } from "../../stores/agentStore";
import AgentScopeRuntimeResponseBuilder from "@agentscope-ai/chat/lib/AgentScopeRuntimeWebUI/core/AgentScopeRuntime/Response/Builder.js";
import { AgentScopeRuntimeRunStatus } from "@agentscope-ai/chat/lib/AgentScopeRuntimeWebUI/core/AgentScopeRuntime/types.js";

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

interface AnywhereChatProps {
  sessionId: string;
  hostClassName?: string;
  inputPlaceholder?: string;
  welcomeGreeting?: string;
  welcomeDescription?: string;
  welcomePrompts?: string[];
  onAssistantTurnCompleted?: (payload: {
    text: string;
    response: Record<string, unknown> | null;
  }) => void;
}

type StreamResponseData = {
  status?: string;
  output?: Array<{
    role?: string;
    content?: Array<{ type?: string; text?: string; refusal?: string }>;
  }>;
};

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
  onAssistantTurnCompleted,
}: AnywhereChatProps) {
  const { t } = useTranslation();
  const { isDark } = useTheme();
  const { selectedAgent } = useAgentStore();
  const [refreshKey, setRefreshKey] = useState(0);
  const chatRef = useRef<IAgentScopeRuntimeWebUIRef>(null);

  useEffect(() => {
    setRefreshKey((prev) => prev + 1);
  }, [sessionId]);

  const singleSessionApi = useMemo(
    () => ({
      getSessionList: async () => {
        if (!sessionId) return [];
        try {
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

      if (!response.ok || !response.body || !onAssistantTurnCompleted) {
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
            }

            if (!isFinalResponseStatus(responseData.status)) {
              continue;
            }

            const finalPayload = latestRenderable || responseData;
            onAssistantTurnCompleted({
              text: extractAssistantText(finalPayload),
              response: finalPayload as Record<string, unknown>,
            });
            break;
          }
        } catch (error) {
          console.warn("AnywhereChat stream side-channel parse failed", error);
        }
      })();

      return new Response(uiStream, {
        status: response.status,
        statusText: response.statusText,
        headers: response.headers,
      });
    },
    [onAssistantTurnCompleted, selectedAgent, sessionId],
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
      <div style={{ flex: 1, minHeight: 0, maxHeight: "100%", overflow: "hidden" }}>
        <AgentScopeRuntimeWebUI
          ref={chatRef}
          key={`${sessionId}-${refreshKey}`}
          options={options}
        />
      </div>
    </div>
  );
}