import type { TaskStatusEvent } from "../pages/Chat/components/TaskGraphPanel/types";

const DATAPAW_AGENT_ID = "datapaw";
const STORAGE_KEY = "qwenpaw-agent-storage";

let installed = false;

function isConsoleChatUrl(url: string): boolean {
  return url.includes("/console/chat");
}

export function isDatapawAgentSelected(): boolean {
  try {
    const sessionRaw = sessionStorage.getItem(STORAGE_KEY);
    if (sessionRaw) {
      const agent = JSON.parse(sessionRaw)?.state?.selectedAgent;
      if (typeof agent === "string" && agent) return agent === DATAPAW_AGENT_ID;
    }
    const localRaw = localStorage.getItem(STORAGE_KEY);
    if (localRaw) {
      const agent = JSON.parse(localRaw)?.state?.selectedAgent;
      if (typeof agent === "string" && agent) return agent === DATAPAW_AGENT_ID;
    }
  } catch {
    /* ignore */
  }
  return false;
}

function withDatapawAgentHeader(init?: RequestInit): RequestInit {
  const headers = new Headers(init?.headers as HeadersInit | undefined);
  headers.set("X-Agent-Id", DATAPAW_AGENT_ID);
  return { ...init, headers };
}

/**
 * Only augments `/console/chat` requests with `X-Agent-Id: datapaw`.
 *
 * SSE body interception lives in `pages/Chat/index.tsx` (`customFetch` /
 * `reconnect`). A second body intercept here previously consumed `task_status`
 * before the chat page saw it, so task cards never rendered.
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

    if (isConsoleChatUrl(url) && isDatapawAgentSelected()) {
      return originalFetch(input, withDatapawAgentHeader(init));
    }

    return originalFetch(input, init);
  };
}

/** @deprecated DOM panel uses fetch body intercept; kept for task-panel compile. */
export function setTaskStatusHandler(
  _handler: ((event: TaskStatusEvent) => void) | null,
): void {
  /* no-op — cards are injected via Chat/index injectTaskGraphCard */
}
