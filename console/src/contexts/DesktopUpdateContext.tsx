import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import {
  checkDesktopUpdate,
  checkCachedUpdate,
  downloadDesktopUpdate,
  installDesktopUpdate,
  installDownloadedUpdate,
  onUpdateEvent,
  type UpdateError,
  type UpdateProgress,
} from "../tauri/desktopUpdate";
import { isDesktopApp } from "../tauri/backendRuntime";

export type UpdatePhase =
  | "idle"
  | "checking"
  | "downloading"
  | "installing"
  | "downloaded"
  | "failed";

interface ContextValue {
  phase: UpdatePhase;
  isBackground: boolean;
  hasUpdate: boolean;
  supportsLaterInstall: boolean;
  version: string;
  body: string;
  downloaded: number;
  total: number | null;
  throughputBps: number;
  error: UpdateError | null;
  startInstall: () => Promise<void>;
  startBackgroundDownload: () => Promise<void>;
  installDownloaded: () => Promise<void>;
  retry: () => Promise<void>;
  dismissFailure: () => void;
}

const DesktopUpdateContext = createContext<ContextValue | null>(null);

const THROUGHPUT_WINDOW_MS = 5_000;

function toErrorMessage(err: unknown): string {
  if (typeof err === "string") return err;
  if (err instanceof Error) return err.message;
  return JSON.stringify(err);
}

export function DesktopUpdateProvider({ children }: { children: ReactNode }) {
  const [phase, setPhase] = useState<UpdatePhase>("idle");
  const [isBackground, setIsBackground] = useState(false);
  const [hasUpdate, setHasUpdate] = useState(false);
  const [supportsLaterInstall, setSupportsLaterInstall] = useState(false);
  const [version, setVersion] = useState("");
  const [body, setBody] = useState("");
  const [downloaded, setDownloaded] = useState(0);
  const [total, setTotal] = useState<number | null>(null);
  const [throughputBps, setThroughputBps] = useState(0);
  const [error, setError] = useState<UpdateError | null>(null);

  const samplesRef = useRef<{ t: number; downloaded: number }[]>([]);

  // Probe on mount: check remote update + check cached update on disk.
  useEffect(() => {
    if (!isDesktopApp()) return;
    let cancelled = false;

    // Check if there's a cached (already downloaded) update on disk.
    checkCachedUpdate()
      .then((cachedVersion) => {
        if (cancelled || !cachedVersion) return;
        setVersion(cachedVersion);
        setHasUpdate(true);
        setSupportsLaterInstall(true);
        setPhase("downloaded");
        setIsBackground(true);
      })
      .catch(() => {});

    // Also check remote for new updates.
    checkDesktopUpdate()
      .then((info) => {
        if (cancelled || !info) return;
        setVersion((prev) => prev || info.version);
        setBody(info.body?.trim() ?? "");
        setHasUpdate(true);
        setSupportsLaterInstall(Boolean(info.supportsLaterInstall));
      })
      .catch((err) => {
        console.warn("[updates] desktop update check failed", err);
      });

    return () => {
      cancelled = true;
    };
  }, []);

  const handleProgress = useCallback((p: UpdateProgress) => {
    const now = Date.now();
    samplesRef.current.push({ t: now, downloaded: p.downloaded });
    samplesRef.current = samplesRef.current.filter(
      (s) => now - s.t <= THROUGHPUT_WINDOW_MS,
    );
    const oldest = samplesRef.current[0];
    const dt = oldest ? (now - oldest.t) / 1000 : 0;
    const dBytes = oldest ? p.downloaded - oldest.downloaded : 0;
    setPhase("downloading");
    setDownloaded(p.downloaded);
    setTotal(p.total ?? null);
    setThroughputBps(dt > 0 ? Math.max(0, dBytes / dt) : 0);
  }, []);

  const beginUpdate = useCallback((background: boolean) => {
    samplesRef.current = [];
    setIsBackground(background);
    setPhase("checking");
    setDownloaded(0);
    setTotal(null);
    setThroughputBps(0);
    setError(null);
  }, []);

  // Subscribe to Rust-side update:* events.
  useEffect(() => {
    if (!isDesktopApp()) return;
    let unlisten: (() => void) | null = null;
    let cancelled = false;
    onUpdateEvent({
      onCheckStart: () => setPhase("checking"),
      onDownloadProgress: handleProgress,
      onInstallStart: () => setPhase("installing"),
      onDownloadDone: (payload) => {
        setPhase("downloaded");
        setVersion(payload.version);
      },
      onError: (err) => {
        setPhase("failed");
        setError(err);
      },
    }).then((u) => {
      if (cancelled) u();
      else unlisten = u;
    });
    return () => {
      cancelled = true;
      unlisten?.();
    };
  }, [handleProgress]);

  // "Install and Restart" immediate full takeover path.
  const startInstall = useCallback(async () => {
    beginUpdate(false);
    try {
      await installDesktopUpdate();
    } catch (err) {
      setPhase("failed");
      setError({ stage: "check", kind: "other", message: toErrorMessage(err) });
    }
  }, [beginUpdate]);

  // "Update Later" caches the update in the background, no UI takeover.
  const startBackgroundDownload = useCallback(async () => {
    beginUpdate(true);
    try {
      await downloadDesktopUpdate();
    } catch (err) {
      setPhase("failed");
      setError({ stage: "check", kind: "other", message: toErrorMessage(err) });
    }
  }, [beginUpdate]);

  // Install a previously downloaded update.
  const installDownloadedFn = useCallback(async () => {
    setIsBackground(false);
    setPhase("installing");
    setError(null);
    try {
      await installDownloadedUpdate();
    } catch (err) {
      setPhase("failed");
      setIsBackground(false);
      setError({
        stage: "install",
        kind: "other",
        message: toErrorMessage(err),
      });
    }
  }, []);

  const dismissFailure = useCallback(() => {
    setPhase("idle");
    setError(null);
    setIsBackground(false);
  }, []);

  const value = useMemo<ContextValue>(
    () => ({
      phase,
      isBackground,
      hasUpdate,
      supportsLaterInstall,
      version,
      body,
      downloaded,
      total,
      throughputBps,
      error,
      startInstall,
      startBackgroundDownload,
      installDownloaded: installDownloadedFn,
      retry: startInstall,
      dismissFailure,
    }),
    [
      phase,
      isBackground,
      hasUpdate,
      supportsLaterInstall,
      version,
      body,
      downloaded,
      total,
      throughputBps,
      error,
      startInstall,
      startBackgroundDownload,
      installDownloadedFn,
      dismissFailure,
    ],
  );

  return (
    <DesktopUpdateContext.Provider value={value}>
      {children}
    </DesktopUpdateContext.Provider>
  );
}

export function useDesktopUpdate(): ContextValue {
  const ctx = useContext(DesktopUpdateContext);
  if (!ctx) {
    throw new Error(
      "useDesktopUpdate must be used inside <DesktopUpdateProvider>",
    );
  }
  return ctx;
}
