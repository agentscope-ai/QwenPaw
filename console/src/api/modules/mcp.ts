import { request } from "../request";
import type {
  MCPClientInfo,
  MCPClientCreateRequest,
  MCPClientUpdateRequest,
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

  // --- OAuth APIs ---

  /**
   * Start OAuth authorization flow
   */
  startMCPOAuth: (clientKey: string) =>
    request<MCPOAuthStartResponse>(
      `/mcp/oauth/${encodeURIComponent(clientKey)}/authorize`,
      { method: "POST" },
    ),

  /**
   * Get OAuth authorization status
   */
  getMCPOAuthStatus: (clientKey: string) =>
    request<MCPOAuthStatusResponse>(
      `/mcp/oauth/${encodeURIComponent(clientKey)}/status`,
    ),

  /**
   * Revoke OAuth authorization
   */
  revokeMCPOAuth: (clientKey: string) =>
    request<{ message: string }>(
      `/mcp/oauth/${encodeURIComponent(clientKey)}/revoke`,
      { method: "POST" },
    ),

  /**
   * Manually refresh OAuth token
   */
  refreshMCPOAuth: (clientKey: string) =>
    request<{ message: string; expires_at: number }>(
      `/mcp/oauth/${encodeURIComponent(clientKey)}/refresh`,
      { method: "POST" },
    ),
};
