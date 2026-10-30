import { request } from "../request";

export interface PawAppGrantAction {
  app_id: string;
  action_id: string;
  summary: string;
  descriptor_digest: string;
  input_schema: {
    properties?: Record<string, unknown>;
  };
  permissions: string[];
  effects: string[];
  settings_entry: string | null;
  enabled: boolean;
  stale: boolean;
  input_values: Record<string, string[]>;
}

export interface PawAppGrantCapability {
  schema_version: 1;
  capability_id: string;
  app_id: string;
  label: string;
  summary: string;
  action_ids: string[];
  permissions: string[];
  effects: string[];
  risk: "read" | "write" | "generation" | "analysis" | "other";
  enabled: boolean;
  partial: boolean;
  stale: boolean;
}

export interface PawAppHostSkillImportStatus {
  app_id: string;
  skill_id: string;
  description: string;
  tool_refs: string[];
  missing_tool_refs: string[];
  installed: boolean;
  enabled: boolean;
  available: boolean;
  status:
    | "available"
    | "disabled"
    | "not_installed"
    | "unavailable"
    | "tool_dependency_unavailable";
}

export interface PawAppGrantCatalog {
  revision: number;
  actions: PawAppGrantAction[];
  capabilities?: PawAppGrantCapability[];
  host_skill_imports?: PawAppHostSkillImportStatus[];
}

export interface PawAppGrantUpdate {
  expected_revision: number;
  enabled: boolean;
  input_values: Record<string, string[]>;
}

function catalogPath(workspaceId: string): string {
  return `/pawapps/workspaces/${encodeURIComponent(workspaceId)}/task-grants`;
}

export const pawappGrantsApi = {
  list(workspaceId: string, signal?: AbortSignal) {
    return request<PawAppGrantCatalog>(catalogPath(workspaceId), { signal });
  },

  update(
    workspaceId: string,
    appId: string,
    actionId: string,
    body: PawAppGrantUpdate,
  ) {
    return request<PawAppGrantCatalog>(
      `${catalogPath(workspaceId)}/actions/${encodeURIComponent(
        appId,
      )}/${encodeURIComponent(actionId)}`,
      {
        method: "PUT",
        body: JSON.stringify(body),
      },
    );
  },

  updateCapability(
    workspaceId: string,
    appId: string,
    capabilityId: string,
    body: Omit<PawAppGrantUpdate, "input_values">,
  ) {
    return request<PawAppGrantCatalog>(
      `${catalogPath(workspaceId)}/capabilities/${encodeURIComponent(
        appId,
      )}/${encodeURIComponent(capabilityId)}`,
      {
        method: "PUT",
        body: JSON.stringify(body),
      },
    );
  },
};
