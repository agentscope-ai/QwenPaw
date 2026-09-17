import { useState, useEffect, useCallback } from "react";

const STORAGE_KEY = "qwenpaw.inbox.approvalWobble";
const SYNC_EVENT = "qwenpaw:inbox-wobble-change";

/**
 * Shared hook for the "approval wobble notification" toggle.
 *
 * - Persisted in localStorage (default: **enabled**).
 * - Cross-component: when one component toggles, others react instantly
 *   via a CustomEvent on `window`.
 */
export function useInboxWobble(): [enabled: boolean, toggle: () => void] {
  const [enabled, setEnabled] = useState(
    () => localStorage.getItem(STORAGE_KEY) !== "false",
  );

  useEffect(() => {
    const sync = () =>
      setEnabled(localStorage.getItem(STORAGE_KEY) !== "false");
    window.addEventListener(SYNC_EVENT, sync);
    return () => window.removeEventListener(SYNC_EVENT, sync);
  }, []);

  const toggle = useCallback(() => {
    const next = localStorage.getItem(STORAGE_KEY) === "false";
    localStorage.setItem(STORAGE_KEY, String(next));
    setEnabled(next);
    window.dispatchEvent(new CustomEvent(SYNC_EVENT));
  }, []);

  return [enabled, toggle];
}
