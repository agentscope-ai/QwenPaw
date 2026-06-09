export interface StatusConfigItem {
  labelKey: string;
  className: string;
}

export const statusConfig: Record<string, StatusConfigItem> = {
  done: { labelKey: "statusDone", className: "statusDone" },
  in_progress: { labelKey: "statusInProgress", className: "statusInProgress" },
  pending: { labelKey: "statusPending", className: "statusPending" },
  todo: { labelKey: "statusTodo", className: "statusNotStarted" },
  not_started: { labelKey: "statusTodo", className: "statusNotStarted" },
  failed: { labelKey: "statusFailed", className: "statusFailed" },
  stale: { labelKey: "statusStale", className: "statusStale" },
  abandoned: { labelKey: "statusAbandoned", className: "statusAbandoned" },
};

const defaultConfig = statusConfig.not_started;

export function getStatusConfig(status: string): StatusConfigItem {
  return statusConfig[status] || defaultConfig;
}

export function isClickable(status: string): boolean {
  return status === "done" || status === "in_progress";
}
