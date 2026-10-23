import {
  useCallback,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
  type CSSProperties,
} from "react";
import { useTranslation } from "react-i18next";
import { ChevronDown, ChevronUp } from "lucide-react";
import {
  selectTasksForSession,
  useBackgroundTasksStore,
  type BackgroundTask,
} from "../../../stores/backgroundTasksStore";
import {
  cancelBackgroundTask,
  startBackgroundTaskStream,
  stopBackgroundTaskStream,
  stopBackgroundTaskWatcher,
} from "../../../hooks/useBackgroundTaskWatcher";
import { message } from "antd";

/** ~3 collapsed rows (bordered ~36px + 6px gaps) so 1–3 items do not overflow. */
const LIST_MAX_HEIGHT_PX = 120;
const SCROLL_EDGE_PX = 1;

function measureListOverflow(el: HTMLElement): {
  canScrollUp: boolean;
  canScrollDown: boolean;
} {
  const { scrollTop, clientHeight, scrollHeight } = el;
  return {
    canScrollUp: scrollTop > SCROLL_EDGE_PX,
    canScrollDown: scrollTop + clientHeight < scrollHeight - SCROLL_EDGE_PX,
  };
}

interface BackgroundTaskPanelProps {
  sessionId: string;
  /** When true, omit outer chrome/title (used inside ChatSenderTabsPanel). */
  embedded?: boolean;
  /** When set (embedded), parent owns the finished-task filter. */
  showFinished?: boolean;
}

function isFinished(task: BackgroundTask): boolean {
  return task.status === "done" || task.status === "cancelled";
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
  showFinished: showFinishedProp,
}: BackgroundTaskPanelProps) {
  const { t } = useTranslation();
  const tasks = useBackgroundTasksStore((s) => s.tasks);
  const removeTask = useBackgroundTasksStore((s) => s.removeTask);
  const removeTasks = useBackgroundTasksStore((s) => s.removeTasks);

  const sessionTasks = useMemo(
    () => selectTasksForSession(tasks, sessionId),
    [tasks, sessionId],
  );

  const [collapsed, setCollapsed] = useState(true);
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [batchBusy, setBatchBusy] = useState(false);
  const [localShowFinished, setLocalShowFinished] = useState(false);
  const [listOverflow, setListOverflow] = useState({
    canScrollUp: false,
    canScrollDown: false,
  });
  const listRef = useRef<HTMLDivElement>(null);
  const [, setTick] = useState(0);
  const showBody = embedded || !collapsed;
  const showFinished = showFinishedProp ?? localShowFinished;

  const syncListOverflow = useCallback(() => {
    const el = listRef.current;
    if (!el) {
      setListOverflow({
        canScrollUp: false,
        canScrollDown: false,
      });
      return;
    }
    setListOverflow(measureListOverflow(el));
  }, []);

  useEffect(() => {
    if (!sessionTasks.some((t) => t.status === "running")) return;
    const id = setInterval(() => setTick((n) => n + 1), 1000);
    return () => clearInterval(id);
  }, [sessionTasks]);

  const runningTasks = useMemo(
    () => sessionTasks.filter((t) => t.status === "running"),
    [sessionTasks],
  );
  const finishedTasks = useMemo(
    () => sessionTasks.filter(isFinished),
    [sessionTasks],
  );
  const visibleTasks = showFinished ? sessionTasks : runningTasks;
  const expandedTask = visibleTasks.find(
    (task) => task.toolCallId === expandedId,
  );

  useEffect(() => {
    if (expandedId && !expandedTask) setExpandedId(null);
  }, [expandedId, expandedTask]);

  const expandedToolCallId = expandedTask?.toolCallId;
  const expandedSessionId = expandedTask?.sessionId;
  const expandedStatus = expandedTask?.status;

  useEffect(() => {
    if (
      !showBody ||
      !expandedToolCallId ||
      !expandedSessionId ||
      expandedStatus !== "running"
    ) {
      return;
    }
    startBackgroundTaskStream(expandedSessionId, expandedToolCallId);
    return () => stopBackgroundTaskStream(expandedToolCallId);
  }, [showBody, expandedToolCallId, expandedSessionId, expandedStatus]);

  useLayoutEffect(() => {
    if (!showBody) return;
    syncListOverflow();
    const el = listRef.current;
    if (!el || typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(() => syncListOverflow());
    observer.observe(el);
    for (const child of Array.from(el.children)) {
      observer.observe(child);
    }
    return () => observer.disconnect();
  }, [showBody, visibleTasks, showFinished, syncListOverflow]);

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

  const handleClearFinished = useCallback(() => {
    if (finishedTasks.length === 0 || batchBusy) return;
    for (const task of finishedTasks) {
      stopBackgroundTaskWatcher(task.toolCallId);
    }
    removeTasks(finishedTasks.map((task) => task.toolCallId));
    message.info(
      t("tool.control.bgQueue.clearAllDone", "Cleared completed tasks"),
    );
  }, [finishedTasks, batchBusy, removeTasks, t]);

  if (sessionTasks.length === 0) return null;

  const hasRunning = runningTasks.length > 0;
  const borderColor = "var(--app-border-subtle)";
  const badgeBg = hasRunning
    ? "var(--app-warning-bg)"
    : "var(--app-accent-soft)";
  const badgeColor = hasRunning
    ? "var(--app-warning-text)"
    : "var(--app-accent-text)";
  const badgeCount = hasRunning
    ? runningTasks.length
    : showFinished
    ? finishedTasks.length
    : 0;
  // Mask colors contribute alpha only; they are not rendered theme colors.
  const listMask =
    listOverflow.canScrollUp && listOverflow.canScrollDown
      ? "linear-gradient(to bottom, transparent, black 20px, black calc(100% - 28px), transparent)"
      : listOverflow.canScrollDown
      ? "linear-gradient(to bottom, black 0, black calc(100% - 28px), transparent)"
      : listOverflow.canScrollUp
      ? "linear-gradient(to bottom, transparent, black 20px, black 100%)"
      : undefined;
  const actionBtnStyle: CSSProperties = {
    border: `1px solid ${borderColor}`,
    background: "var(--app-fill-faint)",
    cursor: batchBusy ? "not-allowed" : "pointer",
    color: "var(--app-text-secondary)",
    fontSize: 11,
    padding: "2px 8px",
    borderRadius: 4,
    lineHeight: 1.4,
    opacity: batchBusy ? 0.5 : 1,
  };

  const showFinishedToggle = (
    <label
      style={{
        display: "inline-flex",
        alignItems: "center",
        gap: 4,
        fontSize: 11,
        color: "var(--app-text-secondary)",
        cursor: "pointer",
        userSelect: "none",
        whiteSpace: "nowrap",
      }}
    >
      <input
        type="checkbox"
        checked={showFinished}
        onChange={(e) => setLocalShowFinished(e.target.checked)}
        onClick={(e) => e.stopPropagation()}
      />
      {t("tool.control.bgQueue.showFinished", "Show completed")}
    </label>
  );

  const batchActions = (
    <div
      style={{ display: "flex", gap: 6, flexShrink: 0, alignItems: "center" }}
    >
      {showFinishedToggle}
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
        disabled={batchBusy || finishedTasks.length === 0}
        onClick={(e) => {
          e.stopPropagation();
          handleClearFinished();
        }}
        style={{
          ...actionBtnStyle,
          opacity: batchBusy || finishedTasks.length === 0 ? 0.4 : 1,
          cursor:
            batchBusy || finishedTasks.length === 0 ? "not-allowed" : "pointer",
        }}
      >
        {t("tool.control.bgQueue.clearAll", "Clear completed")}
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
        background: embedded ? "transparent" : "var(--app-fill-faint)",
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
              color: "var(--app-text-secondary)",
              fontSize: 12,
              fontWeight: 500,
              flex: 1,
              minWidth: 0,
            }}
          >
            <span>{t("tool.control.bgQueue.title", "Background tasks")}</span>
            {badgeCount > 0 && (
              <span
                style={{
                  fontSize: 11,
                  padding: "0 6px",
                  borderRadius: 10,
                  background: badgeBg,
                  color: badgeColor,
                }}
              >
                {badgeCount}
              </span>
            )}
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

      {showBody && (
        <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
          <div style={{ position: "relative" }}>
            <div
              ref={listRef}
              onScroll={syncListOverflow}
              style={{
                display: "flex",
                flexDirection: "column",
                gap: 6,
                maxHeight: LIST_MAX_HEIGHT_PX,
                overflowY: "auto",
                WebkitMaskImage: listMask,
                maskImage: listMask,
              }}
            >
              {visibleTasks.length === 0 && (
                <div
                  style={{
                    fontSize: 12,
                    color: "var(--app-text-tertiary)",
                    padding: "6px 8px",
                  }}
                >
                  {!showFinished && finishedTasks.length > 0
                    ? t("tool.control.bgQueue.emptyHiddenFinished", {
                        count: finishedTasks.length,
                        defaultValue: "{{count}} completed (hidden)",
                      })
                    : t(
                        "tool.control.bgQueue.emptyRunning",
                        "No running tasks",
                      )}
                </div>
              )}
              {visibleTasks.map((task) => {
                const isExpanded = expandedId === task.toolCallId;
                const isRunning = task.status === "running";
                const duration = formatDuration(task.startTime, task.endTime);
                const statusText = isRunning
                  ? `${t(
                      "tool.control.bgQueue.running",
                      "Running",
                    )} ${duration}`
                  : task.status === "cancelled"
                  ? `${t("tool.control.bgQueue.cancelled", "Cancelled")} · ${t(
                      "tool.control.bgQueue.totalDuration",
                      "Total",
                    )} ${duration}`
                  : `${t(
                      "tool.control.bgQueue.doneLabel",
                      "Task completed",
                    )} · ${t(
                      "tool.control.bgQueue.totalDuration",
                      "Total",
                    )} ${duration}`;
                return (
                  <div
                    key={task.toolCallId}
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
                      border: `2px solid ${
                        isExpanded ? "var(--app-accent-border)" : "transparent"
                      }`,
                      background: isExpanded
                        ? "var(--app-accent-soft)"
                        : "var(--app-fill-faint)",
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
                          ? "var(--app-accent)"
                          : task.status === "cancelled"
                          ? "var(--app-status-idle)"
                          : "var(--app-success)",
                        flexShrink: 0,
                      }}
                    />
                    <span
                      style={{
                        flex: 1,
                        overflow: "hidden",
                        textOverflow: "ellipsis",
                        whiteSpace: "nowrap",
                        color: "var(--app-text)",
                      }}
                      title={task.toolName}
                    >
                      {task.toolName}
                    </span>
                    <span
                      style={{
                        color: "var(--app-text-tertiary)",
                        whiteSpace: "nowrap",
                      }}
                    >
                      {statusText}
                    </span>
                    <button
                      type="button"
                      onClick={(e) => {
                        e.stopPropagation();
                        void handleClose(task);
                      }}
                      style={{
                        border: `1px solid ${
                          isRunning ? "var(--app-error-border)" : borderColor
                        }`,
                        background: "transparent",
                        cursor: "pointer",
                        color: isRunning
                          ? "var(--app-error-text)"
                          : "var(--app-text-secondary)",
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
                );
              })}
            </div>
            {listOverflow.canScrollDown && (
              <div
                style={{
                  position: "absolute",
                  left: 0,
                  right: 0,
                  bottom: 0,
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "center",
                  gap: 4,
                  height: 28,
                  fontSize: 11,
                  color: "var(--app-text-secondary)",
                  pointerEvents: "none",
                  background:
                    "linear-gradient(to top, var(--app-surface), transparent)",
                }}
              >
                <ChevronDown size={12} aria-hidden />
                {t("tool.control.bgQueue.scrollMore", "Scroll to view more")}
              </div>
            )}
          </div>
          {expandedTask && (
            <pre
              style={{
                margin: 0,
                padding: 8,
                maxHeight: 160,
                overflow: "auto",
                fontSize: 11,
                fontFamily: "ui-monospace, SFMono-Regular, Menlo, monospace",
                whiteSpace: "pre-wrap",
                wordBreak: "break-word",
                background: "var(--app-surface-sunken)",
                border: `1px solid ${borderColor}`,
                borderRadius: 6,
                color: "var(--app-text)",
              }}
            >
              {(expandedTask.status === "running"
                ? expandedTask.liveOutput
                : expandedTask.result || expandedTask.liveOutput) ||
                t("tool.control.bgQueue.noOutput", "No output yet")}
            </pre>
          )}
        </div>
      )}
    </div>
  );
}
