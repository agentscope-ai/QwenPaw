import { createInterceptedStream } from "@/pages/Chat/sseIntercept";
import { DATAPAW_AGENT_ID } from "../lib/constants";
import { isDatapawAgentSelected } from "../lib/agent";
import {
  handleLiveText,
  handleThinking,
  handleToolCall,
  handleToolResult,
} from "../lib/node-stream-events";
import { handlePlanToolInStream } from "./task-card";

let installed = false;

function isConsoleChatUrl(url: string): boolean {
  return url.includes("/console/chat");
}

function withDatapawAgentHeader(init?: RequestInit): RequestInit {
  const headers = new Headers(init?.headers as HeadersInit | undefined);
  headers.set("X-Agent-Id", DATAPAW_AGENT_ID);
  return { ...init, headers };
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
      ? withDatapawAgentHeader(init)
      : init;

    const response = await originalFetch(input, effectiveInit);

    if (datapawActive && response.body) {
      const interceptedBody = createInterceptedStream(
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

  console.info(
    "[datapaw] Installed fetch patch (X-Agent-Id + chat SSE intercept for task drawer)",
  );
}
