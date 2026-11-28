import { CONSOLE_HOST_PROTOCOL, type ConsoleHostContext } from "./context";

const HOST_TIMEOUT_MS = 15_000;

interface HostBridge {
  context: ConsoleHostContext;
  request: (path: string, body?: unknown) => Promise<unknown>;
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

export function consoleHostRoute(context: ConsoleHostContext): string {
  const { pathname, search, hash } = window.location;
  const current = pathname.startsWith(context.basename)
    ? pathname.slice(context.basename.length)
    : "";
  const requested =
    current && current !== "/index.html"
      ? current + search + hash
      : context.route;
  return requested.startsWith("/") && !requested.startsWith("//")
    ? requested
    : "/chat";
}

export function connectConsoleHost(origin: string): Promise<HostBridge> {
  const page = window as ConsoleWindow;
  if (page[bridgeKey]) return page[bridgeKey];
  const forget = () => {
    if (page[bridgeKey] === connection) delete page[bridgeKey];
  };
  const connection = openHostBridge(origin, forget).catch((error) => {
    forget();
    throw error;
  });
  page[bridgeKey] = connection;
  return connection;
}

async function openHostBridge(
  origin: string,
  forget: () => void,
): Promise<HostBridge> {
  origin = new URL(origin).origin;
  if (
    window.parent === window ||
    origin === "null" ||
    origin === window.location.origin
  ) {
    throw new Error("Open this Console from the Platform Web App");
  }

  return new Promise((resolve, reject) => {
    const connect = () => {
      try {
        window.parent.postMessage(
          { type: "qwenpaw:console-connect", protocol: CONSOLE_HOST_PROTOCOL },
          origin,
        );
      } catch (error) {
        cleanup();
        reject(error);
      }
    };
    const timer = window.setInterval(connect, 500);
    const timeout = window.setTimeout(() => {
      cleanup();
      reject(new Error("Platform connection timed out; reload the Web App"));
    }, HOST_TIMEOUT_MS);
    const cleanup = () => {
      window.clearInterval(timer);
      window.clearTimeout(timeout);
      window.removeEventListener("message", receive);
      window.removeEventListener("pagehide", onPageHide);
    };
    const onPageHide = () => {
      cleanup();
      reject(new Error("Console closed"));
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
      resolve(createHostBridge(event.data.context, event.ports[0], forget));
    };
    window.addEventListener("message", receive);
    window.addEventListener("pagehide", onPageHide);
    connect();
  });
}

function createHostBridge(
  context: ConsoleHostContext,
  port: MessagePort,
  forget: () => void,
): HostBridge {
  type Pending = {
    resolve: (value: unknown) => void;
    reject: (error: Error) => void;
    timer: number;
  };
  const pending = new Map<number, Pending>();
  let nextId = 0;
  let reloading: Promise<unknown> | undefined;
  let closed: Error | undefined;
  function dispose(error: Error) {
    if (closed) return;
    closed = error;
    forget();
    window.removeEventListener("pagehide", onPageHide);
    port.removeEventListener("close", onPortClose);
    port.onmessage = port.onmessageerror = null;
    port.close();
    for (const { reject, timer } of pending.values()) {
      window.clearTimeout(timer);
      reject(error);
    }
    pending.clear();
  }
  const onPageHide = () => dispose(new Error("Console closed"));
  const onPortClose = () => dispose(new Error("Platform connection closed"));
  const send = (path: string, body?: unknown) =>
    new Promise<unknown>((resolve, reject) => {
      if (closed) {
        reject(closed);
        return;
      }
      const id = ++nextId;
      const timer = window.setTimeout(
        () => dispose(new Error("Platform request timed out")),
        HOST_TIMEOUT_MS,
      );
      pending.set(id, { resolve, reject, timer });
      try {
        port.postMessage({ id, path, body });
      } catch (error) {
        if (error instanceof DOMException && error.name === "DataCloneError") {
          pending.delete(id);
          window.clearTimeout(timer);
          reject(error);
        } else {
          onPortClose();
        }
      }
    });
  const bridge: HostBridge = {
    context,
    request(path, body) {
      if (path !== "/host/reload") return send(path, body);
      if (!reloading) {
        void send("/host/navigation", {
          route: consoleHostRoute(context),
        }).catch(() => undefined);
        reloading = send(path, body).finally(() => {
          reloading = undefined;
        });
      }
      return reloading;
    },
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
  port.onmessageerror = onPortClose;
  port.addEventListener("close", onPortClose);
  window.addEventListener("pagehide", onPageHide);
  return bridge;
}

/** Reload through the Platform host when the frame needs a fresh grant. */
export function reloadConsole(): void | Promise<unknown> {
  const origin = consoleHostOrigin();
  if (origin === undefined) {
    window.location.reload();
    return;
  }
  return connectConsoleHost(origin).then((bridge) =>
    bridge.request("/host/reload", {}),
  );
}

export function redactConsoleGrant(value: string): string {
  return value.replace(/(\/console-frames\/)[^/?#\s"'\\)]+/g, "$1[redacted]");
}
