import { DATAPAW_AGENT_ID } from "../lib/constants";
import { isDatapawAgentSelected } from "../lib/agent";
import {
  handleLiveText,
  handleThinking,
  handleToolCall,
  handleToolResult,
} from "../lib/node-stream-events";
import { handlePlanToolInStream } from "./task-card";
import { readSelectedDataSourceId } from "../chat-sender/data-source-selection";
import { resolveBackendSessionId } from "../lib/session-id";

function resolveSessionStorageKey(currentSessionId?: string | null): string {
  return resolveBackendSessionId(currentSessionId) || "default";
}

let installed = false;

type CreateInterceptedStream = typeof import("@/pages/Chat/sseIntercept").createInterceptedStream;

let createInterceptedStream: CreateInterceptedStream | null = null;

async function ensureInterceptedStream(): Promise<CreateInterceptedStream> {
  if (!createInterceptedStream) {
    const mod = await import("@/pages/Chat/sseIntercept");
    createInterceptedStream = mod.createInterceptedStream;
  }
  return createInterceptedStream;
}

function isConsoleChatUrl(url: string): boolean {
  return url.includes("/console/chat");
}

function withDatapawAgentHeader(init?: RequestInit): RequestInit {
  const headers = new Headers(init?.headers as HeadersInit | undefined);
  headers.set("X-Agent-Id", DATAPAW_AGENT_ID);
  return { ...init, headers };
}

function withDatapawChatBody(init?: RequestInit): RequestInit {
  if (!init?.body || typeof init.body !== "string") {
    return init ?? {};
  }

  try {
    const parsed = JSON.parse(init.body) as Record<string, unknown>;
    const sessionId =
      typeof parsed.session_id === "string" ? parsed.session_id : "";
    const datasourceId = readSelectedDataSourceId(
      resolveSessionStorageKey(sessionId),
    );
    if (!datasourceId) return init;

    const existingContext =
      typeof parsed.request_context === "object" && parsed.request_context
        ? (parsed.request_context as Record<string, unknown>)
        : {};

    return {
      ...init,
      body: JSON.stringify({
        ...parsed,
        request_context: {
          ...existingContext,
          datasource_id: datasourceId,
        },
      }),
    };
  } catch {
    return init;
  }
}

/**
 * Patch fetch for DataPaw agent:
 * - Add X-Agent-Id on /console/chat requests
 * - Intercept SSE for task card refresh + node drawer live stream
 */
export function installFetchPatch(): void {
  if (installed) return;
  installed = true;

  const originalFetch = window.fetch.bind(window);
  window.fetch = async (
    input: RequestInfo | URL,
    init?: RequestInit,
  ): Promise<Response> => {
    const url =
      typeof input === "string"
        ? input
        : input instanceof URL
          ? input.href
          : input.url;

    const datapawActive =
      isConsoleChatUrl(url) && isDatapawAgentSelected();
    const effectiveInit = datapawActive
      ? withDatapawChatBody(withDatapawAgentHeader(init))
      : init;

    const response = await originalFetch(input, effectiveInit);

    if (datapawActive && response.body) {
      const intercept = await ensureInterceptedStream();
      const interceptedBody = intercept(
        response.body,
        handleLiveText,
        handleToolCall,
        handleThinking,
        handleToolResult,
        handlePlanToolInStream,
      );
      return new Response(interceptedBody, {
        status: response.status,
        statusText: response.statusText,
        headers: response.headers,
      });
    }

    return response;
  };

}
