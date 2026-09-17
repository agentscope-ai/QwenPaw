import type { RequestOptions } from "../request";

export interface AgentRequestContext {
  agentId?: string;
  governance?: boolean;
}

function headersToRecord(headers?: HeadersInit): Record<string, string> {
  if (!headers) return {};
  if (headers instanceof Headers) {
    return Object.fromEntries(headers.entries());
  }
  if (Array.isArray(headers)) {
    return Object.fromEntries(headers);
  }
  return { ...headers };
}

export function withAgentRequestContext(
  options?: RequestOptions,
  context?: AgentRequestContext,
): RequestOptions | undefined {
  if (!context?.agentId) return options;
  return {
    ...options,
    headers: {
      ...headersToRecord(options?.headers),
      "X-Agent-Id": context.agentId,
      ...(context.governance
        ? { "X-Agent-Governance": "runtime-config" }
        : {}),
    },
  };
}
