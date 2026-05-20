import { request } from "../request";
import type {
  MCPClientInfo,
  MCPClientCreateRequest,
  MCPClientUpdateRequest,
  MCPToolInfo,
  MCPOAuthBeginResponse,
  MCPOAuthCompleteResponse,
} from "../types";

export const mcpApi = {
  /**
   * List all MCP clients
   */
  listMCPClients: () => request<MCPClientInfo[]>("/mcp"),

  /**
   * Get details of a specific MCP client
   */
  getMCPClient: (clientKey: string) =>
    request<MCPClientInfo>(`/mcp/${encodeURIComponent(clientKey)}`),

  /**
   * Create a new MCP client
   */
  createMCPClient: (body: MCPClientCreateRequest) =>
    request<MCPClientInfo>("/mcp", {
      method: "POST",
      body: JSON.stringify(body),
    }),

  /**
   * Update an existing MCP client
   */
  updateMCPClient: (clientKey: string, body: MCPClientUpdateRequest) =>
    request<MCPClientInfo>(`/mcp/${encodeURIComponent(clientKey)}`, {
      method: "PUT",
      body: JSON.stringify(body),
    }),

  /**
   * Toggle MCP client enabled status
   */
  toggleMCPClient: (clientKey: string) =>
    request<MCPClientInfo>(`/mcp/${encodeURIComponent(clientKey)}/toggle`, {
      method: "PATCH",
    }),

  /**
   * Delete an MCP client
   */
  deleteMCPClient: (clientKey: string) =>
    request<{ message: string }>(`/mcp/${encodeURIComponent(clientKey)}`, {
      method: "DELETE",
    }),

  /**
   * List tools from a connected MCP server
   */
  listMCPTools: (clientKey: string) =>
    request<MCPToolInfo[]>(`/mcp/${encodeURIComponent(clientKey)}/tools`),

  /**
   * Start an OAuth authorization flow for an MCP client.
   * Returns an authorize_url to open in the browser plus the operating mode
   * (``auto`` = redirect lands on QwenPaw; ``paste`` = user pastes URL back).
   */
  beginMCPOAuth: (clientKey: string) =>
    request<MCPOAuthBeginResponse>(
      `/mcp/${encodeURIComponent(clientKey)}/auth/oauth/begin`,
      {
        method: "POST",
        body: JSON.stringify({ browser_origin: window.location.origin }),
      },
    ),

  /**
   * Complete an OAuth flow in paste mode by submitting the full callback URL.
   */
  completeMCPOAuth: (clientKey: string, callbackUrl: string) =>
    request<MCPOAuthCompleteResponse>(
      `/mcp/${encodeURIComponent(clientKey)}/auth/oauth/complete`,
      {
        method: "POST",
        body: JSON.stringify({ callback_url: callbackUrl }),
      },
    ),

  /**
   * Clear stored OAuth state for an MCP client (sign out).
   * Set revokeRemote=true to also revoke the tokens at the AS.
   */
  signOutMCPOAuth: (clientKey: string, revokeRemote = false) =>
    request<{ message: string }>(
      `/mcp/${encodeURIComponent(clientKey)}/auth?revoke_remote=${
        revokeRemote ? "true" : "false"
      }`,
      { method: "DELETE" },
    ),
};
