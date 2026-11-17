import { getHost, type HarnessSettingsProps } from "@qwenpaw/plugin-sdk";
import type {
  HarnessStatus,
  HarnessText,
  SharedSettingsProps,
} from "./Settings";

const host = getHost().host;
const React = host.React;
type Scope = "check" | "connection";
interface Operation {
  generation: number;
  epoch: number;
  backendId: string;
  agentId: string;
  controller: AbortController;
  timer?: ReturnType<typeof setTimeout>;
  deadline?: ReturnType<typeof setTimeout>;
  popup?: Window | null;
}
type Options = Pick<HarnessSettingsProps, "value" | "open"> &
  Pick<SharedSettingsProps, "backendId" | "loginMode"> & { text: HarnessText };
const errorMessage = (cause: unknown) =>
  cause instanceof Error ? cause.message : String(cause);

export function useHarnessConnection({
  value,
  open,
  backendId,
  loginMode,
  text,
}: Options) {
  const agentId = host.useSelectedAgent().id;
  const { message } = host.antd.App.useApp();
  const latest = React.useRef({
    value,
    open,
    backendId,
    agentId,
    text,
    message,
  });
  latest.current = { value, open, backendId, agentId, text, message };
  const [status, setStatus] = React.useState<HarnessStatus | null>(null);
  const [checking, setChecking] = React.useState(false);
  const [connecting, setConnecting] = React.useState(false);
  const [error, setError] = React.useState("");
  const active = React.useRef(false);
  const epoch = React.useRef(0);
  const generation = React.useRef(0);
  const operations = React.useRef<Partial<Record<Scope, Operation>>>({});

  const current = React.useCallback((scope: Scope, operation: Operation) => {
    const context = latest.current;
    return (
      active.current &&
      context.open &&
      context.backendId === operation.backendId &&
      context.agentId === operation.agentId &&
      epoch.current === operation.epoch &&
      operations.current[scope]?.generation === operation.generation &&
      !operation.controller.signal.aborted
    );
  }, []);
  const cancel = React.useCallback((scope: Scope) => {
    const operation = operations.current[scope];
    if (!operation) return;
    delete operations.current[scope];
    clearTimeout(operation.timer);
    clearTimeout(operation.deadline);
    operation.controller.abort();
    operation.popup?.close();
    operation.popup = null;
  }, []);
  const begin = React.useCallback(
    (scope: Scope) => {
      if (!active.current || !latest.current.open) return;
      cancel(scope);
      if (scope === "connection") {
        cancel("check");
        setChecking(false);
      }
      const operation: Operation = {
        generation: ++generation.current,
        epoch: epoch.current,
        backendId: latest.current.backendId,
        agentId: latest.current.agentId,
        controller: new AbortController(),
      };
      operations.current[scope] = operation;
      return operation;
    },
    [cancel],
  );
  const request = React.useCallback(
    async <T>(operation: Operation, action: string): Promise<T> => {
      const controller = new AbortController();
      const signal = operation.controller.signal;
      const abort = () => controller.abort();
      signal.addEventListener("abort", abort, { once: true });
      if (signal.aborted) abort();
      let timedOut = false;
      const timer = setTimeout(
        () => {
          timedOut = true;
          controller.abort();
        },
        action === "logout" ? 30000 : 60000,
      );
      try {
        const response = await host.fetch(
          `/harnesses/${operation.backendId}/${action}`,
          {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              settings: latest.current.value,
              device_code: false,
            }),
            signal: controller.signal,
          },
        );
        let body;
        try {
          body = await response.json();
        } catch (cause) {
          if (!response.ok) throw new Error(`HTTP ${response.status}`);
          throw cause;
        }
        if (!response.ok) {
          const detail = body?.detail;
          throw new Error(
            typeof detail === "string"
              ? detail
              : detail?.message ?? `HTTP ${response.status}`,
          );
        }
        return body as T;
      } catch (cause) {
        if (timedOut) throw new Error("Request timed out");
        throw cause;
      } finally {
        clearTimeout(timer);
        signal.removeEventListener("abort", abort);
      }
    },
    [],
  );
  const load = React.useCallback(
    async (scope: Scope, operation: Operation) => {
      const result = await request<HarnessStatus>(operation, "status");
      if (current(scope, operation)) {
        if (scope === "connection" && result.authenticated) {
          cancel("check");
          setChecking(false);
        }
        setStatus(result);
        setError(result.error ?? "");
      }
      return result;
    },
    [cancel, current, request],
  );
  const check = React.useCallback(async () => {
    const operation = begin("check");
    if (!operation) return;
    setChecking(true);
    try {
      await load("check", operation);
    } catch (cause) {
      if (current("check", operation)) setError(errorMessage(cause));
    } finally {
      if (current("check", operation)) {
        setChecking(false);
        cancel("check");
      }
    }
  }, [begin, cancel, current, load]);

  React.useEffect(() => {
    active.current = open;
    setStatus(null);
    setError("");
    setChecking(false);
    setConnecting(false);
    if (open) void check();
    return () => {
      active.current = false;
      epoch.current++;
      cancel("check");
      cancel("connection");
    };
  }, [open, backendId, agentId, check, cancel]);

  const connect = async () => {
    const operation = begin("connection");
    if (!operation) return;
    setConnecting(true);
    try {
      // Open synchronously within the click to preserve browser popup permission.
      if (loginMode === "browser") {
        operation.popup = window.open("about:blank", "_blank");
        if (operation.popup) operation.popup.opener = null;
      }
      const login = await request<{ authUrl?: string; type?: string }>(
        operation,
        "login",
      );
      if (!current("connection", operation)) return;
      if (loginMode === "browser" && login.authUrl) {
        if (operation.popup) {
          operation.popup.location.href = login.authUrl;
          operation.popup = null;
        } else window.open(login.authUrl, "_blank", "noopener,noreferrer");
      } else if (login.type !== "external") {
        throw new Error("Login did not start");
      }
      // An external response did not consume the browser's preopened blank page.
      operation.popup?.close();
      operation.popup = null;
      const poll = async () => {
        if (!current("connection", operation)) return;
        try {
          const result = await load("connection", operation);
          if (!current("connection", operation)) return;
          if (result.authenticated) {
            setConnecting(false);
            latest.current.message.success(latest.current.text.connected);
            cancel("connection");
            return;
          }
        } catch {
          // Retry transient polling failures until the overall login deadline.
        }
        if (current("connection", operation))
          operation.timer = setTimeout(() => void poll(), 2000);
      };
      operation.timer = setTimeout(() => void poll(), 2000);
      operation.deadline = setTimeout(() => {
        if (!current("connection", operation)) return;
        setConnecting(false);
        cancel("connection");
      }, 120000);
    } catch (cause) {
      if (!current("connection", operation)) return;
      setConnecting(false);
      latest.current.message.error(errorMessage(cause));
      cancel("connection");
    }
  };
  const disconnect = async () => {
    const operation = begin("connection");
    if (!operation) return;
    setConnecting(false);
    try {
      await request(operation, "logout");
      if (!current("connection", operation)) return;
      await load("connection", operation);
      if (current("connection", operation))
        latest.current.message.success(latest.current.text.disconnected);
    } catch (cause) {
      if (current("connection", operation))
        latest.current.message.error(errorMessage(cause));
    } finally {
      if (current("connection", operation)) cancel("connection");
    }
  };
  const copyPath = async (path: string) => {
    const capturedEpoch = epoch.current;
    const context = latest.current;
    const valid = () =>
      active.current &&
      latest.current.open &&
      capturedEpoch === epoch.current &&
      context.backendId === latest.current.backendId &&
      context.agentId === latest.current.agentId;
    if (!valid()) return;
    try {
      await navigator.clipboard.writeText(path);
      if (valid()) latest.current.message.success(latest.current.text.copied);
    } catch {
      if (valid()) latest.current.message.error(latest.current.text.copyFailed);
    }
  };
  return {
    status,
    checking,
    connecting,
    error,
    check,
    connect,
    disconnect,
    copyPath,
  };
}
