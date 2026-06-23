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

export type MCPAccessEffect = "allow" | "ask" | "deny";

export interface MCPAccessSummary {
  default_effect: MCPAccessEffect;
  overrides_count: number;
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
  /** Tool whitelist (null means all tools enabled) */
  tools: string[] | null;
  /** OAuth status (null if OAuth not configured) */
  oauth_status: MCPClientOAuthStatus | null;
  /** Summarised MCP access policy */
  access_summary: MCPAccessSummary;
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
  /** Whether this tool is enabled (passes the whitelist) */
  enabled: boolean;
  /** JSON Schema for the tool's input parameters */
  input_schema: Record<string, unknown>;
}

export type MCPAccessSourceType = "channel" | (string & {});
export type MCPAccessSubjectType = "all" | "user";

export interface MCPAccessRule {
  /** Where the tool call comes from */
  source_type: MCPAccessSourceType;
  /** Concrete source, e.g. console, dingtalk */
  source_value: string;
  /** Object scope within the source */
  subject_type: MCPAccessSubjectType;
  /** Concrete object value when subject_type is user */
  subject_value: string;
  /** Access effect for this tool */
  effect: MCPAccessEffect;
}

export interface MCPToolDefaultPolicy {
  /** MCP tool name */
  tool_name: string;
  /** Default effect for this tool */
  effect: MCPAccessEffect;
}

export interface MCPToolAccessOverride extends MCPAccessRule {
  /** MCP tool name */
  tool_name: string;
}

export interface MCPAccessPolicy {
  /** Default effect when no MCP rule matches */
  default_effect: MCPAccessEffect;
  /** Console-managed MCP-wide source/object overrides */
  client_overrides: MCPAccessRule[];
  /** Console-managed default effects for individual tools */
  tool_defaults: MCPToolDefaultPolicy[];
  /** Console-managed per-source/per-object/per-tool overrides */
  tool_overrides: MCPToolAccessOverride[];
  /** Preserved rules not editable from the MCP console */
  unmanaged_rules_count: number;
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
