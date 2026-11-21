import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  useSyncExternalStore,
} from "react";
import { message } from "antd";
import { useTranslation } from "react-i18next";
import api from "../../../api";
import {
  getAccessSessionGeneration,
  subscribeAccessSessionGeneration,
} from "../../../api/authSession";
import { useAuthStore } from "../../../stores/authStore";
import type { PushMessage } from "../types";
import {
  buildContentFallbackTrace,
  buildTraceDisplayItems,
  type TraceDisplayItem,
} from "../utils/traceUtils";

interface TraceData {
  events: Array<{ at: number; event: Record<string, unknown> }>;
}

function getTraceIdentity() {
  const auth = useAuthStore.getState();
  return JSON.stringify([
    auth.mode,
    auth.phase,
    auth.user?.id,
    getAccessSessionGeneration(),
  ]);
}

function subscribeTraceIdentity(listener: () => void) {
  const unsubscribeUser = useAuthStore.subscribe(listener);
  const unsubscribeSession = subscribeAccessSessionGeneration(listener);
  return () => {
    unsubscribeUser();
    unsubscribeSession();
  };
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
  const identity = useSyncExternalStore(
    subscribeTraceIdentity,
    getTraceIdentity,
  );
  const [dataIdentity, setDataIdentity] = useState(identity);
  const currentIdentity = identity === dataIdentity;
  const sequence = useRef(0);
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

  useEffect(() => {
    sequence.current++;
    setDetailOpen(false);
    setSelectedMessage(null);
    setTraceLoading(false);
    setTraceData(null);
    setExpandedTraceMap({});
    traceScrollTopByMessageRef.current = {};
    setDataIdentity(identity);
    return () => {
      sequence.current++;
    };
  }, [identity]);

  const traceEvents = useMemo<TraceDisplayItem[]>(() => {
    if (!currentIdentity || !traceData?.events?.length) return [];
    return buildTraceDisplayItems(traceData.events);
  }, [traceData, currentIdentity]);

  // Reset expanded state when trace data or modal open state changes
  useEffect(() => {
    setExpandedTraceMap({});
  }, [traceData, detailOpen]);

  // Auto-scroll to bottom (or saved position) when trace loads
  useEffect(() => {
    if (
      !currentIdentity ||
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
  }, [
    currentIdentity,
    detailOpen,
    selectedMessage,
    traceEvents.length,
    traceLoading,
  ]);

  const openMessageDetail = useCallback(
    (messageItem: PushMessage) => {
      if (identity !== getTraceIdentity()) return;
      const requestSequence = ++sequence.current;
      const current = () =>
        identity === getTraceIdentity() && requestSequence === sequence.current;
      if (!messageItem.read) {
        markMessageAsRead(messageItem.id);
      }
      setSelectedMessage(
        messageItem.read ? messageItem : { ...messageItem, read: true },
      );
      setDetailOpen(true);
      setDataIdentity(identity);
      setTraceData(null);

      const runId =
        typeof messageItem.metadata?.payload?.run_id === "string"
          ? (messageItem.metadata.payload.run_id as string)
          : undefined;
      if (!runId) {
        setTraceLoading(false);
        setTraceData(buildContentFallbackTrace(messageItem));
        return;
      }
      setTraceLoading(true);
      void api
        .getInboxTrace(runId)
        .then((trace) => {
          if (current()) setTraceData({ events: trace.events || [] });
        })
        .catch(() => {
          if (current()) setTraceData(buildContentFallbackTrace(messageItem));
        })
        .finally(() => {
          if (current()) setTraceLoading(false);
        });
    },
    [identity, markMessageAsRead],
  );

  const closeDetail = useCallback(() => {
    sequence.current++;
    setDetailOpen(false);
    setSelectedMessage(null);
    setTraceData(null);
    setTraceLoading(false);
  }, []);

  const toggleTracePanel = useCallback((key: string, active: boolean) => {
    setExpandedTraceMap((prev) => ({ ...prev, [key]: active }));
  }, []);

  const copyTraceBlock = useCallback(
    async (text: string) => {
      if (!text || identity !== getTraceIdentity()) return;
      try {
        await navigator.clipboard.writeText(text);
        message.success(t("common.copied"));
      } catch {
        message.error(t("common.copyFailed"));
      }
    },
    [identity, t],
  );

  const handleTraceScroll = useCallback(
    (scrollTop: number) => {
      if (!selectedMessage) return;
      traceScrollTopByMessageRef.current[selectedMessage.id] = scrollTop;
    },
    [selectedMessage],
  );

  return {
    detailOpen: currentIdentity && detailOpen,
    selectedMessage: currentIdentity ? selectedMessage : null,
    traceLoading: currentIdentity && traceLoading,
    traceEvents,
    expandedTraceMap: currentIdentity ? expandedTraceMap : {},
    traceContainerRef,
    openMessageDetail,
    closeDetail,
    toggleTracePanel,
    copyTraceBlock,
    handleTraceScroll,
  };
}
