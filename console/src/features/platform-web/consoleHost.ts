import {
  CONSOLE_HOST_PROTOCOL,
  setConsoleHost,
  type ConsoleHostContext,
} from "./context";
import { useWebWorkspace } from "./client";

/** Initialize the shipped Console before any account-scoped stores load. */
export async function initializeConsoleHost(): Promise<void> {
  const origin = document.querySelector<HTMLMetaElement>(
    'meta[name="qwenpaw-platform-origin"]',
  )?.content;
  if (!origin) return;
  if (
    window.parent === window ||
    new URL(origin).origin === window.location.origin
  )
    throw new Error("Open this Console from the Platform Web App");

  await new Promise<void>((resolve, reject) => {
    const pending = new Map<
      number,
      {
        resolve: (value: unknown) => void;
        reject: (error: Error) => void;
      }
    >();
    let nextId = 0;
    const connect = () =>
      window.parent.postMessage(
        { type: "qwenpaw:console-connect", protocol: CONSOLE_HOST_PROTOCOL },
        origin,
      );
    const timer = window.setInterval(connect, 500);
    const timeout = window.setTimeout(() => {
      cleanup();
      reject(new Error("Platform connection timed out; reload the Web App"));
    }, 15000);
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
        !event.ports[0]
      )
        return;
      const context = event.data.context as ConsoleHostContext;
      if (context.protocol !== CONSOLE_HOST_PROTOCOL) return;
      cleanup();
      const port = event.ports[0];
      const request = (path: string, body?: unknown) =>
        new Promise<unknown>((resolve, reject) => {
          const id = ++nextId;
          pending.set(id, { resolve, reject });
          port.postMessage({ id, path, body });
        });
      port.onmessage = ({ data }) => {
        if (data.type === "update") {
          useWebWorkspace.setState({
            update: () => {
              void request("/host/update");
            },
          });
          return;
        }
        const result = pending.get(data.id);
        pending.delete(data.id);
        if (data.error) result?.reject(new Error(data.error));
        else result?.resolve(data.value);
      };
      setConsoleHost(context, request);
      useWebWorkspace.setState({
        account: context.account,
        target: context.target,
        targets: context.targets,
        update: context.updateAvailable
          ? () => {
              void request("/host/update");
            }
          : null,
      });
      const current = window.location.pathname.slice(context.basename.length);
      const requested =
        current && current !== "/index.html"
          ? current + window.location.search + window.location.hash
          : context.route;
      const route =
        requested.startsWith("/") && !requested.startsWith("//")
          ? requested
          : "/chat";
      window.history.replaceState(null, "", context.basename + route);
      void request("/host/navigation", { route });
      window.addEventListener(
        "pagehide",
        () => {
          pending.forEach(({ reject }) => reject(new Error("Console closed")));
          pending.clear();
          port.close();
        },
        { once: true },
      );
      resolve();
    };
    window.addEventListener("message", receive);
    connect();
  });
}
