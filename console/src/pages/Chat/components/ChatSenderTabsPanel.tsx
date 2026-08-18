import { useCallback, useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { message, Tooltip } from "antd";
import {
  SparkClearLine,
  SparkErrorCircleLine,
  SparkPauseLine,
  SparkPlayFill,
  SparkStopCircleLine,
} from "@agentscope-ai/icons";
import { useTheme } from "../../../contexts/ThemeContext";
import {
  selectTasksForSession,
  useBackgroundTasksStore,
} from "../../../stores/backgroundTasksStore";
import {
  cancelBackgroundTask,
  stopBackgroundTaskWatcher,
} from "../../../hooks/useBackgroundTaskWatcher";
import {
  type QueueItem,
  useMessageQueueStore,
} from "../../../stores/messageQueueStore";
import BackgroundTaskPanel from "./BackgroundTaskPanel";
import MessageQueuePanel from "./MessageQueuePanel";

type TabKey = "bg" | "queue";

const EMPTY_QUEUE: QueueItem[] = [];

interface ChatSenderTabsPanelProps {
  bgSessionId: string;
  /** Frontend chat/session id used by the message-queue store. */
  queueSessionId: string;
  onRemove: (id: string) => void;
  onEdit: (id: string, text: string) => void;
  onReorder: (items: QueueItem[]) => void;
  onInterruptAndSend: (item: QueueItem) => void;
  onClear: () => void;
  onPauseResume: () => void;
  onRetry: (id: string) => void;
  onSkip: (id: string) => void;
}

export default function ChatSenderTabsPanel({
  bgSessionId,
  queueSessionId,
  onRemove,
  onEdit,
  onReorder,
  onInterruptAndSend,
  onClear,
  onPauseResume,
  onRetry,
  onSkip,
}: ChatSenderTabsPanelProps) {
  const { t } = useTranslation();
  const { isDark } = useTheme();
  const tasks = useBackgroundTasksStore((s) => s.tasks);
  const removeTasks = useBackgroundTasksStore((s) => s.removeTasks);
  // Self-subscribe so queue/run-state updates don't invalidate ChatPage options.
  const queueItems =
    useMessageQueueStore((s) => s.queues[queueSessionId]) ?? EMPTY_QUEUE;
  const runState = useMessageQueueStore(
    (s) => s.runStates[queueSessionId] ?? "idle",
  );
  const [batchBusy, setBatchBusy] = useState(false);
  const [showFinished, setShowFinished] = useState(false);

  const sessionTasks = useMemo(
    () => selectTasksForSession(tasks, bgSessionId),
    [tasks, bgSessionId],
  );
  const runningTasks = useMemo(
    () => sessionTasks.filter((task) => task.status === "running"),
    [sessionTasks],
  );
  const finishedTasks = useMemo(
    () =>
      sessionTasks.filter(
        (task) => task.status === "done" || task.status === "cancelled",
      ),
    [sessionTasks],
  );

  const hasBg = sessionTasks.length > 0;
  const hasQueue = queueItems.length > 0;
  const hasRunningBg = runningTasks.length > 0;
  const isPausedOrError = runState === "paused" || runState === "error";

  const [activeTab, setActiveTab] = useState<TabKey>(() =>
    hasRunningBg ? "bg" : hasQueue ? "queue" : hasBg ? "bg" : "queue",
  );

  useEffect(() => {
    if (activeTab === "bg" && !hasBg && hasQueue) {
      setActiveTab("queue");
      return;
    }
    if (activeTab === "queue" && !hasQueue && hasBg) {
      setActiveTab("bg");
      return;
    }
    if (!hasBg && !hasQueue) return;
    if (activeTab === "bg" && !hasBg) setActiveTab("queue");
    if (activeTab === "queue" && !hasQueue) setActiveTab("bg");
  }, [activeTab, hasBg, hasQueue]);

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

  if (!hasBg && !hasQueue) return null;

  const borderColor = isDark ? "rgba(255,255,255,0.08)" : "rgba(0,0,0,0.06)";
  const tabInactiveBg = isDark ? "rgba(255,255,255,0.04)" : "rgba(0,0,0,0.03)";
  const tabActiveBg = isDark ? "rgba(255,255,255,0.08)" : "#fff";
  const textColor = isDark ? "#bbb" : "#555";
  const activeText = isDark ? "#eee" : "#222";
  const mutedColor = isDark ? "#888" : "#999";

  const bgBadgeBg = hasRunningBg
    ? isDark
      ? "rgba(250,173,20,0.2)"
      : "rgba(250,173,20,0.15)"
    : isDark
    ? "rgba(114,46,209,0.25)"
    : "rgba(114,46,209,0.12)";
  const bgBadgeColor = hasRunningBg ? "#d48806" : "#722ed1";

  const chipBtnStyle = {
    border: `1px solid ${borderColor}`,
    background: isDark ? "rgba(255,255,255,0.06)" : "rgba(255,255,255,0.9)",
    color: textColor,
    fontSize: 11,
    padding: "2px 10px",
    borderRadius: 999,
    lineHeight: 1,
    height: 24,
    display: "inline-flex" as const,
    alignItems: "center" as const,
    justifyContent: "center" as const,
    gap: 4,
    cursor: "pointer" as const,
  };

  const chipIconStyle = {
    fontSize: 12,
    display: "block" as const,
    flexShrink: 0,
    lineHeight: 1,
  };

  const chipLabelStyle = {
    lineHeight: 1,
    display: "inline-flex" as const,
    alignItems: "center" as const,
  };

  const bgBadgeCount = hasRunningBg
    ? runningTasks.length
    : showFinished && finishedTasks.length > 0
    ? finishedTasks.length
    : null;

  const renderTab = (
    key: TabKey,
    label: string,
    count: number | null,
    badgeBg: string,
    badgeColor: string,
  ) => {
    const active = activeTab === key;
    return (
      <button
        key={key}
        type="button"
        onClick={() => setActiveTab(key)}
        style={{
          display: "inline-flex",
          alignItems: "center",
          gap: 6,
          border: `1px solid ${borderColor}`,
          borderBottom: active
            ? `1px solid ${tabActiveBg}`
            : `1px solid ${borderColor}`,
          marginBottom: -1,
          borderTopLeftRadius: 6,
          borderTopRightRadius: 6,
          padding: "5px 12px",
          background: active ? tabActiveBg : tabInactiveBg,
          color: active ? activeText : textColor,
          fontSize: 12,
          fontWeight: active ? 600 : 500,
          cursor: "pointer",
          position: "relative",
          zIndex: active ? 1 : 0,
        }}
      >
        <span>{label}</span>
        {count != null && (
          <span
            style={{
              fontSize: 11,
              padding: "0 6px",
              borderRadius: 10,
              background: badgeBg,
              color: badgeColor,
              lineHeight: "16px",
            }}
          >
            {count}
          </span>
        )}
      </button>
    );
  };

  const tabActions =
    activeTab === "bg" && hasBg ? (
      <div style={{ display: "inline-flex", alignItems: "center", gap: 6 }}>
        <label
          style={{
            display: "inline-flex",
            alignItems: "center",
            gap: 4,
            fontSize: 11,
            color: textColor,
            cursor: "pointer",
            userSelect: "none",
            whiteSpace: "nowrap",
          }}
        >
          <input
            type="checkbox"
            checked={showFinished}
            onChange={(e) => setShowFinished(e.target.checked)}
          />
          {t("tool.control.bgQueue.showFinished", "Show completed")}
        </label>
        <button
          type="button"
          disabled={batchBusy || !hasRunningBg}
          onClick={() => void handleCancelAll()}
          style={{
            ...chipBtnStyle,
            opacity: batchBusy || !hasRunningBg ? 0.45 : 1,
            cursor: batchBusy || !hasRunningBg ? "not-allowed" : "pointer",
          }}
        >
          <SparkStopCircleLine style={{ ...chipIconStyle, color: "#ff4d4f" }} />
          <span style={chipLabelStyle}>
            {t("tool.control.bgQueue.cancelAll", "Cancel all")}
          </span>
        </button>
        <button
          type="button"
          disabled={batchBusy || finishedTasks.length === 0}
          onClick={handleClearFinished}
          style={{
            ...chipBtnStyle,
            opacity: batchBusy || finishedTasks.length === 0 ? 0.45 : 1,
            cursor:
              batchBusy || finishedTasks.length === 0
                ? "not-allowed"
                : "pointer",
          }}
        >
          <SparkClearLine style={{ ...chipIconStyle, color: mutedColor }} />
          <span style={chipLabelStyle}>
            {t("tool.control.bgQueue.clearAll", "Clear completed")}
          </span>
        </button>
      </div>
    ) : activeTab === "queue" && hasQueue ? (
      <div style={{ display: "inline-flex", alignItems: "center", gap: 4 }}>
        {runState === "paused" && (
          <span style={{ fontSize: 11, color: "#faad14", marginRight: 2 }}>
            {t("chat.queue.paused")}
          </span>
        )}
        {runState === "error" && (
          <span
            style={{
              display: "inline-flex",
              alignItems: "center",
              gap: 3,
              fontSize: 11,
              color: "#ff4d4f",
              marginRight: 2,
            }}
          >
            <SparkErrorCircleLine style={{ fontSize: 11, display: "block" }} />
            {t("chat.queue.sendFailed")}
          </span>
        )}
        <Tooltip
          title={
            isPausedOrError ? t("chat.queue.resume") : t("chat.queue.pause")
          }
          mouseEnterDelay={0.5}
        >
          <button
            type="button"
            onClick={onPauseResume}
            style={chipBtnStyle}
            aria-label={
              isPausedOrError ? t("chat.queue.resume") : t("chat.queue.pause")
            }
          >
            {isPausedOrError ? (
              <SparkPlayFill style={{ ...chipIconStyle, color: "#52c41a" }} />
            ) : (
              <SparkPauseLine style={{ ...chipIconStyle, color: "#faad14" }} />
            )}
            <span style={chipLabelStyle}>
              {isPausedOrError ? t("chat.queue.resume") : t("chat.queue.pause")}
            </span>
          </button>
        </Tooltip>
        {queueItems.length > 1 && (
          <Tooltip title={t("chat.queue.clear")} mouseEnterDelay={0.5}>
            <button
              type="button"
              onClick={onClear}
              style={chipBtnStyle}
              aria-label={t("chat.queue.clear")}
            >
              <SparkClearLine style={{ ...chipIconStyle, color: mutedColor }} />
              <span style={chipLabelStyle}>{t("chat.queue.clear")}</span>
            </button>
          </Tooltip>
        )}
      </div>
    ) : null;

  return (
    <div
      style={{
        display: "flex",
        flexDirection: "column",
        marginBottom: 4,
        borderRadius: 8,
        background: isDark ? "rgba(255,255,255,0.02)" : "rgba(0,0,0,0.01)",
        border: `1px solid ${borderColor}`,
        overflow: "hidden",
      }}
    >
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: 8,
          padding: "6px 10px 0",
          borderBottom: `1px solid ${borderColor}`,
          background: isDark ? "rgba(0,0,0,0.15)" : "rgba(0,0,0,0.02)",
        }}
      >
        <div
          style={{
            display: "flex",
            alignItems: "flex-end",
            gap: 4,
            flex: 1,
            minWidth: 0,
          }}
        >
          {hasQueue &&
            renderTab(
              "queue",
              t("chat.queue.title", "Message queue"),
              queueItems.length,
              isDark ? "rgba(24,144,255,0.2)" : "rgba(24,144,255,0.12)",
              "#1677ff",
            )}
          {hasBg &&
            renderTab(
              "bg",
              t("tool.control.bgQueue.title", "Background tasks"),
              bgBadgeCount,
              bgBadgeBg,
              bgBadgeColor,
            )}
        </div>
        {tabActions && (
          <div
            style={{
              display: "flex",
              alignItems: "center",
              flexShrink: 0,
              paddingBottom: 5,
            }}
          >
            {tabActions}
          </div>
        )}
      </div>

      <div style={{ padding: "8px 12px" }}>
        {activeTab === "bg" && hasBg && (
          <BackgroundTaskPanel
            sessionId={bgSessionId}
            embedded
            showFinished={showFinished}
          />
        )}
        {activeTab === "queue" && hasQueue && (
          <MessageQueuePanel
            embedded
            items={queueItems}
            runState={runState}
            onRemove={onRemove}
            onEdit={onEdit}
            onReorder={onReorder}
            onInterruptAndSend={onInterruptAndSend}
            onClear={onClear}
            onPauseResume={onPauseResume}
            onRetry={onRetry}
            onSkip={onSkip}
          />
        )}
      </div>
    </div>
  );
}
