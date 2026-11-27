import { CONSOLE_HOST_PROTOCOL, type ConsoleHostContext } from "./context";

const HOST_TIMEOUT_MS = 15_000;

interface HostBridge {
  context: ConsoleHostContext;
  request: (path: string, body?: unknown) => Promise<unknown>;
  reload: () => Promise<unknown>;
  onUpdate?: () => void;
}

// The inline startup monitor and the Vite entry are bundled separately.
const bridgeKey = Symbol.for("qwenpaw.consoleHost");
type ConsoleWindow = Window & { [bridgeKey]?: Promise<HostBridge> };

export function consoleHostOrigin(): string | undefined {
  return document.querySelector<HTMLMetaElement>(
    'meta[name="qwenpaw-platform-origin"]',
  )?.content;
}

export function connectConsoleHost(origin: string): Promise<HostBridge> {
  const page = window as ConsoleWindow;
  return (page[bridgeKey] ??= openHostBridge(origin).catch((error) => {
    delete page[bridgeKey];
    throw error;
  }));
}

async function openHostBridge(origin: string): Promise<HostBridge> {
  origin = new URL(origin).origin;
  if (
    window.parent === window ||
    origin === "null" ||
    origin === window.location.origin
  ) {
    throw new Error("Open this Console from the Platform Web App");
  }

  return new Promise((resolve, reject) => {
    const connect = () =>
      window.parent.postMessage(
        { type: "qwenpaw:console-connect", protocol: CONSOLE_HOST_PROTOCOL },
        origin,
      );
    const timer = window.setInterval(connect, 500);
    const timeout = window.setTimeout(() => {
      cleanup();
      reject(new Error("Platform connection timed out; reload the Web App"));
    }, HOST_TIMEOUT_MS);
    const cleanup = () => {
      window.clearInterval(timer);
      window.clearTimeout(timeout);
      window.removeEventListener("message", receive);
    };
    const receive = (event: MessageEvent) => {
      if (
        event.source !== window.parent ||
        event.origin !== origin ||
        event.data?.type !== "qwenpaw:console-context" ||
        event.data.context?.protocol !== CONSOLE_HOST_PROTOCOL ||
        !event.ports[0]
      )
        return;
      cleanup();
      resolve(createHostBridge(event.data.context, event.ports[0]));
    };
    window.addEventListener("message", receive);
    connect();
  });
}

function createHostBridge(
  context: ConsoleHostContext,
  port: MessagePort,
): HostBridge {
  type Pending = {
    resolve: (value: unknown) => void;
    reject: (error: Error) => void;
    timer?: number;
  };
  const pending = new Map<number, Pending>();
  let nextId = 0;
  let reloading: Promise<unknown> | undefined;
  const request = (path: string, body?: unknown, timeout?: number) =>
    new Promise<unknown>((resolve, reject) => {
      const id = ++nextId;
      port.postMessage({ id, path, body });
      const timer = timeout
        ? window.setTimeout(() => {
            pending.delete(id);
            reject(new Error("Platform reload timed out"));
          }, timeout)
        : undefined;
      pending.set(id, { resolve, reject, timer });
    });
  const bridge: HostBridge = {
    context,
    request,
    reload: () =>
      (reloading ??= request("/host/reload", {}, HOST_TIMEOUT_MS).finally(
        () => {
          reloading = undefined;
        },
      )),
  };
  port.onmessage = ({ data }) => {
    if (data.type === "update") {
      bridge.onUpdate?.();
      return;
    }
    const result = pending.get(data.id);
    if (!result) return;
    pending.delete(data.id);
    window.clearTimeout(result.timer);
    if (data.error) result.reject(new Error(data.error));
    else result.resolve(data.value);
  };
  window.addEventListener(
    "pagehide",
    () => {
      pending.forEach(({ reject, timer }) => {
        window.clearTimeout(timer);
        reject(new Error("Console closed"));
      });
      pending.clear();
      port.close();
      const page = window as ConsoleWindow;
      delete page[bridgeKey];
    },
    { once: true },
  );
  return bridge;
}

/** Reload through the Platform host when the frame needs a fresh grant. */
export function reloadConsole(): void | Promise<unknown> {
  const origin = consoleHostOrigin();
  if (origin === undefined) {
    window.location.reload();
    return;
  }
  return connectConsoleHost(origin).then((bridge) => bridge.reload());
}

export function redactConsoleGrant(value: string): string {
  return value.replace(/(\/console-frames\/)[A-Za-z0-9_-]+/g, "$1[redacted]");
}
