import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { message } from "antd";
import { useTranslation } from "react-i18next";
import api from "../../../api";
import type { PushMessage } from "../types";
import {
  buildContentFallbackTrace,
  buildTraceDisplayItems,
  type TraceDisplayItem,
} from "../utils/traceUtils";

interface TraceData {
  events: Array<{ at: number; event: Record<string, unknown> }>;
}

export interface TraceViewerState {
  detailOpen: boolean;
  selectedMessage: PushMessage | null;
  traceLoading: boolean;
  traceEvents: TraceDisplayItem[];
  expandedTraceMap: Record<string, boolean>;
  traceContainerRef: React.RefObject<HTMLDivElement>;
  openMessageDetail: (messageItem: PushMessage) => void;
  closeDetail: () => void;
  toggleTracePanel: (key: string, active: boolean) => void;
  copyTraceBlock: (text: string) => Promise<void>;
  handleTraceScroll: (scrollTop: number) => void;
}

export function useTraceViewer(
  markMessageAsRead: (id: string) => void,
): TraceViewerState {
  const { t } = useTranslation();
  const [detailOpen, setDetailOpen] = useState(false);
  const [selectedMessage, setSelectedMessage] = useState<PushMessage | null>(
    null,
  );
  const [traceLoading, setTraceLoading] = useState(false);
  const [traceData, setTraceData] = useState<TraceData | null>(null);
  const [expandedTraceMap, setExpandedTraceMap] = useState<
    Record<string, boolean>
  >({});
  const traceContainerRef = useRef<HTMLDivElement>(null);
  const traceScrollTopByMessageRef = useRef<Record<string, number>>({});

  const traceEvents = useMemo<TraceDisplayItem[]>(() => {
    if (!traceData?.events?.length) return [];
    return buildTraceDisplayItems(traceData.events);
  }, [traceData]);

  // Reset expanded state when trace data or modal open state changes
  useEffect(() => {
    setExpandedTraceMap({});
  }, [traceData, detailOpen]);

  // Auto-scroll to bottom (or saved position) when trace loads
  useEffect(() => {
    if (
      !detailOpen ||
      traceLoading ||
      traceEvents.length <= 0 ||
      !selectedMessage
    ) {
      return;
    }
    const messageId = selectedMessage.id;
    const savedScrollTop = traceScrollTopByMessageRef.current[messageId];
    const rafId = window.requestAnimationFrame(() => {
      const container = traceContainerRef.current;
      if (!container) return;
      container.scrollTop =
        typeof savedScrollTop === "number"
          ? savedScrollTop
          : container.scrollHeight;
    });
    return () => window.cancelAnimationFrame(rafId);
  }, [detailOpen, selectedMessage, traceEvents.length, traceLoading]);

  const openMessageDetail = useCallback(
    (messageItem: PushMessage) => {
      if (!messageItem.read) {
        markMessageAsRead(messageItem.id);
      }
      setSelectedMessage(
        messageItem.read ? messageItem : { ...messageItem, read: true },
      );
      setDetailOpen(true);

      const runId =
        typeof messageItem.metadata?.payload?.run_id === "string"
          ? (messageItem.metadata.payload.run_id as string)
          : undefined;
      if (!runId) {
        setTraceData(buildContentFallbackTrace(messageItem));
        return;
      }
      setTraceLoading(true);
      void api
        .getInboxTrace(runId)
        .then((trace) => {
          setTraceData({ events: trace.events || [] });
        })
        .catch(() => {
          setTraceData(buildContentFallbackTrace(messageItem));
        })
        .finally(() => setTraceLoading(false));
    },
    [markMessageAsRead],
  );

  const closeDetail = useCallback(() => {
    setDetailOpen(false);
  }, []);

  const toggleTracePanel = useCallback((key: string, active: boolean) => {
    setExpandedTraceMap((prev) => ({ ...prev, [key]: active }));
  }, []);

  const copyTraceBlock = useCallback(
    async (text: string) => {
      if (!text) return;
      try {
        await navigator.clipboard.writeText(text);
        message.success(t("common.copied"));
      } catch {
        message.error(t("common.copyFailed"));
      }
    },
    [t],
  );

  const handleTraceScroll = useCallback(
    (scrollTop: number) => {
      if (!selectedMessage) return;
      traceScrollTopByMessageRef.current[selectedMessage.id] = scrollTop;
    },
    [selectedMessage],
  );

  return {
    detailOpen,
    selectedMessage,
    traceLoading,
    traceEvents,
    expandedTraceMap,
    traceContainerRef,
    openMessageDetail,
    closeDetail,
    toggleTracePanel,
    copyTraceBlock,
    handleTraceScroll,
  };
}
