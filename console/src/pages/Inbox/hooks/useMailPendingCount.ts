import { useCallback, useEffect, useRef, useState } from "react";
import { mailAccessControlApi } from "../../../api/modules/mailAccessControl";

const PENDING_POLLING_INTERVAL_MS = 6000;

/**
 * Polls the mail access control pending list and exposes:
 * - `pendingCount`: number of senders awaiting approval
 * - `newArrival`: true when a pending entry not yet "seen" appears
 * - `markSeen()`: mark all current pending entries as seen (stops wobble)
 * - `refresh()`: manually re-fetch the pending list
 */
export const useMailPendingCount = () => {
  const [pendingCount, setPendingCount] = useState(0);
  const [newArrival, setNewArrival] = useState(false);
  const currentKeysRef = useRef<Set<string>>(new Set());
  const seenKeysRef = useRef<Set<string>>(new Set());

  const refresh = useCallback(async () => {
    try {
      const entries = await mailAccessControlApi.getMailPendingAll();
      const list = entries || [];
      const currentKeys = new Set(
        list.map((entry) => `${entry.agent_id}:${entry.sender_address}`),
      );
      currentKeysRef.current = currentKeys;
      setPendingCount(list.length);
      const hasNew =
        currentKeys.size > 0 &&
        [...currentKeys].some((key) => !seenKeysRef.current.has(key));
      setNewArrival(hasNew);
    } catch (error) {
      // Keep previous state when polling fails.
      console.error("Failed to poll mail pending entries", error);
    }
  }, []);

  /** Mark current pending entries as "seen" so the wobble stops. */
  const markSeen = useCallback(() => {
    seenKeysRef.current = new Set(currentKeysRef.current);
    setNewArrival(false);
  }, []);

  useEffect(() => {
    void refresh();

    let timer: number | null = null;

    const startPolling = () => {
      if (timer) return;
      timer = window.setInterval(() => {
        void refresh();
      }, PENDING_POLLING_INTERVAL_MS);
    };

    const stopPolling = () => {
      if (timer) {
        window.clearInterval(timer);
        timer = null;
      }
    };

    const handleVisibilityChange = () => {
      if (document.visibilityState === "visible") {
        void refresh();
        startPolling();
      } else {
        stopPolling();
      }
    };

    if (document.visibilityState === "visible") {
      startPolling();
    }

    document.addEventListener("visibilitychange", handleVisibilityChange);
    return () => {
      stopPolling();
      document.removeEventListener("visibilitychange", handleVisibilityChange);
    };
  }, [refresh]);

  return { pendingCount, refresh, newArrival, markSeen };
};
