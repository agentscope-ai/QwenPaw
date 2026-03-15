/**
 * ACP (Agent Client Protocol) types
 */

/** Configuration for a single ACP harness */
export interface ACPHarnessConfig {
  /** Whether this harness is enabled */
  enabled: boolean;
  /** Command to launch the harness */
  command: string;
  /** Arguments for the command */
  args: string[];
  /** Environment variables for the harness process */
  env: Record<string, string>;
}

/** ACP (Agent Client Protocol) configuration */
export interface ACPConfig {
  /** Global switch to enable/disable ACP functionality */
  enabled: boolean;
  /** Whether to require user approval before executing ACP tasks */
  require_approval: boolean;
  /** Directory to save ACP session states */
  save_dir: string;
  /** Available ACP harnesses */
  harnesses: Record<string, ACPHarnessConfig>;
}

/** Harness info with key for UI display */
export interface ACPHarnessInfo extends ACPHarnessConfig {
  /** Unique harness key identifier */
  key: string;
  /** Harness display name */
  name: string;
}
