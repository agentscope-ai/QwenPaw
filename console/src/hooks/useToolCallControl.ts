import { useCallback, useEffect, useRef, useState } from "react";
import { toolCallsApi } from "../api/modules/toolCalls";
import { resolveBackendSessionId } from "../utils/resolveBackendSessionId";
import { registerBackgroundTask } from "./useBackgroundTaskWatcher";
import { useBackgroundTasksStore } from "../stores/backgroundTasksStore";

const AUTO_POPUP_SECS = 30;
/** Minimum foreground runtime before auto-opening the control panel. */
const MIN_FOREGROUND_SECS = 15;
const OFFLOAD_POLL_MS = 2000;

export interface ToolCallControlState {
  bannerVisible: boolean;
  offloadRemaining: number | null;
  killRemaining: number | null;
  autoTriggered: boolean;
  isBackground: boolean;
  bgElapsed: number;
  defaultPolicy: "offload" | "keep_foreground";
  /** Absolute hard cap from tool start; null when uncapped. */
  maxInternalTimeoutSecs: number | null;
  /** Seconds since tool start (from last backend snapshot + local tick). */
  elapsed: number;
}

function resolveSessionId(sessionId: string): string {
  return resolveBackendSessionId(sessionId);
}

export function useToolCallControl(
  sessionId: string,
  toolCallId: string | undefined,
  isCalling: boolean,
  toolName?: string,
) {
  const [state, setState] = useState<ToolCallControlState>({
    bannerVisible: false,
    offloadRemaining: null,
    killRemaining: null,
    autoTriggered: false,
    isBackground: false,
    bgElapsed: 0,
    defaultPolicy: "keep_foreground",
    maxInternalTimeoutSecs: null,
    elapsed: 0,
  });

  const timerRef = useRef<ReturnType<typeof setInterval>>();
  const serverOffloadRef = useRef<number | null>(null);
  const serverKillRef = useRef<number | null>(null);
  const serverElapsedRef = useRef(0);
  const serverTimestampRef = useRef<number>(0);
  const fetchedRef = useRef(false);
  const autoTriggeredRef = useRef(false);
  const autoOffloadRegisteredRef = useRef(false);
  /** First positive offload_remaining seen for this call (popup gating). */
  const initialOffloadRef = useRef<number | null>(null);
  const defaultPolicyRef = useRef<"offload" | "keep_foreground">(
    "keep_foreground",
  );
  const toolNameRef = useRef(toolName || toolCallId || "");
  toolNameRef.current = toolName || toolCallId || "";
  const prevCallingRef = useRef(false);

  const tryRegisterBackground = useCallback(
    (reason: string) => {
      if (autoOffloadRegisteredRef.current || !toolCallId) return false;
      if (
        useBackgroundTasksStore
          .getState()
          .tasks.some((t) => t.toolCallId === toolCallId)
      ) {
        autoOffloadRegisteredRef.current = true;
        return true;
      }
      autoOffloadRegisteredRef.current = true;
      void reason;
      registerBackgroundTask({
        sessionId: resolveSessionId(sessionId),
        toolCallId,
        toolName: toolNameRef.current || toolCallId,
      });
      setState((s) => ({
        ...s,
        isBackground: true,
        bannerVisible: false,
      }));
      return true;
    },
    [sessionId, toolCallId],
  );

  const startLocalCountdown = useCallback(() => {
    if (timerRef.current) {
      clearInterval(timerRef.current);
      timerRef.current = undefined;
    }
    const hasOffload =
      serverOffloadRef.current !== null && serverOffloadRef.current > 0;
    const hasKill = serverKillRef.current !== null && serverKillRef.current > 0;
    // Keep ticking while either deadline is still live (keep_foreground may
    // clear offload while kill_remaining must continue).
    if (!hasOffload && !hasKill) {
      return;
    }

    timerRef.current = setInterval(() => {
      const elapsed = (performance.now() - serverTimestampRef.current) / 1000;
      const offR =
        serverOffloadRef.current !== null
          ? Math.max(0, serverOffloadRef.current - elapsed)
          : null;
      const killR =
        serverKillRef.current !== null
          ? Math.max(0, serverKillRef.current - elapsed)
          : null;

      setState((s) => {
        const totalElapsed = serverElapsedRef.current + elapsed;
        const initial = initialOffloadRef.current;
        const minWait =
          initial == null
            ? MIN_FOREGROUND_SECS
            : Math.min(MIN_FOREGROUND_SECS, initial * 0.5);
        // Require real foreground runtime so short tools (curl) do not flash
        // the panel when the whole offload window is already ≤ AUTO_POPUP_SECS.
        const shouldAutoPopup =
          offR !== null &&
          offR <= AUTO_POPUP_SECS &&
          offR > 0 &&
          totalElapsed >= minWait &&
          !s.bannerVisible &&
          !autoTriggeredRef.current;

        if (shouldAutoPopup) {
          autoTriggeredRef.current = true;
        }

        return {
          ...s,
          offloadRemaining: offR,
          killRemaining: killR,
          elapsed: totalElapsed,
          bannerVisible: shouldAutoPopup ? true : s.bannerVisible,
          autoTriggered: shouldAutoPopup ? true : s.autoTriggered,
        };
      });

      if (offR !== null && offR <= 0) {
        // Offload policy: hide the banner locally; registration still waits
        // for backend "offloaded". keep_foreground: leave the banner mounted
        // so OffloadBanner can dismiss itself (toast + collapse) when the
        // countdown / server-cleared deadline ends.
        if (defaultPolicyRef.current === "offload") {
          setState((s) =>
            s.bannerVisible ? { ...s, bannerVisible: false } : s,
          );
        }
        // Stop only when kill countdown is also done/absent.
        if (killR === null || killR <= 0) {
          if (timerRef.current) {
            clearInterval(timerRef.current);
            timerRef.current = undefined;
          }
        }
      } else if (killR !== null && killR <= 0 && (offR === null || offR <= 0)) {
        if (timerRef.current) {
          clearInterval(timerRef.current);
          timerRef.current = undefined;
        }
      }
    }, 1000);
  }, []);

  const applyServerValues = useCallback(
    (
      offload: number | null,
      kill: number | null,
      opts?: {
        elapsed?: number;
        maxInternalTimeoutSecs?: number | null;
      },
    ) => {
      serverOffloadRef.current = offload;
      serverKillRef.current = kill;
      if (offload != null && offload > 0 && initialOffloadRef.current == null) {
        initialOffloadRef.current = offload;
      }
      if (opts?.elapsed != null) {
        serverElapsedRef.current = opts.elapsed;
      }
      serverTimestampRef.current = performance.now();
      setState((s) => ({
        ...s,
        offloadRemaining: offload,
        killRemaining: kill,
        elapsed: opts?.elapsed != null ? opts.elapsed : s.elapsed,
        maxInternalTimeoutSecs:
          opts?.maxInternalTimeoutSecs !== undefined
            ? opts.maxInternalTimeoutSecs
            : s.maxInternalTimeoutSecs,
      }));
      startLocalCountdown();
    },
    [startLocalCountdown],
  );

  // Fetch deadlines when the tool starts. Backend session_id may not be ready
  // on the first paint (new chat / mapping lag) — retry like bg-task hydrate
  // instead of permanently locking fetchedRef after a failed/empty attempt.
  useEffect(() => {
    if (!isCalling || !toolCallId) return;

    fetchedRef.current = false;
    autoOffloadRegisteredRef.current = false;
    initialOffloadRef.current = null;
    autoTriggeredRef.current = false;
    let cancelled = false;
    let attempts = 0;
    let policyLoaded = false;

    const tryFetch = async () => {
      if (cancelled || fetchedRef.current) return;

      const sid = resolveSessionId(sessionId);
      const infoPromise = sid
        ? toolCallsApi.getInfo(sid, toolCallId).catch(() => null)
        : Promise.resolve(null);
      const policyPromise = policyLoaded
        ? Promise.resolve(null)
        : toolCallsApi.getOffloadPolicy().catch(() => null);

      const [info, policy] = await Promise.all([infoPromise, policyPromise]);
      if (cancelled) return;

      if (policy) {
        policyLoaded = true;
        const dp =
          (policy.default_action as "offload" | "keep_foreground") ??
          "keep_foreground";
        defaultPolicyRef.current = dp;
        setState((s) => ({ ...s, defaultPolicy: dp }));
      }

      if (!info) return;

      fetchedRef.current = true;
      if (info.status === "offloaded") {
        tryRegisterBackground("initial-getInfo-offloaded");
      }
      applyServerValues(
        info.offload_remaining ?? null,
        info.kill_remaining ?? null,
        {
          elapsed: info.elapsed ?? 0,
          maxInternalTimeoutSecs: info.max_internal_timeout_secs ?? null,
        },
      );
    };

    void tryFetch();
    const timer = setInterval(() => {
      attempts += 1;
      if (fetchedRef.current || attempts >= 20) {
        clearInterval(timer);
        return;
      }
      void tryFetch();
    }, 250);

    return () => {
      cancelled = true;
      clearInterval(timer);
    };
  }, [
    isCalling,
    sessionId,
    toolCallId,
    applyServerValues,
    tryRegisterBackground,
  ]);

  // Poll backend status while calling — catches system auto-offload even when
  // the tool card leaves "calling" before the local countdown hits zero.
  useEffect(() => {
    if (!isCalling || !toolCallId) return;

    let cancelled = false;
    const poll = async () => {
      if (cancelled || autoOffloadRegisteredRef.current) return;
      const sid = resolveSessionId(sessionId);
      if (!sid) return;
      try {
        const info = await toolCallsApi.getInfo(sid, toolCallId);
        if (cancelled) return;
        if (info.status === "offloaded") {
          tryRegisterBackground("poll-offloaded");
          return;
        }
        if (info.status === "running") {
          // Refresh remaining so kill countdown stays correct after offload
          // deadline clears under keep_foreground.
          applyServerValues(
            info.offload_remaining ?? null,
            info.kill_remaining ?? null,
            {
              elapsed: info.elapsed ?? 0,
              maxInternalTimeoutSecs: info.max_internal_timeout_secs ?? null,
            },
          );
        }
      } catch {
        /* ignore transient errors */
      }
    };

    void poll();
    const id = setInterval(poll, OFFLOAD_POLL_MS);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, [
    isCalling,
    sessionId,
    toolCallId,
    tryRegisterBackground,
    applyServerValues,
  ]);

  // When the card leaves "calling" (offloaded ToolResponse often flips status
  // immediately), register if the offload deadline was reached / backend says so.
  useEffect(() => {
    const wasCalling = prevCallingRef.current;
    prevCallingRef.current = isCalling;

    if (isCalling) return;

    if (timerRef.current) {
      clearInterval(timerRef.current);
      timerRef.current = undefined;
    }

    if (!wasCalling || !toolCallId || autoOffloadRegisteredRef.current) {
      fetchedRef.current = false;
      autoTriggeredRef.current = false;
      initialOffloadRef.current = null;
      return;
    }

    // Only register after the backend confirms offloaded — local countdown
    // reaching zero is not sufficient (policy changes / clock skew).
    const sid = resolveSessionId(sessionId);
    if (sid) {
      void toolCallsApi
        .getInfo(sid, toolCallId)
        .then((info) => {
          // Only background-queue registrations belong here. Foreground
          // success/cancel must not appear in the bg task panel.
          if (info.status === "offloaded") {
            tryRegisterBackground("leave-calling-getInfo");
          } else if (
            info.status === "completed" &&
            info.offload_reason != null
          ) {
            // Fast bg finish race: offloaded then completed before poll saw
            // "offloaded" — still hydrate /output into the bg panel.
            if (autoOffloadRegisteredRef.current) return;
            autoOffloadRegisteredRef.current = true;
            registerBackgroundTask({
              sessionId: sid,
              toolCallId,
              toolName: toolNameRef.current || toolCallId,
              alreadyCompleted: true,
            });
            setState((s) => ({
              ...s,
              isBackground: true,
              bannerVisible: false,
            }));
          }
        })
        .catch(() => {
          /* network blip — poll path may still catch offload */
        });
    }

    fetchedRef.current = false;
    autoTriggeredRef.current = false;
    initialOffloadRef.current = null;
  }, [isCalling, sessionId, toolCallId, tryRegisterBackground]);

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      if (timerRef.current) clearInterval(timerRef.current);
    };
  }, []);

  const toggleBanner = useCallback(() => {
    setState((s) => ({ ...s, bannerVisible: !s.bannerVisible }));
  }, []);

  const closeBanner = useCallback(() => {
    setState((s) => ({ ...s, bannerVisible: false }));
  }, []);

  const updateRemaining = useCallback(
    (
      offload: number | null,
      kill: number | null,
      opts?: {
        elapsed?: number;
        maxInternalTimeoutSecs?: number | null;
      },
    ) => {
      applyServerValues(offload, kill, opts);
    },
    [applyServerValues],
  );

  const setBackground = useCallback((elapsed: number) => {
    setState((s) => ({
      ...s,
      isBackground: true,
      bgElapsed: elapsed,
      bannerVisible: false,
    }));
  }, []);

  return {
    ...state,
    toggleBanner,
    closeBanner,
    updateRemaining,
    setBackground,
  };
}
