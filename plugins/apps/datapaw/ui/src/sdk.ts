export interface PawDisposable {
  dispose(): void;
}

export interface PawRequestOptions {
  headers?: Record<string, string>;
  signal?: AbortSignal;
  query?: Record<string, string | number | boolean | null | undefined>;
}

export interface PawSseEvent {
  event: string;
  data: string;
  id?: string;
  retry?: number;
}

export interface PawApi {
  get<T>(path: string, options?: PawRequestOptions): Promise<T>;
  post<T>(
    path: string,
    body?: unknown,
    options?: PawRequestOptions,
  ): Promise<T>;
  put<T>(path: string, body?: unknown, options?: PawRequestOptions): Promise<T>;
  patch<T>(
    path: string,
    body?: unknown,
    options?: PawRequestOptions,
  ): Promise<T>;
  delete<T>(path: string, options?: PawRequestOptions): Promise<T>;
  download(path: string, options?: PawRequestOptions): Promise<Blob>;
  events(
    path: string,
    options?: PawRequestOptions & {
      method?: "GET" | "POST";
      body?: unknown;
      rawBody?: BodyInit | null;
    },
  ): AsyncGenerator<PawSseEvent>;
}

export type PawDependencyAction =
  | "check"
  | "start"
  | "stop"
  | "restart"
  | "provision";

export interface PawDependencyStatus {
  id: string;
  display_name: string;
  ownership: "host_managed" | "app_managed" | "external";
  required: boolean;
  lifecycle:
    | "unknown"
    | "not_installed"
    | "stopped"
    | "starting"
    | "running"
    | "stopping"
    | "failed"
    | "unmanaged";
  health: "unknown" | "checking" | "healthy" | "degraded" | "unavailable";
  error_code: string | null;
  message: string;
  remediation: string | null;
  capabilities: string[];
  actions: PawDependencyAction[];
  last_checked_at: string;
  latency_ms: number | null;
}

export interface PawDependencySnapshot {
  schema_version: string;
  app_id: string;
  summary: "unknown" | "checking" | "healthy" | "degraded" | "unavailable";
  dependencies: PawDependencyStatus[];
  capabilities: Array<{
    id: string;
    health: PawDependencyStatus["health"];
    dependencies: string[];
  }>;
}

export interface PawAppSdk {
  readonly appId: string;
  api: PawApi;
  dependencies: {
    list(force?: boolean): Promise<PawDependencySnapshot>;
    get(id: string, force?: boolean): Promise<PawDependencyStatus>;
    check(id: string): Promise<PawDependencyStatus>;
    action(
      id: string,
      action: Exclude<PawDependencyAction, "check">,
      options?: { idempotencyKey?: string },
    ): Promise<PawDependencyStatus>;
    subscribe(
      listener: (snapshot: PawDependencySnapshot) => void,
      options?: { intervalMs?: number; force?: boolean },
    ): PawDisposable;
  };
  chat(
    message: string,
    options?: {
      agentId?: string;
      sessionId?: string | null;
      skill?: string;
    },
  ): Promise<string>;
  storage: {
    get<T>(key: string, fallback?: T): Promise<T>;
    set(key: string, value: unknown): Promise<void>;
    delete(key: string): Promise<void>;
    keys(): Promise<string[]>;
  };
  toast(
    message: string,
    kind?: "info" | "success" | "warning" | "error",
  ): Promise<void>;
  ui: {
    registerPage(registration: {
      path?: string;
      label: string;
      icon?: string;
      priority?: number;
      mount(container: HTMLElement): void | (() => void) | PawDisposable;
    }): PawDisposable;
  };
}

declare global {
  interface Window {
    QwenPaw?: {
      paw?: {
        forApp(appId: string): PawAppSdk;
      };
    };
  }
}

export function requireQwenPawDataSdk(): PawAppSdk {
  const factory = window.QwenPaw?.paw;
  if (!factory) {
    throw new Error(
      "This QwenPaw-Data build requires the app-scoped PawApp SDK",
    );
  }
  return factory.forApp("datapaw");
}
