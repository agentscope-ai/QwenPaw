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

/** Parsed external agent configuration from text */
export interface ParsedExternalAgent {
  /** Whether external agent is enabled */
  enabled: boolean;
  /** Harness identifier (e.g., 'opencode', 'qwen') */
  harness: string | null;
  /** Whether to keep session alive */
  keep_session: boolean;
  /** Working directory for the agent */
  cwd: string | null;
  /** Existing session ID to resume */
  existing_session_id: string | null;
  /** Cleaned prompt text */
  prompt: string | null;
}
