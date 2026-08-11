/**
 * pawapp-sdk/types.ts — TypeScript definitions for the PawApp frontend SDK.
 */

import type React from "react";

export interface PawDisposable {
  dispose(): void;
}

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
  query?: Record<string, string | number | boolean | null | undefined>;
}

export interface PawRequestInit extends PawRequestOptions {
  method?: "GET" | "POST" | "PUT" | "PATCH" | "DELETE";
  /** JSON-encoded by the SDK. Mutually exclusive with rawBody. */
  body?: unknown;
  /** FormData, Blob, text, or another native fetch body. */
  rawBody?: BodyInit | null;
}

export interface PawSseOptions extends PawRequestOptions {
  /** GET is useful for subscriptions; POST remains the compatibility default. */
  method?: "GET" | "POST";
  /** JSON-encoded request body. GET streams cannot carry a body. */
  body?: unknown;
  /** Native request body, mutually exclusive with body. */
  rawBody?: BodyInit | null;
}

export interface PawSseEvent {
  event: string;
  data: string;
  id?: string;
  retry?: number;
}

export interface PawChatOptions {
  /** Defaults to the agent selected in the host UI. */
  agentId?: string;
  /** Defaults to the current host session, then pawapp:{appId}. */
  sessionId?: string | null;
  skill?: string;
}

/** One decoded event from the PawApp chat SSE stream. */
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

/** One host-normalized message or tool event restored from session history. */
export interface PawChatHistoryMessage {
  id: string;
  type: string;
  role?: string | null;
  content: unknown[];
  status?: string;
  metadata?: Record<string, unknown> | null;
  [key: string]: unknown;
}

/** Persisted transcript for the effective PawApp chat session. */
export interface PawChatHistory {
  sessionId: string;
  messages: PawChatHistoryMessage[];
}

/** One host-catalogued dialogue owned by a PawApp and agent. */
export interface PawChatSession {
  id: string;
  sessionId: string;
  name: string;
  createdAt: string;
  updatedAt: string;
  archived: boolean;
  pinned: boolean;
}

export interface PawChatSessionScope {
  /** Defaults to the agent selected in the host UI. */
  agentId?: string;
}

export interface PawChatSessionsApi {
  list(options?: PawChatSessionScope): Promise<PawChatSession[]>;
  create(
    options?: PawChatSessionScope & { name?: string },
  ): Promise<PawChatSession>;
  rename(
    chatId: string,
    name: string,
    options?: PawChatSessionScope,
  ): Promise<PawChatSession>;
  archive(
    chatId: string,
    options?: PawChatSessionScope,
  ): Promise<PawChatSession>;
  pin(
    chatId: string,
    pinned: boolean,
    options?: PawChatSessionScope,
  ): Promise<PawChatSession>;
  delete(chatId: string, options?: PawChatSessionScope): Promise<void>;
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
  request<T = unknown>(path: string, opts?: PawRequestInit): Promise<T>;
  post<T = unknown>(
    path: string,
    body?: unknown,
    opts?: PawRequestOptions,
  ): Promise<T>;
  get<T = unknown>(path: string, opts?: PawRequestOptions): Promise<T>;
  put<T = unknown>(
    path: string,
    body?: unknown,
    opts?: PawRequestOptions,
  ): Promise<T>;
  patch<T = unknown>(
    path: string,
    body?: unknown,
    opts?: PawRequestOptions,
  ): Promise<T>;
  delete<T = unknown>(path: string, opts?: PawRequestOptions): Promise<T>;
  download(path: string, opts?: PawRequestOptions): Promise<Blob>;
  stream(
    path: string,
    body?: unknown,
    opts?: PawRequestOptions,
  ): AsyncGenerator<string>;
  /** Standards-compliant SSE reader with event names and multiline data. */
  events(path: string, opts?: PawSseOptions): AsyncGenerator<PawSseEvent>;
  task(path: string, params?: unknown): PawTaskHandle;
}

/** Host capabilities namespace. */
export interface PawHostNamespace {
  chat(message: string, options?: PawChatOptions): Promise<string>;
  chatStream(
    message: string,
    options?: PawChatOptions,
  ): AsyncGenerator<PawChatStreamEvent>;
  getChatHistory(options?: PawChatOptions): Promise<PawChatHistory>;
  chatSessions: PawChatSessionsApi;
  storage: PawStorageApi;
  getSelectedAgentId(): string;
  getCurrentSessionId(): string | null;
  toast(
    message: string,
    kind?: "info" | "success" | "warning" | "error",
  ): Promise<void>;
  notify(title: string, body?: string): Promise<void>;
}

export interface PawPageRegistration {
  /** Defaults to /apps/{appId}. */
  path?: string;
  /** Page metadata reserved for host app discovery and navigation surfaces. */
  label: string;
  icon?: string;
  priority?: number;
  component?: React.ComponentType;
  /** Mount a standalone UI runtime without an iframe. */
  mount?: (container: HTMLElement) => void | (() => void) | PawDisposable;
}

export type PawLocalized<T> = T | ((locale: string) => T);
export type PawChatData = Record<string, unknown>;
export interface PawChatAction {
  id: string;
  icon?: React.ReactElement;
  render?: (ctx: { data: unknown }) => React.ReactElement;
  onClick?: (ctx: { data: unknown }) => void;
}
export type PawChatRequestSlot = (ctx: {
  data: PawChatData;
}) => React.ReactNode;
export type PawChatResponseSlot = (ctx: {
  data: PawChatData;
  isLast?: boolean;
}) => React.ReactNode;
export interface PawChatItemOptions {
  id?: string;
  order?: number;
}

export interface PawChatUiNamespace {
  theme: {
    set(partial: { colorPrimary?: string }): PawDisposable;
  };
  welcome: {
    set(
      partial: Partial<{
        greeting: React.ReactNode;
        description: React.ReactNode;
        avatar: string | React.ReactNode;
        nick: React.ReactNode;
        prompts: Array<{ label?: React.ReactNode; value: string }>;
      }>,
    ): PawDisposable;
    render(
      value:
        | React.ReactNode
        | ((props: {
            greeting?: React.ReactNode;
            description?: React.ReactNode;
            avatar?: string | React.ReactNode;
            prompts?: Array<{ label?: React.ReactNode; value: string }>;
            onSubmit(data: { query: string; fileList?: unknown[] }): void;
          }) => React.ReactElement),
    ): PawDisposable;
  };
  leftHeader: {
    set(
      partial: Partial<{
        logo: PawLocalized<string | React.ReactNode>;
        title: PawLocalized<React.ReactNode>;
      }>,
    ): PawDisposable;
    render(node: React.ReactNode): PawDisposable;
  };
  rightHeader: {
    add(node: React.ReactNode, opts?: PawChatItemOptions): PawDisposable;
  };
  sender: {
    set(
      partial: Partial<{
        placeholder: string;
        disclaimer: React.ReactNode;
      }>,
    ): PawDisposable;
    addPrefix(node: React.ReactNode, opts?: PawChatItemOptions): PawDisposable;
    addSuggestion(item: {
      id?: string;
      items: PawLocalized<Array<{ label?: React.ReactNode; value: string }>>;
    }): PawDisposable;
  };
  actions: { add(action: PawChatAction): PawDisposable };
  requestActions: { add(action: PawChatAction): PawDisposable };
  requestPayload: {
    add(
      transform: (ctx: {
        payload: Record<string, unknown>;
        sessionId: string;
        selectedAgent: string;
      }) => Record<string, unknown> | void,
      opts?: PawChatItemOptions,
    ): PawDisposable;
  };
  request: {
    render(
      render: (ctx: {
        data: PawChatData;
        fallback: () => React.ReactElement;
      }) => React.ReactNode,
    ): PawDisposable;
    prepend(
      render: PawChatRequestSlot,
      opts?: PawChatItemOptions,
    ): PawDisposable;
    append(
      render: PawChatRequestSlot,
      opts?: PawChatItemOptions,
    ): PawDisposable;
  };
  response: {
    set(
      partial: Partial<{
        avatar: PawLocalized<string | React.ReactNode>;
        nick: PawLocalized<React.ReactNode>;
      }>,
    ): PawDisposable;
    render(
      render: (ctx: {
        data: PawChatData;
        isLast?: boolean;
        fallback: () => React.ReactElement;
      }) => React.ReactNode,
    ): PawDisposable;
    prepend(
      render: PawChatResponseSlot,
      opts?: PawChatItemOptions,
    ): PawDisposable;
    append(
      render: PawChatResponseSlot,
      opts?: PawChatItemOptions,
    ): PawDisposable;
  };
  toolRender(
    toolName: string,
    render: React.FC<Record<string, unknown>>,
  ): PawDisposable;
  approvalRender(
    sourceType: string,
    render: React.FC<Record<string, unknown>>,
  ): PawDisposable;
  card(
    cardName: string,
    render: React.FC<Record<string, unknown>>,
  ): PawDisposable;
  disposeAll(): void;
}

export interface PawUiNamespace {
  registerPage(registration: PawPageRegistration): PawDisposable;
  chat: PawChatUiNamespace;
}

export type PawDependencyOwnership =
  | "host_managed"
  | "app_managed"
  | "external";
export type PawDependencyLifecycleState =
  | "unknown"
  | "not_installed"
  | "stopped"
  | "starting"
  | "running"
  | "stopping"
  | "failed"
  | "unmanaged";
export type PawDependencyHealthState =
  | "unknown"
  | "checking"
  | "healthy"
  | "degraded"
  | "unavailable";
export type PawDependencyAction =
  | "check"
  | "start"
  | "stop"
  | "restart"
  | "provision";

export interface PawDependencyStatus {
  id: string;
  display_name: string;
  ownership: PawDependencyOwnership;
  required: boolean;
  lifecycle: PawDependencyLifecycleState;
  health: PawDependencyHealthState;
  error_code: string | null;
  message: string;
  remediation: string | null;
  capabilities: string[];
  actions: PawDependencyAction[];
  last_checked_at: string;
  latency_ms: number | null;
}

export interface PawCapabilityStatus {
  id: string;
  health: PawDependencyHealthState;
  dependencies: string[];
}

export interface PawDependencySnapshot {
  schema_version: "1" | string;
  app_id: string;
  summary: PawDependencyHealthState;
  dependencies: PawDependencyStatus[];
  capabilities: PawCapabilityStatus[];
}

export interface PawDependenciesNamespace {
  list(force?: boolean): Promise<PawDependencySnapshot>;
  get(dependencyId: string, force?: boolean): Promise<PawDependencyStatus>;
  check(dependencyId: string): Promise<PawDependencyStatus>;
  action(
    dependencyId: string,
    action: Exclude<PawDependencyAction, "check">,
    options?: { idempotencyKey?: string },
  ): Promise<PawDependencyStatus>;
  subscribe(
    listener: (snapshot: PawDependencySnapshot) => void,
    options?: { intervalMs?: number; force?: boolean },
  ): PawDisposable;
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
  readonly appId: string;
  api: PawApiNamespace;
  host: PawHostNamespace;
  ui: PawUiNamespace;
  dependencies: PawDependenciesNamespace;
  chat(message: string, options?: PawChatOptions): Promise<string>;
  chatStream(
    message: string,
    options?: PawChatOptions,
  ): AsyncGenerator<PawChatStreamEvent>;
  getChatHistory(options?: PawChatOptions): Promise<PawChatHistory>;
  chatSessions: PawChatSessionsApi;
  storage: PawStorageApi;
  toast(
    message: string,
    kind?: "info" | "success" | "warning" | "error",
  ): Promise<void>;
  notify(title: string, body?: string): Promise<void>;
}

export interface PawSdkFactory {
  forApp(appId: string): PawSdk;
}
