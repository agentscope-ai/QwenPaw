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
  agents: Record<string, ACPAgentConfig>;
}
