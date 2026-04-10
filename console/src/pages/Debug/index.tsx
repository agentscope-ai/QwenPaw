import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";
import {
  Alert,
  Button,
  Card,
  Input,
  message,
  Select,
  Space,
  Spin,
  Switch,
  Tag,
  Typography,
} from "antd";
import dayjs from "dayjs";
import {
  debugApi,
  type BackendDebugLogsResponse,
} from "../../api/modules/debug";

const { Text } = Typography;
const BACKEND_LOG_LINES = 200;
const BACKEND_REFRESH_MS = 3000;

type BackendLevelFilter = "all" | "debug" | "info" | "warning" | "error";

function backendLevelColor(level: BackendLevelFilter): string {
  if (level === "error") return "red";
  if (level === "warning") return "gold";
  if (level === "info") return "blue";
  if (level === "debug") return "geekblue";
  return "default";
}

function escapeRegExp(input: string): string {
  return input.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

function highlightLine(line: string, needle: string): ReactNode {
  const q = needle.trim();
  if (!q) return line;
  const re = new RegExp(escapeRegExp(q), "ig");
  const parts: ReactNode[] = [];
  let lastIndex = 0;
  let match: RegExpExecArray | null;
  while ((match = re.exec(line))) {
    const start = match.index;
    const end = start + match[0].length;
    if (start > lastIndex) {
      parts.push(line.slice(lastIndex, start));
    }
    parts.push(
      <mark
        key={`${start}-${end}`}
        style={{
          background: "rgba(255, 214, 102, 0.65)",
          padding: 0,
        }}
      >
        {line.slice(start, end)}
      </mark>,
    );
    lastIndex = end;
  }
  if (lastIndex < line.length) parts.push(line.slice(lastIndex));
  return parts;
}

export default function DebugPage() {
  const { t } = useTranslation();
  const [backendLogs, setBackendLogs] =
    useState<BackendDebugLogsResponse | null>(null);
  const [initialLoading, setInitialLoading] = useState(true);
  const firstFetchDone = useRef(false);
  const [backendError, setBackendError] = useState("");
  const [autoRefresh, setAutoRefresh] = useState(true);
  const [backendNewestFirst, setBackendNewestFirst] = useState(true);
  const [backendLevel, setBackendLevel] = useState<BackendLevelFilter>("all");
  const [backendQuery, setBackendQuery] = useState("");

  const loadBackendLogs = useCallback(
    async (opts?: { successToast?: boolean }) => {
      const isFirstFetch = !firstFetchDone.current;
      try {
        const res = await debugApi.getBackendLogs(BACKEND_LOG_LINES);
        setBackendLogs(res);
        setBackendError("");
        if (opts?.successToast) {
          message.success(
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
          message.error(
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
    [t],
  );

  useEffect(() => {
    void loadBackendLogs();
  }, [loadBackendLogs]);

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

  const handleCopyBackend = async () => {
    try {
      await navigator.clipboard.writeText(filteredBackendText);
      message.success(t("common.copied"));
    } catch {
      message.error(t("common.copyFailed"));
    }
  };

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

  return (
    <Space direction="vertical" size="middle" style={{ width: "100%" }}>
      <Alert
        type="info"
        showIcon
        message={t("debug.title", "Debug")}
        description={t(
          "debug.desc",
          "View the CoPaw backend daemon log file to help diagnose issues. Logs refresh automatically while this page is open.",
        )}
      />

      <Card
        title={t("debug.backend.title", "Backend logs")}
        extra={
          <Space size="middle">
            <Text type="secondary">
              {t("debug.backend.newestFirst", "Newest first")}
            </Text>
            <Switch
              checked={backendNewestFirst}
              onChange={setBackendNewestFirst}
            />
            <Text type="secondary">
              {t("debug.backend.autoRefresh", "Auto refresh")}
            </Text>
            <Switch checked={autoRefresh} onChange={setAutoRefresh} />
          </Space>
        }
      >
        <Space direction="vertical" size="middle" style={{ width: "100%" }}>
          <Space wrap>
            <Button
              onClick={() => void loadBackendLogs({ successToast: true })}
            >
              {t("debug.actions.refreshBackend", "Refresh backend logs")}
            </Button>
            <Button onClick={() => void handleCopyBackend()}>
              {t("debug.actions.copyBackend", "Copy backend logs")}
            </Button>
            <Select
              style={{ width: 160 }}
              value={backendLevel}
              onChange={(v) => setBackendLevel(v)}
              options={[
                { value: "all", label: t("debug.level.all", "All") },
                {
                  value: "error",
                  label: <Tag color={backendLevelColor("error")}>ERROR</Tag>,
                },
                {
                  value: "warning",
                  label: (
                    <Tag color={backendLevelColor("warning")}>WARNING</Tag>
                  ),
                },
                {
                  value: "info",
                  label: <Tag color={backendLevelColor("info")}>INFO</Tag>,
                },
                {
                  value: "debug",
                  label: <Tag color={backendLevelColor("debug")}>DEBUG</Tag>,
                },
              ]}
            />
            <Input
              style={{ width: 320 }}
              value={backendQuery}
              onChange={(e) => setBackendQuery(e.target.value)}
              placeholder={t(
                "debug.backend.searchPlaceholder",
                "Search backend logs...",
              )}
              allowClear
            />
            {backendLogs?.updated_at && (
              <Text type="secondary">
                {t("debug.backend.updatedAt", "Updated at")}:{" "}
                {dayjs(backendLogs.updated_at * 1000).format(
                  "YYYY-MM-DD HH:mm:ss",
                )}
              </Text>
            )}
          </Space>

          {backendLogs?.path && (
            <Text type="secondary">
              <Text strong>{t("debug.backend.path", "Log file")}:</Text>{" "}
              {backendLogs.path}
            </Text>
          )}

          {backendError ? (
            <Alert message={backendError} type="error" showIcon />
          ) : !backendLogs?.exists ? (
            <Alert
              message={t(
                "debug.backend.notFound",
                "Backend log file was not found yet.",
              )}
              type="warning"
              showIcon
            />
          ) : null}

          <Spin spinning={initialLoading} tip={t("common.loading", "Loading")}>
            <div
              style={{
                border: "1px solid rgba(0,0,0,0.06)",
                borderRadius: 8,
                padding: 12,
                minHeight: 120,
                background: "rgba(0,0,0,0.02)",
                fontFamily:
                  'ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", "Courier New", monospace',
                fontSize: 12,
                lineHeight: 1.5,
                whiteSpace: "pre-wrap",
                wordBreak: "break-word",
                maxHeight: 480,
                overflow: "auto",
              }}
            >
              {filteredBackendLines.length ? (
                filteredBackendLines.map((line, idx) => (
                  <div key={idx}>{highlightLine(line, backendQuery)}</div>
                ))
              ) : (
                <Text type="secondary">
                  {t(
                    "debug.backend.placeholder",
                    "Backend log output will appear here.",
                  )}
                </Text>
              )}
            </div>
          </Spin>
        </Space>
      </Card>
    </Space>
  );
}
