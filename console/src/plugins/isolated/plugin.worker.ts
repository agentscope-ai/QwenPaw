import {
  validateView,
  type PluginNode,
  type PluginRegistration,
} from "./protocol";

type Render = (
  input: unknown,
  event?: { action: string; value?: string },
  context?: { agentId: string; sessionId: string },
) => PluginNode | Promise<PluginNode>;
const port = self as unknown as {
  onmessage: ((event: MessageEvent) => void) | null;
  postMessage: (message: unknown) => void;
};
const renderers = new Map<string, Render>();
const registrations: PluginRegistration[] = [];
const requests = new Map<
  number,
  { resolve: (value: unknown) => void; reject: (error: Error) => void }
>();
let initialized = false;
let sealed = false;
let requestId = 0;
let locale = "en";

type Definition = Omit<PluginRegistration, "kind"> & { render: Render };
const register = (kind: "route" | "tool", config: Definition) => {
  if (
    sealed ||
    registrations.length >= 50 ||
    !config.id ||
    renderers.has(config.id) ||
    typeof config.render !== "function"
  )
    throw new Error("invalid_plugin_registration");
  renderers.set(config.id, config.render);
  registrations.push({
    id: config.id,
    kind,
    path: config.path,
    label: config.label,
    tool: config.tool,
  });
};

Object.defineProperty(globalThis, "QwenPawWorker", {
  value: Object.freeze({
    version: "worker-v1",
    t: (zh: string, en: string) =>
      locale.toLowerCase().startsWith("zh") ? zh : en,
    registerRoute: (config: Definition) => register("route", config),
    registerTool: (config: Definition) => register("tool", config),
    request: (
      path: string,
      options?: { method?: string; body?: unknown; idempotencyKey?: string },
    ) =>
      new Promise((resolve, reject) => {
        if (requests.size >= 4) {
          reject(new Error("plugin_requests_busy"));
          return;
        }
        const id = ++requestId;
        requests.set(id, { resolve, reject });
        port.postMessage({ type: "request", id, path, options });
      }),
  }),
});

port.onmessage = (event) => {
  const message = event.data;
  if (message.type === "ping") {
    port.postMessage({ type: "pong" });
    return;
  }
  if (message.type === "response") {
    const pending = requests.get(message.id);
    requests.delete(message.id);
    if (message.error) pending?.reject(new Error(message.error));
    else pending?.resolve(message.value);
    return;
  }
  if (message.type === "init" && !initialized) {
    initialized = true;
    locale = message.locale || "en";
    const url = URL.createObjectURL(
      new Blob([message.code], { type: "application/javascript" }),
    );
    void import(/* @vite-ignore */ url)
      .then(() => {
        sealed = true;
        port.postMessage({ type: "ready", registrations });
      })
      .catch((error) =>
        port.postMessage({ type: "failed", error: String(error) }),
      )
      .finally(() => URL.revokeObjectURL(url));
    return;
  }
  if (message.type === "render" && sealed) {
    locale = message.context?.locale || locale;
    void Promise.resolve()
      .then(() => {
        const render = renderers.get(message.target);
        if (!render) throw new Error("plugin_view_not_found");
        return render(message.input, message.event, message.context);
      })
      .then((view) =>
        port.postMessage({
          type: "view",
          id: message.id,
          view: validateView(view),
        }),
      )
      .catch((error) =>
        port.postMessage({ type: "failed", error: String(error) }),
      );
  }
};
