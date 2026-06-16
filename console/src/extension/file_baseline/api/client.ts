import { request } from "@/api/request";
import { getApiUrl } from "@/api/config";

export interface FileBaselineProtectionSettings {
  enabled: boolean;
  pilot_mode: boolean;
  protected_targets: string[];
  protected_paths: string[];
  baseline_established: boolean;
  baseline_cleared_at?: string | null;
  open_alert_count: number;
  scan_status?: string | null;
  last_scan_at?: string | null;
  last_scan_drift_count?: number | null;
}

export interface FileBaselineProtectionAlert {
  alert_id: string;
  agent_id: string;
  path: string;
  approved_sha256: string;
  current_sha256: string;
  provenance: string;
  status: string;
  detected_at: string;
  patch_path?: string | null;
}

export interface FileBaselineProtectionAlertsResponse {
  enabled: boolean;
  scanning: boolean;
  alerts: FileBaselineProtectionAlert[];
  open_alert_count: number;
}

export interface FileBaselineProtectionActionResponse {
  confirmed: boolean;
  message?: string;
  alert_id?: string;
  action?: string;
}

export interface FileBaselineProtectionSettingsUpdateBody {
  enabled?: boolean;
  protected_targets?: string[];
  confirmation_phrase?: string;
}

export interface FileBaselineWorkspaceBrowseEntry {
  name: string;
  type: "dir" | "file";
  rel_path: string;
  size?: number;
}

export interface FileBaselineWorkspaceBrowseResponse {
  agent_id: string;
  workspace_label: string;
  current_path: string;
  parent_path: string;
  default_path: string;
  entries: FileBaselineWorkspaceBrowseEntry[];
}

export const fileBaselineApi = {
  getFileBaselineProtectionSettings: () =>
    request<FileBaselineProtectionSettings>(
      "/config/security/file-baseline/settings",
    ),

  updateFileBaselineProtectionSettings: (body: FileBaselineProtectionSettingsUpdateBody) =>
    request<FileBaselineProtectionSettings>(
      "/config/security/file-baseline/settings",
      {
        method: "PUT",
        body: JSON.stringify(body),
      },
    ),

  getFileBaselineProtectionAlerts: () =>
    request<FileBaselineProtectionAlertsResponse>(
      "/config/security/file-baseline/alerts",
    ),

  restoreFileBaselineProtectionAlert: (alertId: string, confirmationPhrase: string) =>
    request<FileBaselineProtectionActionResponse>(
      "/config/security/file-baseline/restore",
      {
        method: "POST",
        body: JSON.stringify({
          alert_id: alertId,
          confirmation_phrase: confirmationPhrase,
        }),
      },
    ),

  acceptFileBaselineProtectionAlert: (alertId: string, confirmationPhrase: string) =>
    request<FileBaselineProtectionActionResponse>(
      "/config/security/file-baseline/accept",
      {
        method: "POST",
        body: JSON.stringify({
          alert_id: alertId,
          confirmation_phrase: confirmationPhrase,
        }),
      },
    ),

  getFileBaselineProtectionWatchUrl: () =>
    getApiUrl("/config/security/file-baseline/watch"),

  browseWorkspaceProtectableFiles: (path = "skills") =>
    request<FileBaselineWorkspaceBrowseResponse>(
      `/config/security/file-baseline/browse?path=${encodeURIComponent(path)}`,
    ),
};
