import { useEffect, useRef, useState } from "react";
import { MessageCircle, X } from "lucide-react";
import { consoleApi, type PushMessage } from "../../api/modules/console";
import styles from "./index.module.less";

const POLL_INTERVAL_MS = 2500;
const AUTO_DISMISS_MS = 8000;
const MAX_SEEN_IDS = 500;
const MAX_VISIBLE_BUBBLES = 4;
const MAX_NEW_PER_POLL = 2;
const TITLE_BLINK_PREFIX = "\u2022 ";

interface BubbleItem extends PushMessage {
  dismissAt: number;
}

export default function ConsoleCronBubble() {
  const [items, setItems] = useState<BubbleItem[]>([]);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const seenIdsRef = useRef<Set<string>>(new Set());
  const originalTitleRef = useRef(document.title);
  const blinkRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const dismiss = (id: string) => {
    setItems((prev) => prev.filter((i) => i.id !== id));
  };

  useEffect(() => {
    originalTitleRef.current = document.title;
  }, []);

  useEffect(() => {
    const tick = () => {
      consoleApi
        .getPushMessages()
        .then((res) => {
          if (!res?.messages?.length) return;
          const seen = seenIdsRef.current;
          if (seen.size > MAX_SEEN_IDS) seen.clear();
          const newItems: BubbleItem[] = [];
          const now = Date.now();
          for (const m of res.messages) {
            if (seen.has(m.id)) continue;
            seen.add(m.id);
            newItems.push({ ...m, dismissAt: now + AUTO_DISMISS_MS });
          }
          if (newItems.length === 0) return;
          const toAdd = newItems.slice(-MAX_NEW_PER_POLL);
          setItems((prev) => {
            const merged = [...prev, ...toAdd];
            return merged.slice(-MAX_VISIBLE_BUBBLES);
          });
        })
        .catch(() => {});
    };

    tick();
    pollRef.current = setInterval(tick, POLL_INTERVAL_MS);
    return () => {
      if (pollRef.current) clearInterval(pollRef.current);
    };
  }, []);

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
    const original = originalTitleRef.current;
    let showPrefix = true;
    blinkRef.current = setInterval(() => {
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
      document.title = original;
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
