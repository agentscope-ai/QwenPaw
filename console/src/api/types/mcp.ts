/**
 * MCP (Model Context Protocol) client types
 */

/** Transport mode for MCP clients */
export type MCPTransport = "stdio" | "sse" | "streamable_http";

export interface MCPClientInfo {
  /** Unique client key identifier */
  key: string;
  /** Client display name */
  name: string;
  /** Client description */
  description: string;
  /** Whether the client is enabled */
  enabled: boolean;
  /** Transport mode */
  transport: MCPTransport;
  /** Command to launch the MCP server (stdio) */
  command: string;
  /** Command-line arguments (stdio) */
  args: string[];
  /** Environment variables (stdio) */
  env: Record<string, string>;
  /** Server URL (sse / streamable_http) */
  url: string;
  /** HTTP headers (sse / streamable_http) */
  headers: Record<string, string>;
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
    /** Transport mode */
    transport?: MCPTransport;
    /** Command to launch the MCP server (stdio) */
    command?: string;
    /** Command-line arguments (stdio) */
    args?: string[];
    /** Environment variables (stdio) */
    env?: Record<string, string>;
    /** Server URL (sse / streamable_http) */
    url?: string;
    /** HTTP headers (sse / streamable_http) */
    headers?: Record<string, string>;
  };
}

export interface MCPClientUpdateRequest {
  /** Client display name */
  name?: string;
  /** Client description */
  description?: string;
  /** Whether to enable the client */
  enabled?: boolean;
  /** Transport mode */
  transport?: MCPTransport;
  /** Command to launch the MCP server (stdio) */
  command?: string;
  /** Command-line arguments (stdio) */
  args?: string[];
  /** Environment variables (stdio) */
  env?: Record<string, string>;
  /** Server URL (sse / streamable_http) */
  url?: string;
  /** HTTP headers (sse / streamable_http) */
  headers?: Record<string, string>;
}
