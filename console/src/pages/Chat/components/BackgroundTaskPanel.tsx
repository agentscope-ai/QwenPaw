import {
  useCallback,
  useEffect,
  useMemo,
  useState,
  type CSSProperties,
} from "react";
import { useTranslation } from "react-i18next";
import { ChevronDown, ChevronUp, X } from "lucide-react";
import { useTheme } from "../../../contexts/ThemeContext";
import {
  selectTasksForSession,
  useBackgroundTasksStore,
  type BackgroundTask,
} from "../../../stores/backgroundTasksStore";
import {
  cancelBackgroundTask,
  stopBackgroundTaskWatcher,
} from "../../../hooks/useBackgroundTaskWatcher";
import { message } from "antd";

interface BackgroundTaskPanelProps {
  sessionId: string;
  /** When true, omit outer chrome/title (used inside ChatSenderTabsPanel). */
  embedded?: boolean;
}

function formatDuration(startTime: number, endTime: number | null): string {
  const end = endTime ?? Date.now();
  const secs = Math.max(0, Math.floor((end - startTime) / 1000));
  if (secs < 60) return `${secs}s`;
  const m = Math.floor(secs / 60);
  const s = secs % 60;
  return `${m}m ${s}s`;
}

export default function BackgroundTaskPanel({
  sessionId,
  embedded = false,
}: BackgroundTaskPanelProps) {
  const { t } = useTranslation();
  const { isDark } = useTheme();
  const tasks = useBackgroundTasksStore((s) => s.tasks);
  const removeTask = useBackgroundTasksStore((s) => s.removeTask);
  const removeTasks = useBackgroundTasksStore((s) => s.removeTasks);
  const dismissHint = useBackgroundTasksStore((s) => s.dismissHint);

  const sessionTasks = useMemo(
    () => selectTasksForSession(tasks, sessionId),
    [tasks, sessionId],
  );

  const [collapsed, setCollapsed] = useState(true);
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [batchBusy, setBatchBusy] = useState(false);
  const [, setTick] = useState(0);
  const showBody = embedded || !collapsed;

  useEffect(() => {
    if (!sessionTasks.some((t) => t.status === "running")) return;
    const id = setInterval(() => setTick((n) => n + 1), 1000);
    return () => clearInterval(id);
  }, [sessionTasks]);

  const runningTasks = useMemo(
    () => sessionTasks.filter((t) => t.status === "running"),
    [sessionTasks],
  );

  const handleClose = useCallback(
    async (task: BackgroundTask) => {
      if (task.status === "running") {
        try {
          await cancelBackgroundTask(task.sessionId, task.toolCallId);
          message.info(
            t("tool.control.toast.cancelled", "Tool call cancelled"),
          );
        } catch (e) {
          console.error("[BackgroundTaskPanel] cancel failed:", e);
          message.error(
            t("tool.control.toast.cancelFailed", "Failed to cancel tool"),
          );
        }
        return;
      }
      stopBackgroundTaskWatcher(task.toolCallId);
      removeTask(task.toolCallId);
    },
    [removeTask, t],
  );

  const handleCancelAll = useCallback(async () => {
    if (runningTasks.length === 0 || batchBusy) return;
    setBatchBusy(true);
    try {
      await Promise.allSettled(
        runningTasks.map((task) =>
          cancelBackgroundTask(task.sessionId, task.toolCallId),
        ),
      );
      message.info(
        t("tool.control.bgQueue.cancelAllDone", "Cancelled all running tasks"),
      );
    } finally {
      setBatchBusy(false);
    }
  }, [runningTasks, batchBusy, t]);

  const handleClearAll = useCallback(async () => {
    if (sessionTasks.length === 0 || batchBusy) return;
    setBatchBusy(true);
    try {
      // Cancel running tools first, then remove every entry in this session.
      await Promise.allSettled(
        runningTasks.map((task) =>
          cancelBackgroundTask(task.sessionId, task.toolCallId),
        ),
      );
      for (const task of sessionTasks) {
        stopBackgroundTaskWatcher(task.toolCallId);
      }
      removeTasks(sessionTasks.map((task) => task.toolCallId));
      message.info(
        t("tool.control.bgQueue.clearAllDone", "Cleared background task list"),
      );
    } finally {
      setBatchBusy(false);
    }
  }, [sessionTasks, runningTasks, batchBusy, removeTasks, t]);

  if (sessionTasks.length === 0) return null;

  const hasRunning = runningTasks.length > 0;
  const borderColor = isDark ? "rgba(255,255,255,0.08)" : "rgba(0,0,0,0.06)";
  const badgeBg = hasRunning
    ? isDark
      ? "rgba(250,173,20,0.2)"
      : "rgba(250,173,20,0.15)"
    : isDark
    ? "rgba(114,46,209,0.25)"
    : "rgba(114,46,209,0.12)";
  const badgeColor = hasRunning ? "#d48806" : "#722ed1";
  const actionBtnStyle: CSSProperties = {
    border: `1px solid ${borderColor}`,
    background: isDark ? "rgba(255,255,255,0.04)" : "rgba(0,0,0,0.03)",
    cursor: batchBusy ? "not-allowed" : "pointer",
    color: isDark ? "#bbb" : "#555",
    fontSize: 11,
    padding: "2px 8px",
    borderRadius: 4,
    lineHeight: 1.4,
    opacity: batchBusy ? 0.5 : 1,
  };

  const batchActions = (
    <div style={{ display: "flex", gap: 6, flexShrink: 0 }}>
      <button
        type="button"
        disabled={batchBusy || runningTasks.length === 0}
        onClick={(e) => {
          e.stopPropagation();
          void handleCancelAll();
        }}
        style={{
          ...actionBtnStyle,
          opacity: batchBusy || runningTasks.length === 0 ? 0.4 : 1,
          cursor:
            batchBusy || runningTasks.length === 0 ? "not-allowed" : "pointer",
        }}
      >
        {t("tool.control.bgQueue.cancelAll", "Cancel all")}
      </button>
      <button
        type="button"
        disabled={batchBusy || sessionTasks.length === 0}
        onClick={(e) => {
          e.stopPropagation();
          void handleClearAll();
        }}
        style={actionBtnStyle}
      >
        {t("tool.control.bgQueue.clearAll", "Clear all")}
      </button>
    </div>
  );

  return (
    <div
      style={{
        display: "flex",
        flexDirection: "column",
        gap: 6,
        padding: embedded ? 0 : "8px 12px",
        marginBottom: embedded ? 0 : 4,
        borderRadius: embedded ? 0 : 8,
        background: embedded
          ? "transparent"
          : isDark
          ? "rgba(255,255,255,0.02)"
          : "rgba(0,0,0,0.01)",
        border: embedded ? "none" : `1px solid ${borderColor}`,
      }}
    >
      {!embedded && (
        <div
          style={{
            display: "flex",
            alignItems: "center",
            gap: 8,
          }}
        >
          <button
            type="button"
            onClick={() => setCollapsed((c) => !c)}
            style={{
              display: "flex",
              alignItems: "center",
              gap: 8,
              border: "none",
              background: "transparent",
              cursor: "pointer",
              padding: 0,
              color: isDark ? "#bbb" : "#555",
              fontSize: 12,
              fontWeight: 500,
              flex: 1,
              minWidth: 0,
            }}
          >
            <span>{t("tool.control.bgQueue.title", "Background tasks")}</span>
            <span
              style={{
                fontSize: 11,
                padding: "0 6px",
                borderRadius: 10,
                background: badgeBg,
                color: badgeColor,
              }}
            >
              {sessionTasks.length}
            </span>
            <span
              style={{
                marginLeft: "auto",
                opacity: 0.6,
                display: "inline-flex",
                alignItems: "center",
              }}
            >
              {collapsed ? (
                <ChevronDown size={14} aria-hidden />
              ) : (
                <ChevronUp size={14} aria-hidden />
              )}
            </span>
          </button>
          {showBody && batchActions}
        </div>
      )}

      {showBody &&
        sessionTasks.map((task) => {
          const body =
            task.status === "running"
              ? task.liveOutput
              : task.result || task.liveOutput;
          const isExpanded = expandedId === task.toolCallId;
          const isRunning = task.status === "running";
          return (
            <div key={task.toolCallId}>
              {task.hintVisible && (
                <div
                  style={{
                    borderLeft: "3px solid #722ed1",
                    padding: "6px 10px",
                    marginBottom: 4,
                    fontSize: 12,
                    background: isDark
                      ? "rgba(114,46,209,0.12)"
                      : "rgba(114,46,209,0.06)",
                    color: isDark ? "#d3adf7" : "#531dab",
                    display: "flex",
                    justifyContent: "space-between",
                    gap: 8,
                  }}
                >
                  <span>
                    {task.status === "cancelled"
                      ? t("tool.control.hint.cancelled", {
                          tool: task.toolName,
                          defaultValue: `Tool ${task.toolName} cancelled`,
                        })
                      : t("tool.control.hint.completed", {
                          tool: task.toolName,
                          defaultValue: `Tool ${task.toolName} completed in background`,
                        })}
                  </span>
                  <button
                    type="button"
                    onClick={() => dismissHint(task.toolCallId)}
                    style={{
                      border: "none",
                      background: "transparent",
                      cursor: "pointer",
                      color: "inherit",
                      opacity: 0.7,
                      display: "inline-flex",
                      alignItems: "center",
                      padding: 0,
                    }}
                    aria-label={t("common.close", "Close")}
                  >
                    <X size={14} aria-hidden />
                  </button>
                </div>
              )}
              <div
                role="button"
                tabIndex={0}
                onClick={() =>
                  setExpandedId((id) =>
                    id === task.toolCallId ? null : task.toolCallId,
                  )
                }
                onKeyDown={(e) => {
                  if (e.key === "Enter" || e.key === " ") {
                    e.preventDefault();
                    setExpandedId((id) =>
                      id === task.toolCallId ? null : task.toolCallId,
                    );
                  }
                }}
                style={{
                  display: "flex",
                  alignItems: "center",
                  gap: 8,
                  padding: "6px 8px",
                  borderRadius: 6,
                  background: isDark
                    ? "rgba(255,255,255,0.04)"
                    : "rgba(0,0,0,0.02)",
                  cursor: "pointer",
                  fontSize: 12,
                }}
              >
                <span
                  style={{
                    width: 8,
                    height: 8,
                    borderRadius: "50%",
                    background: isRunning
                      ? "#722ed1"
                      : task.status === "cancelled"
                      ? "#8c8c8c"
                      : "#52c41a",
                    flexShrink: 0,
                  }}
                />
                <span
                  style={{
                    flex: 1,
                    overflow: "hidden",
                    textOverflow: "ellipsis",
                    whiteSpace: "nowrap",
                    color: isDark ? "#ddd" : "#333",
                  }}
                  title={task.toolName}
                >
                  {task.toolName}
                </span>
                <span
                  style={{
                    color: isDark ? "#888" : "#999",
                    whiteSpace: "nowrap",
                  }}
                >
                  {isRunning
                    ? `${t(
                        "tool.control.bgQueue.running",
                        "Running",
                      )} ${formatDuration(task.startTime, null)}`
                    : task.status === "cancelled"
                    ? `${t(
                        "tool.control.bgQueue.cancelled",
                        "Cancelled",
                      )} · ${t(
                        "tool.control.bgQueue.totalDuration",
                        "Total",
                      )} ${formatDuration(task.startTime, task.endTime)}`
                    : `${t(
                        "tool.control.bgQueue.totalDuration",
                        "Total",
                      )} ${formatDuration(task.startTime, task.endTime)}`}
                </span>
                <button
                  type="button"
                  onClick={(e) => {
                    e.stopPropagation();
                    void handleClose(task);
                  }}
                  style={{
                    border: `1px solid ${
                      isRunning
                        ? isDark
                          ? "rgba(255,77,79,0.45)"
                          : "rgba(255,77,79,0.35)"
                        : borderColor
                    }`,
                    background: "transparent",
                    cursor: "pointer",
                    color: isRunning
                      ? isDark
                        ? "#ff7875"
                        : "#cf1322"
                      : isDark
                      ? "#aaa"
                      : "#666",
                    fontSize: 11,
                    padding: "1px 8px",
                    borderRadius: 4,
                    flexShrink: 0,
                    whiteSpace: "nowrap",
                  }}
                >
                  {isRunning
                    ? t("tool.control.bgQueue.cancel", "Cancel")
                    : t("tool.control.bgQueue.remove", "Remove")}
                </button>
              </div>
              {isExpanded && (
                <pre
                  style={{
                    margin: "4px 0 0",
                    padding: 8,
                    maxHeight: 160,
                    overflow: "auto",
                    fontSize: 11,
                    fontFamily:
                      "ui-monospace, SFMono-Regular, Menlo, monospace",
                    whiteSpace: "pre-wrap",
                    wordBreak: "break-word",
                    background: isDark ? "#141414" : "#fafafa",
                    border: `1px solid ${borderColor}`,
                    borderRadius: 6,
                    color: isDark ? "#ccc" : "#333",
                  }}
                >
                  {body || t("tool.control.bgQueue.noOutput", "No output yet")}
                </pre>
              )}
            </div>
          );
        })}
    </div>
  );
}
