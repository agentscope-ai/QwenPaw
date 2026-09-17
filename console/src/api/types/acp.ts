export type ACPToolParseMode = "call_title" | "update_detail" | "call_detail";

export const ACP_DEFAULT_STDIO_BUFFER_LIMIT_BYTES = 50 * 1024 * 1024;

export interface ACPAgentConfig {
  enabled: boolean;
  command: string;
  args: string[];
  env: Record<string, string>;
  trusted: boolean;
  tool_parse_mode: ACPToolParseMode;
  stdio_buffer_limit_bytes?: number;
  [key: string]: unknown;
}

export interface ACPConfig {
  node_path?: string;
  agents: Record<string, ACPAgentConfig>;
}

export interface ACPNodeRuntimeCandidate {
  key: string;
  label: string;
  node_path: string;
  npx_path: string;
  node_version: string;
  npx_version: string;
  available: boolean;
  reason_code: string;
  reason: string;
}

export interface ACPNodeRuntimeStatus {
  node_path: string;
  effective_node_path: string;
  candidates: ACPNodeRuntimeCandidate[];
}

export interface ACPNodeRuntimeUpdate {
  node_path: string;
}
