import { request } from "../request";

export interface ToolConfigField {
  name: string;
  label: string;
  type: "text" | "password" | "number" | "boolean" | "select" | "textarea";
  required: boolean;
  placeholder?: string;
  help?: string;
  options?: string[];
  default?: unknown;
  min?: number;
  max?: number;
}

export interface ToolInfo {
  name: string;
  enabled: boolean;
  source_plugin_id?: string | null;
  source_plugin_name?: string | null;
  category?: string | null;
  description: string;
  summary?: string;
  detail?: string;
  input_schema?: Record<string, unknown>;
  async_execution: boolean;
  icon: string;
  requires_config?: boolean;
  config_fields?: ToolConfigField[];
  config_values?: Record<string, unknown>;
}

function withLang(path: string, lang?: string): string {
  if (!lang) return path;
  return `${path}${path.includes("?") ? "&" : "?"}lang=${encodeURIComponent(
    lang,
  )}`;
}

export const toolsApi = {
  /**
   * List all built-in tools
   */
  listTools: (agentId?: string, lang?: string) =>
    request<ToolInfo[]>(
      withLang("/tools", lang),
      agentId ? { headers: { "X-Agent-Id": agentId } } : undefined,
    ),

  /**
   * Toggle tool enabled status
   */
  toggleTool: (toolName: string, lang?: string) =>
    request<ToolInfo>(
      withLang(`/tools/${encodeURIComponent(toolName)}/toggle`, lang),
      {
        method: "PATCH",
      },
    ),

  /**
   * Update tool async_execution setting
   */
  updateAsyncExecution: (
    toolName: string,
    asyncExecution: boolean,
    lang?: string,
  ) =>
    request<ToolInfo>(
      withLang(`/tools/${encodeURIComponent(toolName)}/async-execution`, lang),
      {
        method: "PATCH",
        body: JSON.stringify({ async_execution: asyncExecution }),
      },
    ),

  /**
   * Get tool configuration
   */
  getToolConfig: (toolName: string, params?: Record<string, string>) => {
    const query = params ? `?${new URLSearchParams(params).toString()}` : "";
    return request<Record<string, unknown>>(
      `/tools/${encodeURIComponent(toolName)}/config${query}`,
    );
  },

  /**
   * Update tool configuration
   */
  updateToolConfig: (
    toolName: string,
    config: Record<string, unknown>,
    agentId?: string,
  ) =>
    request<{ status: string; message: string }>(
      `/tools/${encodeURIComponent(toolName)}/config`,
      {
        method: "POST",
        body: JSON.stringify({ config }),
        ...(agentId ? { headers: { "X-Agent-Id": agentId } } : {}),
      },
    ),
};
