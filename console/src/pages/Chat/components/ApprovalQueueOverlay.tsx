import { useEffect, useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { IconButton } from "@agentscope-ai/design";
import { ChevronLeft, ChevronRight } from "lucide-react";

interface ApprovalQueueItem {
  requestId: string;
}

interface ApprovalQueueOverlayProps<T extends ApprovalQueueItem> {
  items: readonly T[];
  renderItem: (item: T) => ReactNode;
}

export default function ApprovalQueueOverlay<T extends ApprovalQueueItem>({
  items,
  renderItem,
}: ApprovalQueueOverlayProps<T>) {
  const { t } = useTranslation();
  const [activeRequestId, setActiveRequestId] = useState<string | null>(null);
  // Last confirmed position of the active card. When that card resolves and
  // leaves the queue, keep the position (clamped to the new tail) instead of
  // rewinding to the first card, so resolving card N surfaces card N+1.
  const [positionIndex, setPositionIndex] = useState(0);
  const requestedIndex = items.findIndex(
    (item) => item.requestId === activeRequestId,
  );
  const activeIndex =
    requestedIndex >= 0
      ? requestedIndex
      : Math.min(positionIndex, Math.max(items.length - 1, 0));
  const activeItem = items[activeIndex];

  useEffect(() => {
    if (items.length === 0) {
      setPositionIndex(0);
      setActiveRequestId(null);
      return;
    }
    if (!activeItem) return;
    if (requestedIndex >= 0 && requestedIndex !== positionIndex) {
      setPositionIndex(requestedIndex);
    }
    if (activeItem.requestId !== activeRequestId) {
      setActiveRequestId(activeItem.requestId);
    }
  }, [
    activeItem,
    activeRequestId,
    items.length,
    positionIndex,
    requestedIndex,
  ]);

  if (!activeItem) return null;

  const positionLabel = t("approval.queue.position", {
    current: activeIndex + 1,
    total: items.length,
  });

  return (
    <section
      role="region"
      aria-label={t("approval.queue.title")}
      style={{
        position: "fixed",
        bottom: 80,
        right: 24,
        zIndex: 1000,
        display: "flex",
        width: "calc(100vw - 48px)",
        maxWidth: 480,
        flexDirection: "column",
        gap: 8,
      }}
    >
      <div
        style={{
          display: "flex",
          alignItems: "center",
          alignSelf: "flex-end",
          gap: 4,
          padding: "4px 6px",
          border: "1px solid var(--app-border-subtle)",
          borderRadius: 10,
          background: "var(--app-surface-raised)",
          boxShadow: "var(--app-shadow-panel)",
          color: "var(--app-text-secondary)",
        }}
      >
        <IconButton
          aria-label={t("approval.queue.previous")}
          bordered={false}
          size="small"
          disabled={activeIndex === 0}
          icon={<ChevronLeft size={16} aria-hidden />}
          onClick={() =>
            setActiveRequestId(items[activeIndex - 1]?.requestId ?? null)
          }
        />
        <span
          aria-live="polite"
          style={{
            minWidth: 44,
            textAlign: "center",
            fontSize: 12,
            fontVariantNumeric: "tabular-nums",
          }}
        >
          {positionLabel}
        </span>
        <IconButton
          aria-label={t("approval.queue.next")}
          bordered={false}
          size="small"
          disabled={activeIndex === items.length - 1}
          icon={<ChevronRight size={16} aria-hidden />}
          onClick={() =>
            setActiveRequestId(items[activeIndex + 1]?.requestId ?? null)
          }
        />
      </div>
      <div data-approval-id={activeItem.requestId}>
        {renderItem(activeItem)}
      </div>
    </section>
  );
}
