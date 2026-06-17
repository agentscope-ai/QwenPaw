import { request } from "../request";
import type {
  MCPClientInfo,
  MCPClientCreateRequest,
  MCPClientUpdateRequest,
  MCPToolInfo,
  MCPOAuthStartRequest,
  MCPOAuthStartResponse,
  MCPOAuthStatusResponse,
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
    request<MCPClientInfo>(`/mcp/toggle/${encodeURIComponent(clientKey)}`, {
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
    request<MCPToolInfo[]>(`/mcp/tools/${encodeURIComponent(clientKey)}`),

  /**
   * Update tool whitelist for an MCP client
   */
  updateMCPToolWhitelist: (clientKey: string, tools: string[] | null) =>
    request<MCPToolInfo[]>(`/mcp/tools/${encodeURIComponent(clientKey)}`, {
      method: "PUT",
      body: JSON.stringify({ tools }),
    }),

  /**
   * Start an OAuth 2.1 PKCE flow for a remote MCP client.
   * Returns the authorization URL to open in a popup.
   */
  startOAuth: (clientKey: string, body: MCPOAuthStartRequest) =>
    request<MCPOAuthStartResponse>(
      `/mcp/oauth/start/${encodeURIComponent(clientKey)}`,
      {
        method: "POST",
        body: JSON.stringify(body),
      },
    ),

  /**
   * Get current OAuth token status for an MCP client.
   */
  getOAuthStatus: (clientKey: string) =>
    request<MCPOAuthStatusResponse>(
      `/mcp/oauth/status/${encodeURIComponent(clientKey)}`,
    ),

  /**
   * Revoke / clear OAuth tokens for an MCP client.
   */
  revokeOAuth: (clientKey: string) =>
    request<{ message: string }>(
      `/mcp/oauth/${encodeURIComponent(clientKey)}`,
      { method: "DELETE" },
    ),
};
