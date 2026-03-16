/**
 * MCP (Model Context Protocol) client types
 */

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
  /** Whether server requires OAuth authorization (returned 401) */
  requires_auth?: boolean;
  /** Whether OAuth is authorized */
  oauth_authorized?: boolean;
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

/** OAuth start response */
export interface MCPOAuthStartResponse {
  /** Authorization URL to redirect user */
  auth_url: string;
}

/** OAuth status response */
export interface MCPOAuthStatusResponse {
  /** Whether OAuth is authorized */
  authorized: boolean;
  /** Whether server requires OAuth (returned 401) */
  requires_auth?: boolean;
  /** Token expiration timestamp */
  expires_at?: number;
}
