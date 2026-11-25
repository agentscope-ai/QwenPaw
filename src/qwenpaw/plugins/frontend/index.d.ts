export * from "./host.js";
export * from "./paw.js";
import type { QwenPawWindowNamespace } from "./host.js";
import type { PawSdk, PawRequestOptions } from "./paw.js";
export declare const SDK_VERSION: "1.2.0";
/** Harness settings types are available since SDK 1.1.0. */
export type { HarnessSettingsProps, HarnessFrontendExtension } from "./host.js";
/** Features of this library, not a claim about the currently running backend. */
export declare const SDK_CAPABILITIES: readonly string[];
export interface AppCapabilities {
  status: "supported" | "unsupported" | "unknown";
  sdk_version: string | null;
  app_id: string;
  capabilities: string[];
}
export declare function capabilities(
  appId: string,
  options?: PawRequestOptions,
): Promise<AppCapabilities>;
export declare function getHost(): QwenPawWindowNamespace;
export declare function forApp(appId: string): PawSdk;
export interface ChatRequest {
  message: string;
  session_id?: string;
  skill?: string;
  request_id?: string;
}
export interface TaskSnapshot {
  run_id: string;
  session_id: string;
  workspace_id: string;
  app_id: string;
  status:
    | "running"
    | "completed"
    | "cancelled"
    | "failed"
    | "interrupted"
    | "idle";
  error: string;
  result: string;
  result_truncated: boolean;
}
export interface CancelResult {
  requested: boolean;
  stopped: boolean;
  timed_out: boolean;
}
export interface AppTasks {
  start(
    request: ChatRequest,
    options?: PawRequestOptions,
  ): Promise<TaskSnapshot>;
  get(runId: string, options?: PawRequestOptions): Promise<TaskSnapshot>;
  /** Status changes only; reconnect yields current status. Full output is in chat history. */
  stream(
    runId: string,
    options?: PawRequestOptions,
  ): AsyncGenerator<TaskSnapshot>;
  cancel(runId: string, options?: PawRequestOptions): Promise<CancelResult>;
}
export declare function tasks(appId: string): AppTasks;

/** @since 1.2.0 An explicitly selected main conversation in this workspace. */
export interface CheckpointScope extends PawRequestOptions {
  chatId: string;
  agentId: string;
}
/** @since 1.2.0 */
export interface CheckpointEntry {
  id: string;
  kind: string;
  name: string;
  timestamp_ms: number;
  description: string;
  is_current: boolean;
}
/** @since 1.2.0 */
export interface SnapshotResult {
  id: string;
  timestamp_ms: number;
}
/** @since 1.2.0 */
export interface RestoreOptions extends CheckpointScope {
  include_memory?: boolean;
  include_files?: boolean;
  files?: string[];
}
/** @since 1.2.0 */
export interface RestoreResult {
  id: string;
  dry_run: boolean;
  restored_paths: string[];
  deleted_paths: string[];
  file_paths: string[];
  include_memory: boolean;
  include_files: boolean;
}
/** @since 1.2.0 */
export interface CheckpointClient {
  timeline(
    options: CheckpointScope & { limit?: number },
  ): Promise<CheckpointEntry[]>;
  snapshot(name: string, options: CheckpointScope): Promise<SnapshotResult>;
  previewRestore(
    target: string,
    options: RestoreOptions,
  ): Promise<RestoreResult>;
  /** Waits for native host confirmation; abort cancels a pending request. */
  restore(target: string, options: RestoreOptions): Promise<RestoreResult>;
}
/** @since 1.2.0 Requires the app's standard checkpoint capability. */
export declare function checkpoints(appId: string): CheckpointClient;
