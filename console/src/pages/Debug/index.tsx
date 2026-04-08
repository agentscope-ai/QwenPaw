import { useCallback, useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import {
  Alert,
  Button,
  Card,
  Input,
  Select,
  Space,
  Switch,
  Table,
  Tag,
  Typography,
} from "antd";
import type { ColumnsType } from "antd/es/table";
import dayjs from "dayjs";
import {
  debugApi,
  type BackendDebugLogsResponse,
} from "../../api/modules/debug";
import {
  clearDebugLogs,
  getDebugLogs,
  subscribeDebugLogs,
  type DebugLogEntry,
  type DebugLogLevel,
} from "../../utils/debugLog";

const { Text } = Typography;
const BACKEND_LOG_LINES = 200;
const BACKEND_REFRESH_MS = 3000;

type LevelFilter = DebugLogLevel | "all";

type BackendLevelFilter = "all" | "debug" | "info" | "warning" | "error";

function levelColor(level: DebugLogLevel): string {
  if (level === "error") return "red";
  if (level === "warn") return "gold";
  if (level === "info") return "blue";
  if (level === "debug") return "geekblue";
  return "default";
}

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

function highlightLine(line: string, needle: string): React.ReactNode {
  const q = needle.trim();
  if (!q) return line;
  const re = new RegExp(escapeRegExp(q), "ig");
  const parts: React.ReactNode[] = [];
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
  const [entries, setEntries] = useState<DebugLogEntry[]>(() => getDebugLogs());
  const [level, setLevel] = useState<LevelFilter>("all");
  const [query, setQuery] = useState("");
  const [backendLogs, setBackendLogs] =
    useState<BackendDebugLogsResponse | null>(null);
  const [backendLoading, setBackendLoading] = useState(false);
  const [backendError, setBackendError] = useState("");
  const [autoRefresh, setAutoRefresh] = useState(true);
  const [backendNewestFirst, setBackendNewestFirst] = useState(true);
  const [backendLevel, setBackendLevel] = useState<BackendLevelFilter>("all");
  const [backendQuery, setBackendQuery] = useState("");

  useEffect(() => subscribeDebugLogs(setEntries), []);

  const loadBackendLogs = useCallback(async () => {
    setBackendLoading(true);
    try {
      const res = await debugApi.getBackendLogs(BACKEND_LOG_LINES);
      setBackendLogs(res);
      setBackendError("");
    } catch (error) {
      setBackendError(
        error instanceof Error
          ? error.message
          : t("debug.backend.loadFailed", "Failed to load backend logs"),
      );
    } finally {
      setBackendLoading(false);
    }
  }, [t]);

  useEffect(() => {
    void loadBackendLogs();
  }, [loadBackendLogs]);

  useEffect(() => {
    if (!autoRefresh) return;
    const timer = window.setInterval(() => {
      void loadBackendLogs();
    }, BACKEND_REFRESH_MS);
    return () => {
      window.clearInterval(timer);
    };
  }, [autoRefresh, loadBackendLogs]);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    return entries.filter((e) => {
      if (level !== "all" && e.level !== level) return false;
      if (!q) return true;
      const hay = `${e.message}\n${e.detail ?? ""}\n${e.stack ?? ""}\n${
        e.source
      }`.toLowerCase();
      return hay.includes(q);
    });
  }, [entries, level, query]);

  const columns: ColumnsType<DebugLogEntry> = useMemo(
    () => [
      {
        title: t("debug.columns.time", "Time"),
        dataIndex: "ts",
        width: 170,
        render: (ts: number) => (
          <Text type="secondary">{dayjs(ts).format("YYYY-MM-DD HH:mm:ss")}</Text>
        ),
      },
      {
        title: t("debug.columns.level", "Level"),
        dataIndex: "level",
        width: 90,
        render: (v: DebugLogLevel) => <Tag color={levelColor(v)}>{v}</Tag>,
      },
      {
        title: t("debug.columns.source", "Source"),
        dataIndex: "source",
        width: 190,
        render: (v: string) => <Text code>{v}</Text>,
      },
      {
        title: t("debug.columns.message", "Message"),
        dataIndex: "message",
        ellipsis: true,
        render: (_: unknown, r) => (
          <Space direction="vertical" size={2} style={{ width: "100%" }}>
            <Text>{r.message || "-"}</Text>
            {r.detail && (
              <Text type="secondary" style={{ whiteSpace: "pre-wrap" }}>
                {r.detail}
              </Text>
            )}
            {r.stack && (
              <Text type="secondary" style={{ whiteSpace: "pre-wrap" }}>
                {r.stack}
              </Text>
            )}
            {r.href && (
              <Text type="secondary">
                <Text strong>{t("debug.href", "URL")}:</Text> {r.href}
              </Text>
            )}
          </Space>
        ),
      },
    ],
    [t],
  );

  const handleCopy = async () => {
    const payload = JSON.stringify(filtered, null, 2);
    await navigator.clipboard.writeText(payload);
  };

  const handleDownload = () => {
    const payload = JSON.stringify(filtered, null, 2);
    const blob = new Blob([payload], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `copaw-debug-${dayjs().format("YYYYMMDD-HHmmss")}.json`;
    a.click();
    URL.revokeObjectURL(url);
  };

  const handleThrow = () => {
    throw new Error("DebugPage: manual throw()");
  };

  const handleReject = () => {
    void Promise.reject(new Error("DebugPage: manual reject()"));
  };

  const handleLog = () => {
    console.log("DebugPage: manual log()", {
      route: window.location.pathname,
      ts: new Date().toISOString(),
    });
  };

  const handleDebug = () => {
    console.debug("DebugPage: manual debug()", {
      route: window.location.pathname,
      ts: new Date().toISOString(),
    });
  };

  const handleInfo = () => {
    console.info("DebugPage: manual info()", {
      route: window.location.pathname,
      ts: new Date().toISOString(),
    });
  };

  const handleWarn = () => {
    console.warn("DebugPage: manual warn()", {
      route: window.location.pathname,
      ts: new Date().toISOString(),
    });
  };

  const handleCopyBackend = async () => {
    await navigator.clipboard.writeText(filteredBackendText);
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
        // Accept both "INFO " and "INFO|" styles.
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
          "This page collects frontend console logs, uncaught runtime errors, and backend daemon logs to help you track issues. Frontend logs are stored locally in your browser and sync across tabs.",
        )}
      />

      <Card
        title={t("debug.frontend.title", "Frontend logs")}
        extra={
          <Text type="secondary">
            {t("debug.frontend.total", "Showing {{count}} entries", {
              count: filtered.length,
            })}
          </Text>
        }
      >
        <Space direction="vertical" size="middle" style={{ width: "100%" }}>
          <Space wrap>
            <Select
              style={{ width: 160 }}
              value={level}
              onChange={(v) => setLevel(v)}
              options={[
                { value: "all", label: t("debug.level.all", "All") },
                { value: "error", label: "error" },
                { value: "warn", label: "warn" },
                { value: "info", label: "info" },
                { value: "debug", label: "debug" },
                { value: "log", label: "log" },
              ]}
            />
            <Input
              style={{ width: 320 }}
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder={t("debug.searchPlaceholder", "Search logs...")}
              allowClear
            />
            <Button onClick={handleCopy}>
              {t("debug.actions.copyJson", "Copy JSON")}
            </Button>
            <Button onClick={handleDownload}>
              {t("debug.actions.downloadJson", "Download JSON")}
            </Button>
            <Button danger onClick={() => clearDebugLogs()}>
              {t("debug.actions.clear", "Clear")}
            </Button>
          </Space>

          <Space wrap>
            <Button onClick={handleLog}>
              {t("debug.actions.log", "Log test message")}
            </Button>
            <Button onClick={handleDebug}>
              {t("debug.actions.debug", "Debug test message")}
            </Button>
            <Button onClick={handleInfo}>
              {t("debug.actions.info", "Info test message")}
            </Button>
            <Button onClick={handleWarn}>
              {t("debug.actions.warn", "Warn test message")}
            </Button>
            <Button onClick={handleThrow}>
              {t("debug.actions.throw", "Throw test error")}
            </Button>
            <Button onClick={handleReject}>
              {t("debug.actions.reject", "Reject test promise")}
            </Button>
          </Space>

          <Table
            rowKey="id"
            columns={columns}
            dataSource={filtered}
            pagination={{ pageSize: 20, showSizeChanger: true }}
          />
        </Space>
      </Card>

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
            <Button loading={backendLoading} onClick={() => void loadBackendLogs()}>
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

          <div
            style={{
              border: "1px solid rgba(0,0,0,0.06)",
              borderRadius: 8,
              padding: 12,
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
        </Space>
      </Card>
    </Space>
  );
}

