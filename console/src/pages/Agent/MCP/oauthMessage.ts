export interface OAuthMessageContext {
  origin: string;
  sessionId: string;
  clientKey: string;
  agentId: string;
}

export function matchesOAuthMessage(
  event: Pick<MessageEvent, "origin" | "data">,
  context: OAuthMessageContext,
): boolean {
  const data = event.data as Record<string, unknown> | null;
  return Boolean(
    event.origin === context.origin &&
      data &&
      (data.type === "mcp-oauth-success" || data.type === "mcp-oauth-error") &&
      data.session_id === context.sessionId &&
      data.client_key === context.clientKey &&
      data.agent_id === context.agentId,
  );
}

export function isOAuthSessionComplete(
  status: { session_id?: string; status?: string; authorized: boolean },
  sessionId: string,
): boolean {
  return (
    status.session_id === sessionId &&
    status.status === "completed" &&
    status.authorized
  );
}

export type OAuthSessionTerminal = "success" | "failed" | "expired" | null;

export function getOAuthSessionTerminal(
  status: { session_id?: string; status?: string; authorized: boolean },
  sessionId: string,
): OAuthSessionTerminal {
  if (status.session_id !== sessionId) return null;
  if (status.status === "failed") return "failed";
  if (status.status === "expired") return "expired";
  if (status.status === "completed") {
    return status.authorized ? "success" : "failed";
  }
  return null;
}
