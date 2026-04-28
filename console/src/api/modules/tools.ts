import { request } from "../request";

export interface ToolConfigField {
  name: string;
  label: string;
  type: "text" | "password" | "number" | "select";
  required: boolean;
  placeholder?: string;
  help?: string;
  options?: Array<{ label: string; value: string }>;
}

export interface ToolInfo {
  name: string;
  enabled: boolean;
  description: string;
  async_execution: boolean;
  icon: string;
  requires_config?: boolean;
  config_fields?: ToolConfigField[];
  config_values?: Record<string, any>;
}

export const toolsApi = {
  /**
   * List all built-in tools
   */
  listTools: () => request<ToolInfo[]>("/tools"),

  /**
   * Toggle tool enabled status
   */
  toggleTool: (toolName: string) =>
    request<ToolInfo>(`/tools/${encodeURIComponent(toolName)}/toggle`, {
      method: "PATCH",
    }),

  /**
   * Update tool async_execution setting
   */
  updateAsyncExecution: (toolName: string, asyncExecution: boolean) =>
    request<ToolInfo>(
      `/tools/${encodeURIComponent(toolName)}/async-execution`,
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
