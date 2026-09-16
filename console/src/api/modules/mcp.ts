import { request } from "../request";
import { withAgentRequestContext } from "./agentRequestContext";

export interface MCPApiContext {
  agentId?: string;
  signal?: AbortSignal;
}

function options(
  context?: MCPApiContext,
  init: Parameters<typeof request>[1] = {},
) {
  if (!context && Object.keys(init).length === 0) return undefined;
  return withAgentRequestContext(
    context?.signal ? { ...init, signal: context.signal } : init,
    { agentId: context?.agentId },
  );
}
import type {
  MCPClientInfo,
  MCPClientCreateRequest,
  MCPClientUpdateRequest,
  MCPToolInfo,
  MCPAccessPrincipalOption,
  MCPAccessPolicy,
  MCPOAuthStartRequest,
  MCPOAuthStartResponse,
  MCPOAuthStatusResponse,
} from "../types";

export const mcpApi = {
  /**
   * List all MCP clients
   */
  listMCPClients: (context?: MCPApiContext) =>
    request<MCPClientInfo[]>("/mcp", options(context)),

  /**
   * Get details of a specific MCP client
   */
  getMCPClient: (clientKey: string, context?: MCPApiContext) =>
    request<MCPClientInfo>(
      `/mcp/${encodeURIComponent(clientKey)}`,
      options(context),
    ),

  /**
   * Create a new MCP client
   */
  createMCPClient: (body: MCPClientCreateRequest, context?: MCPApiContext) =>
    request<MCPClientInfo>("/mcp", options(context, {
      method: "POST",
      body: JSON.stringify(body),
    })),

  /**
   * Update an existing MCP client
   */
  updateMCPClient: (
    clientKey: string,
    body: MCPClientUpdateRequest,
    context?: MCPApiContext,
  ) =>
    request<MCPClientInfo>(`/mcp/${encodeURIComponent(clientKey)}`, options(context, {
      method: "PUT",
      body: JSON.stringify(body),
    })),

  /**
   * Toggle MCP client enabled status
   */
  toggleMCPClient: (clientKey: string, expectedRevision?: number, context?: MCPApiContext) =>
    request<MCPClientInfo>(`/mcp/toggle/${encodeURIComponent(clientKey)}${revisionQuery(expectedRevision)}`, options(context, {
      method: "PATCH",
    })),

  /**
   * Delete an MCP client
   */
  deleteMCPClient: (clientKey: string, expectedRevision?: number, context?: MCPApiContext) =>
    request<{ message: string }>(`/mcp/${encodeURIComponent(clientKey)}${revisionQuery(expectedRevision)}`, options(context, {
      method: "DELETE",
    })),

  /**
   * List tools from a connected MCP server
   */
  listMCPTools: (clientKey: string, context?: MCPApiContext) =>
    request<MCPToolInfo[]>(`/mcp/tools/${encodeURIComponent(clientKey)}`, options(context)),

  /**
   * List recent source-scoped principals for MCP access rules.
   */
  listMCPAccessPrincipals: (context?: MCPApiContext) =>
    request<MCPAccessPrincipalOption[]>("/mcp/access-principals", options(context)),

  /**
   * Get saved MCP access policy. Does not require the MCP server to be online.
   */
  getMCPPolicy: (clientKey: string, context?: MCPApiContext) =>
    request<MCPAccessPolicy>(`/mcp/policy/${encodeURIComponent(clientKey)}`, options(context)),

  /**
   * Update saved MCP access policy. Does not require the MCP server to be online.
   */
  updateMCPPolicy: (clientKey: string, body: MCPAccessPolicy, expectedRevision?: number, context?: MCPApiContext) =>
    request<MCPAccessPolicy>(`/mcp/policy/${encodeURIComponent(clientKey)}`, {
      ...options(context, {
        method: "PUT",
        body: JSON.stringify({ ...body, expected_revision: expectedRevision }),
      }),
    }),

  /**
   * Update tool whitelist for an MCP client
   */
  updateMCPToolWhitelist: (clientKey: string, tools: string[] | null, expectedRevision?: number, context?: MCPApiContext) =>
    request<MCPToolInfo[]>(`/mcp/tools/${encodeURIComponent(clientKey)}`, {
      ...options(context, { method: "PUT", body: JSON.stringify({ tools, expected_revision: expectedRevision }) }),
    }),

  /**
   * Start an OAuth 2.1 PKCE flow for a remote MCP client.
   * Returns the authorization URL to open in a popup.
   */
  startOAuth: (clientKey: string, body: MCPOAuthStartRequest, context?: MCPApiContext) =>
    request<MCPOAuthStartResponse>(
      `/mcp/oauth/start/${encodeURIComponent(clientKey)}`,
      options(context, {
        method: "POST",
        body: JSON.stringify(body),
      }),
    ),

  /**
   * Get current OAuth token status for an MCP client.
   */
  getOAuthStatus: (clientKey: string, sessionId?: string, context?: MCPApiContext) =>
    request<MCPOAuthStatusResponse>(
      `/mcp/oauth/status/${encodeURIComponent(clientKey)}${sessionId ? `?session_id=${encodeURIComponent(sessionId)}` : ""}`,
      options(context),
    ),

  /**
   * Revoke / clear OAuth tokens for an MCP client.
   */
  revokeOAuth: (clientKey: string, expectedRevision?: number, context?: MCPApiContext) =>
    request<{ message: string }>(
      `/mcp/oauth/${encodeURIComponent(clientKey)}${revisionQuery(expectedRevision)}`,
      options(context, { method: "DELETE" }),
    ),
};

function revisionQuery(revision?: number): string {
  return revision === undefined ? "" : `?expected_revision=${revision}`;
}
