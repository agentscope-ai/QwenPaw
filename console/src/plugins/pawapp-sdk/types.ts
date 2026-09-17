/**
 * pawapp-sdk/types.ts — TypeScript definitions for the PawApp frontend SDK.
 */

/** Response from a backend API call. */
export interface PawApiResponse<T = unknown> {
  data: T;
  status: number;
  ok: boolean;
}

/** Options for API requests. */
export interface PawRequestOptions {
  headers?: Record<string, string>;
  signal?: AbortSignal;
}

/** PawTask event handler. */
export type PawTaskEventHandler<T = unknown> = (data: T) => void;

/** PawTask events. */
export interface PawTaskEvents {
  progress: { step: number; total?: number; message?: string };
  done: { result: unknown };
  error: { message: string; code?: string };
  [key: string]: unknown;
}

/** Storage interface for PawApps. */
export interface PawStorageApi {
  get<T = unknown>(key: string, defaultValue?: T): Promise<T>;
  set(key: string, value: unknown): Promise<void>;
  delete(key: string): Promise<void>;
  keys(): Promise<string[]>;
}

/** API namespace for backend communication. */
export interface PawApiNamespace {
  post<T = unknown>(
    path: string,
    body?: unknown,
    opts?: PawRequestOptions,
  ): Promise<T>;
  get<T = unknown>(path: string, opts?: PawRequestOptions): Promise<T>;
  stream(
    path: string,
    body?: unknown,
    opts?: PawRequestOptions,
  ): AsyncGenerator<string>;
  task(path: string, params?: unknown): PawTaskHandle;
}

/** Host capabilities namespace. */
export interface PawHostNamespace {
  chat(message: string): Promise<string>;
  storage: PawStorageApi;
  toast(
    message: string,
    kind?: "info" | "success" | "warning" | "error",
  ): Promise<void>;
  notify(title: string, body?: string): Promise<void>;
}

/** Handle to a running PawTask. */
export interface PawTaskHandle {
  on<K extends string>(event: K, handler: PawTaskEventHandler): PawTaskHandle;
  off(event: string, handler: PawTaskEventHandler): PawTaskHandle;
  cancel(): void;
  readonly result: Promise<unknown>;
  readonly taskId: string;
}

/** The top-level paw SDK object. */
export interface PawSdk {
  api: PawApiNamespace;
  host: PawHostNamespace;
  chat(message: string): Promise<string>;
  storage: PawStorageApi;
  toast(
    message: string,
    kind?: "info" | "success" | "warning" | "error",
  ): Promise<void>;
  notify(title: string, body?: string): Promise<void>;
}
