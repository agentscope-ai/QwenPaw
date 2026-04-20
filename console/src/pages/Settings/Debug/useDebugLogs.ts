import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { App } from "antd";
import { useTranslation } from "react-i18next";
import {
  debugApi,
  type BackendDebugLogsResponse,
} from "../../../api/modules/debug";

const BACKEND_LOG_LINES = 200;
const BACKEND_REFRESH_MS = 3000;

export type BackendLevelFilter = "all" | "debug" | "info" | "warning" | "error";

export function backendLevelColor(level: BackendLevelFilter): string {
  if (level === "error") return "red";
  if (level === "warning") return "gold";
  if (level === "info") return "blue";
  if (level === "debug") return "geekblue";
  return "default";
}

export function useDebugLogs() {
  const { t } = useTranslation();
  const { message: messageApi } = App.useApp();

  const [backendLogs, setBackendLogs] =
    useState<BackendDebugLogsResponse | null>(null);
  const [initialLoading, setInitialLoading] = useState(true);
  const firstFetchDone = useRef(false);
  const [backendError, setBackendError] = useState("");
  const [autoRefresh, setAutoRefresh] = useState(true);
  const [backendNewestFirst, setBackendNewestFirst] = useState(true);
  const [backendLevel, setBackendLevel] = useState<BackendLevelFilter>("all");
  const [backendQuery, setBackendQuery] = useState("");

  // ── Fetch backend logs ──────────────────────────────────────────────────

  const loadBackendLogs = useCallback(
    async (opts?: { successToast?: boolean }) => {
      const isFirstFetch = !firstFetchDone.current;
      try {
        const res = await debugApi.getBackendLogs(BACKEND_LOG_LINES);
        setBackendLogs(res);
        setBackendError("");
        if (opts?.successToast) {
          messageApi.success(
            t("debug.actions.refreshSuccess", "Logs refreshed"),
          );
        }
      } catch (error) {
        setBackendError(
          error instanceof Error
            ? error.message
            : t("debug.backend.loadFailed", "Failed to load backend logs"),
        );
        if (opts?.successToast) {
          messageApi.error(
            error instanceof Error
              ? error.message
              : t("debug.backend.loadFailed", "Failed to load backend logs"),
          );
        }
      } finally {
        if (isFirstFetch) {
          firstFetchDone.current = true;
          setInitialLoading(false);
        }
      }
    },
    [t, messageApi],
  );

  // ── Initial load ────────────────────────────────────────────────────────

  useEffect(() => {
    void loadBackendLogs();
  }, [loadBackendLogs]);

  // ── Auto-refresh polling ────────────────────────────────────────────────

  useEffect(() => {
    if (!autoRefresh) return;
    let cancelled = false;
    let timeoutId: number | undefined;

    const tick = async () => {
      if (cancelled) return;
      await loadBackendLogs();
      if (cancelled) return;
      timeoutId = window.setTimeout(() => {
        void tick();
      }, BACKEND_REFRESH_MS);
    };

    timeoutId = window.setTimeout(() => {
      void tick();
    }, BACKEND_REFRESH_MS);
    return () => {
      cancelled = true;
      if (timeoutId !== undefined) {
        window.clearTimeout(timeoutId);
      }
    };
  }, [autoRefresh, loadBackendLogs]);

  // ── Filter and sort ─────────────────────────────────────────────────────

  const backendLines = useMemo(() => {
    const raw = backendLogs?.content || "";
    if (!raw.trim()) return [] as string[];
    const lines = raw.split("\n");
    return backendNewestFirst ? [...lines].reverse() : lines;
  }, [backendLogs?.content, backendNewestFirst]);

  const filteredBackendLines = useMemo(() => {
    const q = backendQuery.trim().toLowerCase();
    return backendLines.filter((line) => {
      if (backendLevel !== "all") {
        const lvl = backendLevel.toUpperCase();
        const levelHit =
          line.includes(` ${lvl} `) ||
          line.includes(`| ${lvl} `) ||
          line.includes(`${lvl} `);
        if (!levelHit) return false;
      }
      if (!q) return true;
      return line.toLowerCase().includes(q);
    });
  }, [backendLines, backendLevel, backendQuery]);

  const filteredBackendText = useMemo(
    () => filteredBackendLines.join("\n"),
    [filteredBackendLines],
  );

  // ── Copy to clipboard ──────────────────────────────────────────────────

  const handleCopyBackend = useCallback(async () => {
    try {
      await navigator.clipboard.writeText(filteredBackendText);
      messageApi.success(t("common.copied"));
    } catch {
      messageApi.error(t("common.copyFailed"));
    }
  }, [filteredBackendText, t, messageApi]);

  return {
    backendLogs,
    initialLoading,
    backendError,
    autoRefresh,
    setAutoRefresh,
    backendNewestFirst,
    setBackendNewestFirst,
    backendLevel,
    setBackendLevel,
    backendQuery,
    setBackendQuery,
    filteredBackendLines,
    loadBackendLogs,
    handleCopyBackend,
  };
}
