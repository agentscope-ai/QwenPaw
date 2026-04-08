export type DebugLogLevel =
  | "error"
  | "warn"
  | "info"
  | "debug"
  | "log";

export type DebugLogSource =
  | "console"
  | "window.error"
  | "window.unhandledrejection";

export interface DebugLogEntry {
  id: string;
  ts: number;
  level: DebugLogLevel;
  source: DebugLogSource;
  message: string;
  detail?: string;
  stack?: string;
  href?: string;
}

const STORAGE_KEY = "copaw_debug_logs_v1";
const BROADCAST_CHANNEL = "copaw_debug_logs_channel_v1";
const MAX_ENTRIES = 500;

type Listener = (entries: DebugLogEntry[]) => void;
const listeners = new Set<Listener>();
let storageSyncAttached = false;
let captureInitialized = false;
let broadcast: BroadcastChannel | null = null;

/** True while addDebugLog runs (storage + emit). Prevents emit→listener→console/addDebugLog loops. */
let isProcessingInternalLog = false;

function safeStringify(value: unknown): string {
  try {
    if (value instanceof Error) {
      return value.stack || value.message || String(value);
    }
    if (typeof value === "string") return value;
    return JSON.stringify(value);
  } catch {
    return String(value);
  }
}

function coerceMessage(args: unknown[]): { message: string; detail?: string } {
  if (!args.length) return { message: "" };
  const first = args[0];
  const message = safeStringify(first);
  const rest = args.slice(1);
  if (!rest.length) return { message };
  return { message, detail: rest.map(safeStringify).join("\n") };
}

function loadFromStorage(): DebugLogEntry[] {
  if (typeof window === "undefined") return [];
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw);
    if (!Array.isArray(parsed)) return [];
    return parsed
      .filter((e) => e && typeof e === "object")
      .slice(-MAX_ENTRIES) as DebugLogEntry[];
  } catch {
    return [];
  }
}

function saveToStorage(entries: DebugLogEntry[]) {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(entries));
  } catch {
    // best-effort; ignore quota errors
  }
}

let cache: DebugLogEntry[] | null = null;
function getCache(): DebugLogEntry[] {
  if (cache) return cache;
  cache = loadFromStorage();
  return cache;
}

function emit() {
  const entries = getDebugLogs();
  for (const cb of listeners) cb(entries);
}

function notifyCrossTab() {
  if (typeof window === "undefined") return;
  try {
    if (typeof BroadcastChannel !== "undefined") {
      broadcast ??= new BroadcastChannel(BROADCAST_CHANNEL);
      broadcast.postMessage({ type: "debug-logs-updated" });
    }
  } catch {
    // best-effort
  }
}

function attachCrossTabSync() {
  if (typeof window === "undefined" || storageSyncAttached) return;
  storageSyncAttached = true;

  window.addEventListener("storage", (event) => {
    if (event.key !== STORAGE_KEY) return;
    cache = loadFromStorage();
    emit();
  });

  try {
    if (typeof BroadcastChannel !== "undefined") {
      broadcast ??= new BroadcastChannel(BROADCAST_CHANNEL);
      broadcast.addEventListener("message", () => {
        cache = loadFromStorage();
        emit();
      });
    }
  } catch {
    // best-effort
  }
}

function newId(): string {
  // stable enough for UI + export without extra deps
  return `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`;
}

export function getDebugLogs(): DebugLogEntry[] {
  return [...getCache()].sort((a, b) => b.ts - a.ts);
}

export function clearDebugLogs() {
  cache = [];
  saveToStorage(cache);
  notifyCrossTab();
  emit();
}

export function subscribeDebugLogs(cb: Listener): () => void {
  attachCrossTabSync();
  listeners.add(cb);
  cb(getDebugLogs());
  return () => {
    listeners.delete(cb);
  };
}

export function addDebugLog(entry: Omit<DebugLogEntry, "id" | "ts" | "href">) {
  if (isProcessingInternalLog) return;
  try {
    isProcessingInternalLog = true;
    const e: DebugLogEntry = {
      id: newId(),
      ts: Date.now(),
      href: typeof window !== "undefined" ? window.location.href : undefined,
      ...entry,
    };
    const entries = getCache();
    entries.push(e);
    if (entries.length > MAX_ENTRIES) entries.splice(0, entries.length - MAX_ENTRIES);
    saveToStorage(entries);
    notifyCrossTab();
    emit();
  } finally {
    isProcessingInternalLog = false;
  }
}

export function initDebugLogCapture(options?: {
  ignoreMessages?: (msg: string) => boolean;
  suppressIgnoredConsole?: boolean;
}) {
  if (typeof window === "undefined" || captureInitialized) return;
  captureInitialized = true;
  const ignore = options?.ignoreMessages;
  const suppress = options?.suppressIgnoredConsole ?? false;
  attachCrossTabSync();

  const originalError: (...args: unknown[]) => void = console.error.bind(console);
  const originalWarn: (...args: unknown[]) => void = console.warn.bind(console);
  const originalInfo: ((...args: unknown[]) => void) | undefined =
    console.info?.bind(console);
  const originalDebug: ((...args: unknown[]) => void) | undefined =
    console.debug?.bind(console);
  const originalLog: ((...args: unknown[]) => void) | undefined =
    console.log?.bind(console);

  console.error = (...args: unknown[]) => {
    // 🔒 Recursion guard: inside addDebugLog/emit, use native console only
    if (isProcessingInternalLog) {
      originalError(...args);
      return;
    }
    const { message, detail } = coerceMessage(args);
    const ignored = !!ignore?.(message);
    if (!ignored) {
      const err = args.find((a) => a instanceof Error) as Error | undefined;
      addDebugLog({
        level: "error",
        source: "console",
        message,
        detail,
        stack: err?.stack,
      });
    }
    if (ignored && suppress) return;
    originalError(...args);
  };

  console.warn = (...args: unknown[]) => {
    if (isProcessingInternalLog) {
      originalWarn(...args);
      return;
    }
    const { message, detail } = coerceMessage(args);
    const ignored = !!ignore?.(message);
    if (!ignored) {
      const err = args.find((a) => a instanceof Error) as Error | undefined;
      addDebugLog({
        level: "warn",
        source: "console",
        message,
        detail,
        stack: err?.stack,
      });
    }
    if (ignored && suppress) return;
    originalWarn(...args);
  };

  if (originalInfo) {
    console.info = (...args: unknown[]) => {
      if (isProcessingInternalLog) {
        originalInfo(...args);
        return;
      }
      const { message, detail } = coerceMessage(args);
      const ignored = !!ignore?.(message);
      if (!ignored) {
        addDebugLog({
          level: "info",
          source: "console",
          message,
          detail,
        });
      }
      if (ignored && suppress) return;
      originalInfo(...args);
    };
  }

  if (originalDebug) {
    console.debug = (...args: unknown[]) => {
      if (isProcessingInternalLog) {
        originalDebug(...args);
        return;
      }
      const { message, detail } = coerceMessage(args);
      const ignored = !!ignore?.(message);
      if (!ignored) {
        addDebugLog({
          level: "debug",
          source: "console",
          message,
          detail,
        });
      }
      if (ignored && suppress) return;
      originalDebug(...args);
    };
  }

  if (originalLog) {
    console.log = (...args: unknown[]) => {
      if (isProcessingInternalLog) {
        originalLog(...args);
        return;
      }
      const { message, detail } = coerceMessage(args);
      const ignored = !!ignore?.(message);
      if (!ignored) {
        addDebugLog({
          level: "log",
          source: "console",
          message,
          detail,
        });
      }
      if (ignored && suppress) return;
      originalLog(...args);
    };
  }

  window.addEventListener("error", (ev) => {
    const msg = (ev as ErrorEvent).message || "Window error";
    if (ignore?.(msg)) return;
    const err = (ev as ErrorEvent).error as Error | undefined;
    addDebugLog({
      level: "error",
      source: "window.error",
      message: msg,
      stack: err?.stack,
      detail: (ev as ErrorEvent).filename
        ? `${(ev as ErrorEvent).filename}:${(ev as ErrorEvent).lineno}:${(ev as ErrorEvent).colno}`
        : undefined,
    });
  });

  window.addEventListener("unhandledrejection", (ev) => {
    const reason = (ev as PromiseRejectionEvent).reason;
    const msg =
      reason instanceof Error
        ? reason.message
        : typeof reason === "string"
          ? reason
          : "Unhandled promise rejection";
    if (ignore?.(msg)) return;
    addDebugLog({
      level: "error",
      source: "window.unhandledrejection",
      message: msg,
      detail: reason instanceof Error ? undefined : safeStringify(reason),
      stack: reason instanceof Error ? reason.stack : undefined,
    });
  });
}
