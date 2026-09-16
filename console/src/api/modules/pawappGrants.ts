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

export interface PawAppGrantCatalog {
  revision: number;
  actions: PawAppGrantAction[];
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
};
