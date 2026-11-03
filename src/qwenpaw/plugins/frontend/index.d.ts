export * from "./host.js";
export * from "./paw.js";
import type { QwenPawWindowNamespace } from "./host.js";
import type { PawSdk, PawRequestOptions } from "./paw.js";
export declare const SDK_VERSION: "1.0.0";
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
