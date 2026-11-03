import { useEffect, useRef, useState } from "react";
import { MessageCircle, X } from "lucide-react";
import { consoleApi, type PushMessage } from "../../api/modules/console";
import { useApprovalContext } from "../../contexts/ApprovalContext";
import styles from "./index.module.less";

const POLL_INTERVAL_MS = 2500;
const BACKGROUND_POLL_INTERVAL_MS = 30000;
const AUTO_DISMISS_MS = 8000;
const MAX_SEEN_IDS = 500;
const MAX_VISIBLE_BUBBLES = 4;
const MAX_NEW_PER_POLL = 2;
const TITLE_BLINK_PREFIX = "\u2022 ";

interface BubbleItem extends PushMessage {
  dismissAt: number;
}

export default function ConsolePollService() {
  const [items, setItems] = useState<BubbleItem[]>([]);
  const pollRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const seenIdsRef = useRef<Set<string>>(new Set());
  const originalTitleRef = useRef(document.title);
  const blinkRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const { setApprovals } = useApprovalContext();

  const dismiss = (id: string) => {
    setItems((prev) => prev.filter((i) => i.id !== id));
  };

  useEffect(() => {
    originalTitleRef.current = document.title;
    const onDocumentTitleChange = (event: Event) => {
      originalTitleRef.current = (event as CustomEvent<string>).detail;
    };
    document.addEventListener(
      "qwenpaw:document-title-change",
      onDocumentTitleChange,
    );
    return () => {
      document.removeEventListener(
        "qwenpaw:document-title-change",
        onDocumentTitleChange,
      );
    };
  }, []);

  useEffect(() => {
    let cancelled = false;
    let inFlight = false;
    let refreshAfterFlight = false;
    const prevApprovalsRef = { current: "" };
    const clearScheduledPoll = () => {
      if (!pollRef.current) return;
      clearTimeout(pollRef.current);
      pollRef.current = null;
    };

    const scheduleNextPoll = (delay?: number) => {
      if (cancelled) return;
      clearScheduledPoll();
      const nextDelay =
        delay ??
        (document.hidden ? BACKGROUND_POLL_INTERVAL_MS : POLL_INTERVAL_MS);
      pollRef.current = setTimeout(() => {
        pollRef.current = null;
        void tick();
      }, nextDelay);
    };

    const tick = async () => {
      if (cancelled) return;
      if (inFlight) {
        refreshAfterFlight = true;
        return;
      }

      inFlight = true;
      try {
        const res = await consoleApi.getPushMessages();
        if (cancelled) return;

        // Update pending approvals only when they actually change,
        // to avoid triggering unnecessary re-renders in Chat component.
        if (res?.pending_approvals) {
          const serialized = JSON.stringify(res.pending_approvals);
          if (serialized !== prevApprovalsRef.current) {
            prevApprovalsRef.current = serialized;
            setApprovals(res.pending_approvals);
          }
        }

        // Update message bubbles.
        if (res?.messages?.length) {
          const seen = seenIdsRef.current;
          if (seen.size > MAX_SEEN_IDS) seen.clear();
          const newItems: BubbleItem[] = [];
          const now = Date.now();
          for (const m of res.messages) {
            if (seen.has(m.id)) continue;
            seen.add(m.id);
            newItems.push({ ...m, dismissAt: now + AUTO_DISMISS_MS });
          }
          if (newItems.length > 0) {
            const toAdd = newItems.slice(-MAX_NEW_PER_POLL);
            setItems((prev) => {
              const merged = [...prev, ...toAdd];
              return merged.slice(-MAX_VISIBLE_BUBBLES);
            });
          }
        }
      } catch {
        // Polling is best-effort; the next scheduled request retries.
      } finally {
        inFlight = false;
        if (!cancelled) {
          if (refreshAfterFlight) {
            refreshAfterFlight = false;
            scheduleNextPoll(0);
          } else {
            scheduleNextPoll();
          }
        }
      }
    };

    const onVisibility = () => {
      clearScheduledPoll();
      if (document.hidden) {
        refreshAfterFlight = false;
        if (!inFlight) scheduleNextPoll(BACKGROUND_POLL_INTERVAL_MS);
        return;
      }
      if (inFlight) {
        refreshAfterFlight = true;
      } else {
        void tick();
      }
    };

    document.addEventListener("visibilitychange", onVisibility);
    void tick();
    return () => {
      cancelled = true;
      clearScheduledPoll();
      document.removeEventListener("visibilitychange", onVisibility);
    };
  }, [setApprovals]);

  useEffect(() => {
    if (items.length === 0) return;
    const t = setInterval(() => {
      const now = Date.now();
      setItems((prev) => {
        const next = prev.filter((i) => i.dismissAt > now);
        return next.length === prev.length ? prev : next;
      });
    }, 500);
    return () => clearInterval(t);
  }, [items.length]);

  useEffect(() => {
    if (items.length === 0 || !document.hidden || blinkRef.current) return;
    let showPrefix = true;
    blinkRef.current = setInterval(() => {
      const original = originalTitleRef.current;
      document.title = showPrefix
        ? `${TITLE_BLINK_PREFIX}${original}`
        : original;
      showPrefix = !showPrefix;
    }, 800);
    return () => {
      if (blinkRef.current) {
        clearInterval(blinkRef.current);
        blinkRef.current = null;
      }
      document.title = originalTitleRef.current;
    };
  }, [items.length]);

  useEffect(() => {
    const onVisibility = () => {
      if (document.visibilityState === "visible") {
        if (blinkRef.current) {
          clearInterval(blinkRef.current);
          blinkRef.current = null;
        }
        document.title = originalTitleRef.current;
      }
    };
    document.addEventListener("visibilitychange", onVisibility);
    return () => document.removeEventListener("visibilitychange", onVisibility);
  }, []);

  if (items.length === 0) return null;

  return (
    <div className={styles.wrap} role="region" aria-label="Cron messages">
      {items.map((item) => (
        <div key={item.id} className={styles.bubble}>
          <MessageCircle size={18} className={styles.icon} aria-hidden />
          <p className={styles.text} title={item.text}>
            {item.text}
          </p>
          <button
            type="button"
            className={styles.close}
            onClick={() => dismiss(item.id)}
            aria-label="Close"
          >
            <X size={14} />
          </button>
        </div>
      ))}
    </div>
  );
}
