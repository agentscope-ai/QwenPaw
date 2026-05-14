/**
 * MCP (Model Context Protocol) client types
 */

export interface MCPClientOAuthStatus {
  /** Whether a valid access token is present */
  authorized: boolean;
  /** Unix timestamp when the access token expires (0 = unknown) */
  expires_at: number;
  /** Granted OAuth scope(s) */
  scope: string;
  /** OAuth client_id used */
  client_id: string;
}

export interface MCPClientInfo {
  /** Unique client key identifier */
  key: string;
  /** Client display name */
  name: string;
  /** Client description */
  description: string;
  /** Whether the client is enabled */
  enabled: boolean;
  /** MCP transport type */
  transport: "stdio" | "streamable_http" | "sse";
  /** Remote MCP endpoint URL for HTTP/SSE transport */
  url: string;
  /** HTTP headers for remote transport */
  headers: Record<string, string>;
  /** Command to launch the MCP server */
  command: string;
  /** Command-line arguments */
  args: string[];
  /** Environment variables */
  env: Record<string, string>;
  /** Working directory for stdio command */
  cwd: string;
  /** OAuth status (null if OAuth not configured) */
  oauth_status: MCPClientOAuthStatus | null;
}

export interface MCPOAuthStartRequest {
  /** MCP server URL */
  url: string;
  /** OAuth scope(s) to request */
  scope?: string;
  /** Pre-registered client_id (leave empty to use Dynamic Client Registration) */
  client_id?: string;
  /** Override authorization endpoint (skips auto-discovery) */
  auth_endpoint?: string;
  /** Override token endpoint (skips auto-discovery) */
  token_endpoint?: string;
}

export interface MCPOAuthStartResponse {
  /** Full authorization URL to open in a popup */
  auth_url: string;
  /** State token / session ID for polling */
  session_id: string;
}

export interface MCPOAuthStatusResponse {
  authorized: boolean;
  expires_at: number;
  scope: string;
}

export interface MCPClientCreateRequest {
  /** Unique client key identifier */
  client_key: string;
  /** Client configuration */
  client: {
    /** Client display name */
    name: string;
    /** Client description */
    description?: string;
    /** Whether to enable the client */
    enabled?: boolean;
    /** MCP transport type */
    transport?: "stdio" | "streamable_http" | "sse";
    /** Remote MCP endpoint URL for HTTP/SSE transport */
    url?: string;
    /** HTTP headers for remote transport */
    headers?: Record<string, string>;
    /** Command to launch the MCP server */
    command?: string;
    /** Command-line arguments */
    args?: string[];
    /** Environment variables */
    env?: Record<string, string>;
    /** Working directory for stdio command */
    cwd?: string;
  };
}

export interface MCPToolInfo {
  /** Tool name */
  name: string;
  /** Tool description */
  description: string;
  /** JSON Schema for the tool's input parameters */
  input_schema: Record<string, unknown>;
}

export interface MCPClientUpdateRequest {
  /** Client display name */
  name?: string;
  /** Client description */
  description?: string;
  /** Whether to enable the client */
  enabled?: boolean;
  /** MCP transport type */
  transport?: "stdio" | "streamable_http" | "sse";
  /** Remote MCP endpoint URL for HTTP/SSE transport */
  url?: string;
  /** HTTP headers for remote transport */
  headers?: Record<string, string>;
  /** Command to launch the MCP server */
  command?: string;
  /** Command-line arguments */
  args?: string[];
  /** Environment variables */
  env?: Record<string, string>;
  /** Working directory for stdio command */
  cwd?: string;
}
