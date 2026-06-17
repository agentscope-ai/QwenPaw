import { useState, useCallback, useRef } from "react";
import { useTranslation } from "react-i18next";
import { Input, Tooltip } from "antd";
import { IconButton } from "@agentscope-ai/design";
import {
  SparkDragDotLine,
  SparkEditLine,
  SparkSendLine,
  SparkDeleteLine,
  SparkRefreshLine,
  SparkNextSentenceLine,
  SparkPauseLine,
  SparkPlayFill,
  SparkAlertLine,
  SparkErrorCircleLine,
  SparkClearLine,
} from "@agentscope-ai/icons";
import { useTheme } from "../../../contexts/ThemeContext";
import {
  type QueueItem,
  type QueueRunState,
} from "../../../stores/messageQueueStore";

export type { QueueItem };

interface MessageQueuePanelProps {
  items: QueueItem[];
  runState: QueueRunState;
  onRemove: (id: string) => void;
  onEdit: (id: string, text: string) => void;
  onReorder: (items: QueueItem[]) => void;
  onInterruptAndSend: (item: QueueItem) => void;
  onClear: () => void;
  onPauseResume: () => void;
  onRetry: (id: string) => void;
  onSkip: (id: string) => void;
}

export default function MessageQueuePanel({
  items,
  runState,
  onRemove,
  onEdit,
  onReorder,
  onInterruptAndSend,
  onClear,
  onPauseResume,
  onRetry,
  onSkip,
}: MessageQueuePanelProps) {
  const { t } = useTranslation();
  const { isDark } = useTheme();
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editText, setEditText] = useState("");
  const [dragOverId, setDragOverId] = useState<string | null>(null);
  const [hoveredId, setHoveredId] = useState<string | null>(null);
  const dragItemRef = useRef<string | null>(null);

  const startEdit = useCallback((item: QueueItem) => {
    setEditingId(item.id);
    setEditText(item.text);
  }, []);

  const confirmEdit = useCallback(() => {
    if (editingId && editText.trim()) {
      onEdit(editingId, editText.trim());
    }
    setEditingId(null);
    setEditText("");
  }, [editingId, editText, onEdit]);

  const cancelEdit = useCallback(() => {
    setEditingId(null);
    setEditText("");
  }, []);

  const handleDragStart = useCallback((id: string) => {
    dragItemRef.current = id;
  }, []);

  const dragOverIdRef = useRef<string | null>(null);
  const handleDragOver = useCallback((e: React.DragEvent, id: string) => {
    e.preventDefault();
    if (
      dragItemRef.current &&
      dragItemRef.current !== id &&
      dragOverIdRef.current !== id
    ) {
      dragOverIdRef.current = id;
      setDragOverId(id);
    }
  }, []);

  const handleDrop = useCallback(
    (targetId: string) => {
      const fromId = dragItemRef.current;
      if (!fromId || fromId === targetId) {
        setDragOverId(null);
        return;
      }
      const fromIdx = items.findIndex((it) => it.id === fromId);
      const toIdx = items.findIndex((it) => it.id === targetId);
      if (fromIdx === -1 || toIdx === -1) {
        setDragOverId(null);
        return;
      }
      const next = [...items];
      const [moved] = next.splice(fromIdx, 1);
      next.splice(toIdx, 0, moved);
      onReorder(next);
      setDragOverId(null);
      dragItemRef.current = null;
      dragOverIdRef.current = null;
    },
    [items, onReorder],
  );

  const handleDragEnd = useCallback(() => {
    setDragOverId(null);
    dragItemRef.current = null;
    dragOverIdRef.current = null;
  }, []);

  if (items.length === 0) return null;

  const isPausedOrError = runState === "paused" || runState === "error";
  const borderColor = isDark ? "rgba(255,255,255,0.08)" : "rgba(0,0,0,0.06)";
  const rowBg = isDark ? "rgba(255,255,255,0.04)" : "rgba(0,0,0,0.02)";
  const hoverBg = isDark ? "rgba(255,255,255,0.08)" : "rgba(0,0,0,0.05)";
  const dragOverBg = isDark ? "rgba(255,255,255,0.1)" : "rgba(0,0,0,0.06)";
  const mutedColor = isDark ? "#888" : "#999";

  return (
    <div
      style={{
        display: "flex",
        flexDirection: "column",
        gap: 3,
        padding: "8px 12px",
        maxHeight: 220,
        overflowY: "auto",
        borderRadius: 8,
        background: isDark ? "rgba(255,255,255,0.02)" : "rgba(0,0,0,0.01)",
        border: `1px solid ${borderColor}`,
      }}
    >
      {/* Header */}
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          marginBottom: 4,
          position: "sticky",
          top: 0,
          zIndex: 1,
          background: isDark ? "#1f1f1f" : "#fff",
          paddingTop: 4,
          paddingBottom: 6,
          borderBottom: `1px solid ${borderColor}`,
        }}
      >
        {/* Title + status badge */}
        <span
          style={{
            display: "inline-flex",
            alignItems: "center",
            gap: 6,
            fontSize: 12,
            fontWeight: 500,
            color: isDark ? "#bbb" : "#555",
            userSelect: "none",
          }}
        >
          {t("chat.queue.title")} ({items.length})
          {runState === "paused" && (
            <span
              style={{
                display: "inline-flex",
                alignItems: "center",
                gap: 3,
                fontSize: 11,
                color: "#faad14",
                fontWeight: 400,
              }}
            >
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
                fontWeight: 400,
              }}
            >
              <SparkErrorCircleLine style={{ fontSize: 11 }} />
              {t("chat.queue.sendFailed")}
            </span>
          )}
        </span>

        {/* Header actions */}
        <span style={{ display: "inline-flex", alignItems: "center", gap: 4 }}>
          <Tooltip
            title={
              isPausedOrError ? t("chat.queue.resume") : t("chat.queue.pause")
            }
            mouseEnterDelay={0.5}
          >
            <IconButton
              bordered={false}
              size="small"
              icon={
                isPausedOrError ? (
                  <SparkPlayFill style={{ fontSize: 14, color: "#52c41a" }} />
                ) : (
                  <SparkPauseLine style={{ fontSize: 14, color: "#faad14" }} />
                )
              }
              onClick={onPauseResume}
            />
          </Tooltip>
          {items.length > 1 && (
            <Tooltip title={t("chat.queue.clear")} mouseEnterDelay={0.5}>
              <IconButton
                bordered={false}
                size="small"
                icon={
                  <SparkClearLine style={{ fontSize: 14, color: mutedColor }} />
                }
                onClick={onClear}
              />
            </Tooltip>
          )}
        </span>
      </div>

      {/* Queue rows */}
      {items.map((item) => {
        const statusColor =
          item.status === "failed"
            ? "#ff4d4f"
            : item.status === "sending"
            ? "#1890ff"
            : "#52c41a";
        const isHovered = hoveredId === item.id;
        const isEditing = editingId === item.id;

        return (
          <div
            key={item.id}
            draggable={!isEditing && item.status !== "sending"}
            onDragStart={() => handleDragStart(item.id)}
            onDragOver={(e) => handleDragOver(e, item.id)}
            onDrop={() => handleDrop(item.id)}
            onDragEnd={handleDragEnd}
            onMouseEnter={() => setHoveredId(item.id)}
            onMouseLeave={() =>
              setHoveredId((prev) => (prev === item.id ? null : prev))
            }
            style={{
              display: "flex",
              alignItems: "center",
              gap: 4,
              padding: "4px 8px 4px 4px",
              borderRadius: 6,
              fontSize: 12,
              background:
                dragOverId === item.id
                  ? dragOverBg
                  : isHovered
                  ? hoverBg
                  : rowBg,
              cursor: isEditing ? "default" : "grab",
              transition: "background 0.15s ease",
              position: "relative",
              overflow: "hidden",
            }}
          >
            {/* Status bar */}
            <div
              style={{
                position: "absolute",
                left: 0,
                top: 6,
                bottom: 6,
                width: 3,
                borderRadius: 2,
                background: statusColor,
                opacity: 0.8,
              }}
            />

            {/* Drag handle */}
            <Tooltip title={t("chat.queue.dragSort")} mouseEnterDelay={0.8}>
              <span
                style={{
                  color: mutedColor,
                  cursor: "grab",
                  paddingLeft: 6,
                  display: "inline-flex",
                  alignItems: "center",
                  flexShrink: 0,
                }}
              >
                <SparkDragDotLine style={{ fontSize: 13 }} />
              </span>
            </Tooltip>

            {/* Content: editing or display */}
            {isEditing ? (
              <Input
                size="small"
                autoFocus
                value={editText}
                onChange={(e) => setEditText(e.target.value)}
                onPressEnter={confirmEdit}
                onBlur={confirmEdit}
                onKeyDown={(e) => {
                  if (e.key === "Escape") cancelEdit();
                }}
                style={{ flex: 1, fontSize: 12 }}
              />
            ) : (
              <>
                {/* Text */}
                <span
                  style={{
                    flex: 1,
                    overflow: "hidden",
                    textOverflow: "ellipsis",
                    whiteSpace: "nowrap",
                    color:
                      item.status === "failed"
                        ? "#ff4d4f"
                        : item.status === "sending"
                        ? "#1890ff"
                        : isDark
                        ? "#ddd"
                        : "#333",
                    fontWeight: item.status === "sending" ? 500 : 400,
                  }}
                >
                  {item.text}
                  {item.errorMessage && (
                    <span
                      style={{
                        fontSize: 10,
                        color: "#ff4d4f",
                        marginLeft: 4,
                      }}
                    >
                      ({item.errorMessage})
                    </span>
                  )}
                </span>

                {/* Attachment previews */}
                {(item.attachments?.length || 0) > 0 && (
                  <span
                    style={{
                      display: "inline-flex",
                      alignItems: "center",
                      gap: 4,
                      flexShrink: 0,
                    }}
                  >
                    {item.attachments!.map((att, ai) => {
                      const isImage = att.type?.startsWith("image/");
                      return (
                        <Tooltip
                          key={ai}
                          title={att.name || att.url}
                          mouseEnterDelay={0.5}
                        >
                          <span
                            style={{
                              display: "inline-flex",
                              alignItems: "center",
                              gap: 3,
                              padding: "2px 5px",
                              borderRadius: 4,
                              background: isDark
                                ? "rgba(255,255,255,0.06)"
                                : "rgba(0,0,0,0.04)",
                              fontSize: 10,
                              color: mutedColor,
                              maxWidth: 100,
                              overflow: "hidden",
                              whiteSpace: "nowrap" as const,
                            }}
                          >
                            {isImage ? (
                              <img
                                src={att.url}
                                alt={att.name || "image"}
                                style={{
                                  width: 18,
                                  height: 18,
                                  objectFit: "cover" as const,
                                  borderRadius: 3,
                                  flexShrink: 0,
                                }}
                              />
                            ) : (
                              <SparkAlertLine
                                style={{ fontSize: 12, flexShrink: 0 }}
                              />
                            )}
                            <span
                              style={{
                                overflow: "hidden",
                                textOverflow: "ellipsis",
                              }}
                            >
                              {att.name || t("chat.queue.file")}
                            </span>
                          </span>
                        </Tooltip>
                      );
                    })}
                  </span>
                )}

                {/* Row action buttons — always reserve space for layout stability */}
                <span
                  style={{
                    display: "inline-flex",
                    alignItems: "center",
                    gap: 2,
                    flexShrink: 0,
                    opacity: isHovered ? 1 : 0,
                    transition: "opacity 0.15s ease",
                    pointerEvents: isHovered ? "auto" : "none",
                  }}
                >
                  <Tooltip title={t("chat.queue.edit")} mouseEnterDelay={0.5}>
                    <IconButton
                      bordered={false}
                      size="small"
                      icon={<SparkEditLine style={{ fontSize: 13 }} />}
                      onClick={() => startEdit(item)}
                    />
                  </Tooltip>

                  {item.status === "failed" && (
                    <>
                      <Tooltip
                        title={t("chat.queue.retry")}
                        mouseEnterDelay={0.5}
                      >
                        <IconButton
                          bordered={false}
                          size="small"
                          icon={
                            <SparkRefreshLine
                              style={{ fontSize: 13, color: "#1890ff" }}
                            />
                          }
                          onClick={() => onRetry(item.id)}
                        />
                      </Tooltip>
                      <Tooltip
                        title={t("chat.queue.skip")}
                        mouseEnterDelay={0.5}
                      >
                        <IconButton
                          bordered={false}
                          size="small"
                          icon={
                            <SparkNextSentenceLine
                              style={{ fontSize: 13, color: mutedColor }}
                            />
                          }
                          onClick={() => onSkip(item.id)}
                        />
                      </Tooltip>
                    </>
                  )}

                  <Tooltip
                    title={t("chat.queue.interruptAndSend")}
                    mouseEnterDelay={0.5}
                  >
                    <IconButton
                      bordered={false}
                      size="small"
                      icon={<SparkSendLine style={{ fontSize: 13 }} />}
                      onClick={() => onInterruptAndSend(item)}
                    />
                  </Tooltip>

                  <Tooltip title={t("chat.queue.delete")} mouseEnterDelay={0.5}>
                    <IconButton
                      bordered={false}
                      size="small"
                      icon={
                        <SparkDeleteLine
                          style={{ fontSize: 13, color: "#ff4d4f" }}
                        />
                      }
                      onClick={() => onRemove(item.id)}
                    />
                  </Tooltip>
                </span>
              </>
            )}
          </div>
        );
      })}
    </div>
  );
}
