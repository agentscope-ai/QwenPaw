export interface StatusConfigItem {
  /** i18n key for the status label */
  label: string;
  /** Unicode icon character */
  icon: string;
  /** CSS class name key (resolved by consumer via styles[config.className]) */
  className: string;
}

/**
 * Status configuration map.
 * Maps each NodeStatus to its display config (i18n label key, icon, className key).
 */
export const statusConfig: Record<string, StatusConfigItem> = {
  done: {
    label: 'taskGraph.statusDone',
    icon: '✓',
    className: 'statusDone',
  },
  in_progress: {
    label: 'taskGraph.statusInProgress',
    icon: '◐',
    className: 'statusInProgress',
  },
  pending: {
    label: 'taskGraph.statusPending',
    icon: '◷',
    className: 'statusPending',
  },
  todo: {
    label: 'taskGraph.statusTodo',
    icon: '○',
    className: 'statusNotStarted',
  },
  not_started: {
    label: 'taskGraph.statusTodo',
    icon: '○',
    className: 'statusNotStarted',
  },
  failed: {
    label: 'taskGraph.statusFailed',
    icon: '✗',
    className: 'statusFailed',
  },
  stale: {
    label: 'taskGraph.statusStale',
    icon: '⧖',
    className: 'statusStale',
  },
  abandoned: {
    label: 'taskGraph.statusAbandoned',
    icon: '⌀',
    className: 'statusAbandoned',
  },
};

/** Default fallback config for unknown statuses */
const defaultConfig: StatusConfigItem = statusConfig.not_started;

/**
 * Safely retrieve status config by status string.
 * Falls back to not_started config for unknown statuses.
 */
export function getStatusConfig(status: string): StatusConfigItem {
  return statusConfig[status] || defaultConfig;
}

/**
 * Determine whether a node with the given status is clickable (can open detail drawer).
 * Only 'done' and 'in_progress' statuses are clickable.
 */
export function isClickable(status: string): boolean {
  return status === 'done' || status === 'in_progress';
}
