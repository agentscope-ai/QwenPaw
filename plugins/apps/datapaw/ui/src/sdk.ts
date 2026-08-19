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

export interface PawChatStreamEvent {
  object?: "response" | "message" | "content" | string;
  type?: string;
  id?: string;
  msg_id?: string;
  role?: string;
  status?: string;
  delta?: boolean;
  text?: string;
  content?: unknown[];
  output?: unknown[];
  data?: unknown;
  error?: unknown;
  [key: string]: unknown;
}

export interface PawChatHistoryMessage {
  id: string;
  type: string;
  role?: string | null;
  content: unknown[];
  status?: string;
  metadata?: Record<string, unknown> | null;
  [key: string]: unknown;
}

export interface PawChatHistory {
  sessionId: string;
  messages: PawChatHistoryMessage[];
}

export interface PawChatSession {
  id: string;
  sessionId: string;
  name: string;
  createdAt: string;
  updatedAt: string;
  archived: boolean;
  pinned: boolean;
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

export type PawDependencyHealthState =
  | "unknown"
  | "checking"
  | "healthy"
  | "degraded"
  | "unavailable";

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
  health: PawDependencyHealthState;
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
  chatStream(
    message: string,
    options?: {
      agentId?: string;
      sessionId?: string | null;
      skill?: string;
    },
  ): AsyncGenerator<PawChatStreamEvent>;
  getChatHistory(options?: {
    agentId?: string;
    sessionId?: string | null;
    skill?: string;
  }): Promise<PawChatHistory>;
  chatSessions: {
    list(options?: { agentId?: string }): Promise<PawChatSession[]>;
    create(options?: {
      agentId?: string;
      name?: string;
    }): Promise<PawChatSession>;
    rename(
      chatId: string,
      name: string,
      options?: { agentId?: string },
    ): Promise<PawChatSession>;
    archive(
      chatId: string,
      options?: { agentId?: string },
    ): Promise<PawChatSession>;
    pin(
      chatId: string,
      pinned: boolean,
      options?: { agentId?: string },
    ): Promise<PawChatSession>;
    delete(chatId: string, options?: { agentId?: string }): Promise<void>;
  };
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
