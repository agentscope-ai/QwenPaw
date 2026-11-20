import { ApiRequestError, request } from "../../api/request";
import i18n from "i18next";
import {
  getAgentAccessScopeKey,
  getChatSessionScope,
  subscribeChatSessionScope,
} from "../../stores/chatSessionScope";
import { useAgentStore } from "../../stores/agentStore";
import {
  pluginInput,
  runtimePath,
  validateView,
  type PluginNode,
  type PluginRegistration,
} from "./protocol";

export class PluginWorkerClient {
  readonly pluginId: string;
  private worker: Worker;
  private controller = new AbortController();
  private stopped = false;
  private stoppedListeners = new Set<() => void>();
  getStopped = () => this.stopped;
  subscribeStopped = (listener: () => void) => {
    this.stoppedListeners.add(listener);
    return () => {
      this.stoppedListeners.delete(listener);
    };
  };
  private sequence = 0;
  private renders = new Map<
    number,
    {
      resolve: (node: PluginNode) => void;
      reject: (error: Error) => void;
      timer: ReturnType<typeof setTimeout>;
    }
  >();
  private heartbeat?: ReturnType<typeof setInterval>;
  private lastPong = performance.now();
  private error: Error | null = null;
  private requests = new Set<AbortController>();
  private resolveReady!: (items: PluginRegistration[]) => void;
  private rejectReady!: (error: Error) => void;
  private initTimer: ReturnType<typeof setTimeout>;
  private stopListener: () => void;
  readonly ready: Promise<PluginRegistration[]>;
  onStopped?: (error: Error) => void;

  constructor(pluginId: string, code: string, signal?: AbortSignal) {
    this.pluginId = pluginId;
    this.worker = new Worker(new URL("./plugin.worker.ts", import.meta.url), {
      type: "module",
    });
    this.ready = new Promise((resolve, reject) => {
      this.resolveReady = resolve;
      this.rejectReady = reject;
    });
    const abort = () => this.stop(new Error("plugin_identity_changed"));
    signal?.addEventListener("abort", abort, { once: true });
    const scope = getAgentAccessScopeKey();
    const unsubscribe = subscribeChatSessionScope(() => {
      const next = getAgentAccessScopeKey();
      if (scope === next) return;
      this.stop(new Error("plugin_identity_changed"));
    });
    this.stopListener = () => {
      signal?.removeEventListener("abort", abort);
      unsubscribe();
    };
    this.initTimer = setTimeout(
      () => this.stop(new Error("plugin_initialization_timed_out")),
      8000,
    );
    this.worker.onerror = (event) => {
      event.preventDefault();
      this.stop(new Error("plugin_execution_failed"));
    };
    this.worker.onmessageerror = () =>
      this.stop(new Error("invalid_plugin_message"));
    this.worker.onmessage = (event) => this.receive(event.data);
    if (signal?.aborted) abort();
    else
      this.worker.postMessage({
        type: "init",
        code,
        locale: i18n.language || navigator.language,
      });
  }

  private receive(message: Record<string, unknown>) {
    if (this.stopped) return;
    try {
      if (message.type === "failed") throw new Error("plugin_execution_failed");
      if (message.type === "pong") {
        this.lastPong = performance.now();
        return;
      }
      if (message.type === "ready") {
        if (this.heartbeat) throw new Error("duplicate_plugin_initialization");
        const registrations = message.registrations;
        if (!Array.isArray(registrations) || registrations.length > 50)
          throw new Error("invalid_plugin_registration");
        const ids = new Set<string>();
        const targets = new Set<string>();
        for (const item of registrations) {
          if (
            !item ||
            typeof item.id !== "string" ||
            !/^[\w.-]{1,80}$/.test(item.id) ||
            ids.has(item.id)
          )
            throw new Error("invalid_plugin_registration");
          ids.add(item.id);
          if (item.kind === "route") {
            const prefix = `/plugin/${this.pluginId}`;
            if (
              typeof item.path !== "string" ||
              !(
                item.path === prefix ||
                item.path.startsWith(prefix + "/") ||
                item.path === `/apps/${this.pluginId}`
              ) ||
              /[?#:*]|\.\./.test(item.path) ||
              typeof item.label !== "string" ||
              item.label.length > 100
            )
              throw new Error("invalid_plugin_route");
          } else if (
            item.kind !== "tool" ||
            typeof item.tool !== "string" ||
            !/^[\w.-]{1,100}$/.test(item.tool)
          ) {
            throw new Error("invalid_plugin_tool");
          }
          const target = `${item.kind}:${item.path ?? item.tool}`;
          if (targets.has(target)) throw new Error("duplicate_plugin_target");
          targets.add(target);
        }
        clearTimeout(this.initTimer);
        this.lastPong = performance.now();
        this.heartbeat = setInterval(() => {
          if (document.hidden) {
            this.lastPong = performance.now();
            return;
          }
          if (performance.now() - this.lastPong > 10000)
            this.stop(new Error("plugin_unresponsive"));
          else this.worker.postMessage({ type: "ping" });
        }, 2000);
        this.resolveReady(registrations);
      } else if (message.type === "view") {
        const pending = this.renders.get(Number(message.id));
        if (!pending) return;
        const view = validateView(message.view);
        clearTimeout(pending.timer);
        this.renders.delete(Number(message.id));
        pending.resolve(view);
      } else if (message.type === "request") {
        void this.apiRequest(message);
      }
    } catch (error) {
      this.stop(
        error instanceof Error ? error : new Error("invalid_plugin_message"),
      );
    }
  }

  private async apiRequest(message: Record<string, unknown>) {
    const scope = getAgentAccessScopeKey();
    const controller = new AbortController();
    const abort = () => controller.abort();
    try {
      if (this.requests.size >= 4) throw new Error("plugin_requests_busy");
      this.requests.add(controller);
      this.controller.signal.addEventListener("abort", abort, { once: true });
      const path = runtimePath(this.pluginId, message.path);
      const options = message.options as
        | { method?: string; body?: unknown; idempotencyKey?: string }
        | undefined;
      const method = options?.method ?? "GET";
      if (!["GET", "POST", "PUT", "PATCH", "DELETE"].includes(method))
        throw new Error("invalid_plugin_method");
      const key = options?.idempotencyKey;
      if (
        key !== undefined &&
        (typeof key !== "string" || !/^[a-zA-Z0-9._-]{1,128}$/.test(key))
      )
        throw new Error("invalid_plugin_idempotency_key");
      const body =
        options?.body === undefined ? undefined : JSON.stringify(options.body);
      if (body && body.length > 128_000)
        throw new Error("plugin_request_too_large");
      const value = await request(path, {
        method,
        signal: controller.signal,
        timeout: method === "GET" ? 8000 : 60_000,
        headers: {
          "X-Agent-Id": useAgentStore.getState().selectedAgent,
          ...(key ? { "Idempotency-Key": key } : {}),
          ...(options?.body !== undefined
            ? { "Content-Type": "application/json" }
            : {}),
        },
        ...(body !== undefined ? { body } : {}),
      });
      if (this.stopped) return;
      if (scope !== getAgentAccessScopeKey())
        throw new Error("plugin_scope_changed");
      this.worker.postMessage({ type: "response", id: message.id, value });
    } catch (error) {
      if (
        error instanceof ApiRequestError &&
        error.status === 404 &&
        /plugin_not_found|pawapp_not_found/.test(error.message)
      ) {
        this.stop(new Error("plugin_access_revoked"));
        return;
      }
      if (!this.stopped)
        this.worker.postMessage({
          type: "response",
          id: message.id,
          error: "plugin_request_failed",
        });
    } finally {
      this.controller.signal.removeEventListener("abort", abort);
      this.requests.delete(controller);
    }
  }

  render(
    target: string,
    input: unknown,
    event?: { action: string; value?: string },
  ): Promise<PluginNode> {
    if (this.stopped) return Promise.reject(this.error);
    if (this.renders.size >= 100)
      return Promise.reject(new Error("plugin_render_busy"));
    const id = ++this.sequence;
    return new Promise((resolve, reject) => {
      // The heartbeat detects a blocked event loop. A render can legitimately
      // await several sequential requests while the worker keeps answering pings.
      const timer = setTimeout(() => {
        this.renders.delete(id);
        reject(new Error("plugin_render_timed_out"));
      }, 180_000);
      this.renders.set(id, { resolve, reject, timer });
      try {
        this.worker.postMessage({
          type: "render",
          id,
          target,
          input: pluginInput(input),
          event,
          context: {
            locale: i18n.language || navigator.language,
            agentId: useAgentStore.getState().selectedAgent,
            sessionId: getChatSessionScope().sessionId,
          },
        });
      } catch {
        this.stop(new Error("invalid_plugin_input"));
      }
    });
  }

  stop(error = new Error("plugin_stopped")) {
    if (this.stopped) return;
    this.stopped = true;
    this.error = error;
    this.worker.terminate();
    this.worker.onmessage = null;
    this.worker.onerror = null;
    this.worker.onmessageerror = null;
    this.controller.abort();
    this.stopListener();
    clearTimeout(this.initTimer);
    clearInterval(this.heartbeat);
    this.rejectReady(error);
    for (const pending of this.renders.values()) {
      clearTimeout(pending.timer);
      pending.reject(error);
    }
    this.renders.clear();
    for (const listener of this.stoppedListeners) listener();
    this.stoppedListeners.clear();
    this.onStopped?.(error);
  }
}
