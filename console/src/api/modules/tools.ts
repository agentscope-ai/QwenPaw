import { request } from "../request";

export interface ToolConfigField {
  name: string;
  label: string;
  type: "text" | "password" | "number" | "boolean" | "select" | "textarea";
  required: boolean;
  placeholder?: string;
  help?: string;
  options?: string[];
  default?: any;
  min?: number;
  max?: number;
}

export interface ToolInfo {
  name: string;
  enabled: boolean;
  description: string;
  summary?: string;
  detail?: string;
  input_schema?: Record<string, unknown>;
  async_execution: boolean;
  icon: string;
  requires_config?: boolean;
  config_fields?: ToolConfigField[];
  config_values?: Record<string, any>;
}

function withLang(path: string, lang?: string): string {
  if (!lang) return path;
  const sep = path.includes("?") ? "&" : "?";
  return `${path}${sep}lang=${encodeURIComponent(lang)}`;
}

export const toolsApi = {
  /**
   * List all built-in tools
   */
  listTools: (lang?: string) => request<ToolInfo[]>(withLang("/tools", lang)),

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
  getToolConfig: (toolName: string) =>
    request<Record<string, any>>(
      `/tools/${encodeURIComponent(toolName)}/config`,
    ),

  /**
   * Update tool configuration
   */
  updateToolConfig: (toolName: string, config: Record<string, any>) =>
    request<{ status: string; message: string }>(
      `/tools/${encodeURIComponent(toolName)}/config`,
      {
        method: "POST",
        body: JSON.stringify({ config }),
      },
    ),
};
