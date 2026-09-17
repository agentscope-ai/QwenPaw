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
  async_execution: boolean;
  icon: string;
  requires_config?: boolean;
  config_fields?: ToolConfigField[];
  config_values?: Record<string, any>;
  credential_status?: Record<string, "missing" | "configured" | "revoked">;
  can_edit?: boolean;
  policy_locked?: boolean;
  policy_reason?: string | null;
}

export interface ToolCredentialAction {
  action: "keep" | "replace" | "delete";
  value?: string;
}

export interface ToolConfigView {
  config: Record<string, unknown>;
  credential_status: Record<string, "missing" | "configured" | "revoked">;
}

export interface ToolConfigUpdate {
  config: Record<string, unknown>;
  credential_updates: Record<string, ToolCredentialAction>;
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
    request<ToolConfigView>(`/tools/${encodeURIComponent(toolName)}/config`),

  /**
   * Update tool configuration
   */
  updateToolConfig: (toolName: string, body: ToolConfigUpdate) =>
    request<{ status: string; message: string }>(
      `/tools/${encodeURIComponent(toolName)}/config`,
      {
        method: "POST",
        body: JSON.stringify(body),
      },
    ),
};
