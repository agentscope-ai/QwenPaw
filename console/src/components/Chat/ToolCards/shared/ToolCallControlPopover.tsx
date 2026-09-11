/**
 * OffloadBanner — renders below the tool card as a horizontal panel.
 *
 * Button set and countdown copy branch on effective mode:
 * - auto-offload armed (policy offload + active deadline): offload decision UX
 * - otherwise: foreground UX (keep policy, or offload deadline cleared / prevented)
 *
 * Countdown appears once in the header: ring + short caption (no footer duplicate).
 */

import React, { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { message } from "antd";
import { Clock3, Hourglass, Moon, RefreshCw, X } from "lucide-react";
import { toolCallsApi } from "../../../../api/modules/toolCalls";
import { registerBackgroundTask } from "../../../../hooks/useBackgroundTaskWatcher";
import styles from "./offloadBanner.module.less";

function controlActionErrorMessage(
  err: unknown,
  t: (key: string, fallback: string) => string,
): string {
  const msg = err instanceof Error ? err.message : String(err ?? "");
  if (
    /\b404\b/.test(msg) ||
    /not found/i.test(msg) ||
    /tool call not found/i.test(msg)
  ) {
    return t(
      "tool.control.toast.notFound",
      "Tool call not found (it may have already finished).",
    );
  }
  if (
    /\b409\b/.test(msg) ||
    /cannot offload/i.test(msg) ||
    /cannot cancel/i.test(msg) ||
    /cannot extend/i.test(msg)
  ) {
    return t(
      "tool.control.toast.conflict",
      "Action rejected (tool state changed or limit reached).",
    );
  }
  if (
    /failed to fetch/i.test(msg) ||
    /networkerror/i.test(msg) ||
    /network request failed/i.test(msg)
  ) {
    return t(
      "tool.control.toast.networkError",
      "Network error. Check your connection and try again.",
    );
  }
  return t(
    "tool.control.toast.actionFailed",
    "Action failed. The tool may have finished or the request was rejected.",
  );
}

const CIRCUMFERENCE = 2 * Math.PI * 10;
const EXTEND_KILL_SECS = 30;

interface OffloadBannerProps {
  sessionId: string;
  toolCallId: string;
  toolName: string;
  offloadRemaining: number | null;
  killRemaining: number | null;
  totalSeconds: number;
  defaultPolicy: "offload" | "keep_foreground";
  /** Absolute hard cap from tool start; null/undefined when uncapped. */
  maxInternalTimeoutSecs?: number | null;
  elapsed?: number;
  onClose: () => void;
  onUpdateRemaining: (offload: number | null, kill: number | null) => void;
}

export const OffloadBanner: React.FC<OffloadBannerProps> = ({
  sessionId,
  toolCallId,
  toolName,
  offloadRemaining,
  killRemaining,
  totalSeconds,
  defaultPolicy,
  maxInternalTimeoutSecs = null,
  elapsed = 0,
  onClose,
  onUpdateRemaining,
}) => {
  const { t } = useTranslation();
  const isOffloadPolicy = defaultPolicy === "offload";
  const [collapsing, setCollapsing] = useState(false);
  const [displaySecs, setDisplaySecs] = useState(
    offloadRemaining !== null ? Math.ceil(offloadRemaining) : 0,
  );
  const startTimeRef = useRef(performance.now());
  const startSecsRef = useRef(displaySecs);
  const timerRef = useRef<ReturnType<typeof setInterval>>();
  const [busy, setBusy] = useState<string | null>(null);

  const hasCountdown = offloadRemaining !== null && offloadRemaining > 0;
  // Policy may still be "offload", but after "don't auto-offload" the deadline
  // is cleared — switch copy/buttons to foreground mode.
  const autoOffloadArmed = isOffloadPolicy && hasCountdown;
  const showForegroundUi = !autoOffloadArmed;
  // Mirror coordinator cap: new kill = now/current + 30 must stay ≤ started+cap.
  const canExtendKill =
    maxInternalTimeoutSecs == null ||
    elapsed + (killRemaining ?? 0) + EXTEND_KILL_SECS <=
      maxInternalTimeoutSecs + 0.01;
  const prevOffloadRemainingRef = useRef(offloadRemaining);
  const dismissRef = useRef<(showToast?: boolean) => void>(() => {});

  const dismiss = (showToast = false) => {
    if (timerRef.current) clearInterval(timerRef.current);
    if (showToast) {
      // Countdown reached 0: only toast/register after backend confirms
      // offloaded (local timer alone can race policy changes).
      if (isOffloadPolicy) {
        void toolCallsApi
          .getInfo(sessionId, toolCallId)
          .then((info) => {
            // Fast bg finish may already be "completed" — only register when
            // the call was actually backgrounded (offload_reason set).
            if (info.status === "offloaded") {
              registerBackgroundTask({
                sessionId,
                toolCallId,
                toolName: toolName || toolCallId,
              });
              message.info(
                t(
                  "tool.control.offloadMode.toastAuto",
                  "Moved to background automatically",
                ),
              );
              return;
            }
            if (info.status === "completed" && info.offload_reason != null) {
              registerBackgroundTask({
                sessionId,
                toolCallId,
                toolName: toolName || toolCallId,
                alreadyCompleted: true,
              });
            }
          })
          .catch(() => {
            /* poll in useToolCallControl may still confirm shortly */
          });
      } else {
        message.info(
          t(
            "tool.control.keepMode.toastDismiss",
            "Reminder closed; tool keeps running in foreground",
          ),
        );
      }
    }
    setCollapsing(true);
    setTimeout(() => onClose(), 250);
  };
  dismissRef.current = dismiss;

  useEffect(() => {
    const prev = prevOffloadRemainingRef.current;
    prevOffloadRemainingRef.current = offloadRemaining;

    // keep_foreground: panel countdown is the offload window. When the
    // server clears that deadline (null) or it hits 0, auto-dismiss — do
    // not leave a countdown-less sticky panel. (offload policy + prevent
    // offload also clears the deadline but must keep the panel open.)
    if (
      !isOffloadPolicy &&
      prev != null &&
      prev > 0 &&
      (offloadRemaining === null || offloadRemaining <= 0)
    ) {
      dismissRef.current(true);
      return;
    }

    if (offloadRemaining === null || offloadRemaining <= 0) return;
    startTimeRef.current = performance.now();
    startSecsRef.current = Math.ceil(offloadRemaining);
    setDisplaySecs(startSecsRef.current);

    timerRef.current = setInterval(() => {
      const tickElapsed = (performance.now() - startTimeRef.current) / 1000;
      const remaining = Math.max(0, startSecsRef.current - tickElapsed);
      setDisplaySecs(Math.ceil(remaining));
      if (remaining <= 0) {
        clearInterval(timerRef.current);
        dismissRef.current(true);
      }
    }, 1000);

    return () => {
      if (timerRef.current) clearInterval(timerRef.current);
    };
  }, [offloadRemaining, isOffloadPolicy]);

  const withGuard = async (action: string, fn: () => Promise<void>) => {
    if (busy) return;
    setBusy(action);
    try {
      await fn();
    } catch (e) {
      console.error(`[OffloadBanner] ${action} failed:`, e);
      message.error(controlActionErrorMessage(e, t));
    } finally {
      setBusy(null);
    }
  };

  const handleBackground = () =>
    withGuard("offload", async () => {
      await toolCallsApi.offload(sessionId, toolCallId);
      registerBackgroundTask({
        sessionId,
        toolCallId,
        toolName: toolName || toolCallId,
      });
      message.success(
        t("tool.control.toast.offloaded", "Tool moved to background"),
      );
      dismiss();
    });

  const handlePreventOffload = () =>
    withGuard("keep", async () => {
      const res = await toolCallsApi.preventOffload(sessionId, toolCallId);
      onUpdateRemaining(res.offload_remaining, res.kill_remaining);
      message.info(t("tool.control.toast.keepWaiting", "Continuing to wait…"));
      // Stay open so title/footer switch to "won't auto-offload" in place.
    });

  const handleDelayOffload = () =>
    withGuard("extendOffload", async () => {
      const res = await toolCallsApi.extendOffload(sessionId, toolCallId, 30);
      onUpdateRemaining(res.offload_remaining, res.kill_remaining);
      message.info(
        t(
          "tool.control.toast.extended",
          "Offload delayed; will remind you in +30s",
        ),
      );
    });

  const handleExtendKill = () =>
    withGuard("extendKill", async () => {
      const res = await toolCallsApi.extendKill(
        sessionId,
        toolCallId,
        EXTEND_KILL_SECS,
      );
      onUpdateRemaining(res.offload_remaining, res.kill_remaining);
      message.info(
        t("tool.control.toast.killExtended", "Timeout extended by 30s"),
      );
    });

  const handleCancel = () =>
    withGuard("cancel", async () => {
      await toolCallsApi.cancel(sessionId, toolCallId);
      message.info(t("tool.control.toast.cancelled", "Tool call cancelled"));
      dismiss();
    });

  const total = hasCountdown ? totalSeconds : 1;
  const pct = hasCountdown ? displaySecs / total : 0;
  const offset = CIRCUMFERENCE * (1 - pct);
  const isUrgent = displaySecs <= 5;

  const title = autoOffloadArmed
    ? t(
        "tool.control.offloadMode.title",
        "Tool running longer — about to offload",
      )
    : isOffloadPolicy
    ? t("tool.control.offloadMode.preventedTitle", "Auto-offload disabled")
    : t("tool.control.keepMode.title", "Tool still running in foreground");

  const ringAria = autoOffloadArmed
    ? t("tool.control.offloadMode.ringAria", {
        seconds: displaySecs,
        defaultValue: "{{seconds}}s until auto-offload",
      })
    : t("tool.control.keepMode.ringAria", {
        seconds: displaySecs,
        defaultValue: "Panel closes in {{seconds}}s",
      });

  const countdownCaption = autoOffloadArmed
    ? t("tool.control.offloadMode.countdownCaption", "until auto-offload")
    : t("tool.control.keepMode.countdownCaption", "until panel closes");

  const footerNoCountdown = isOffloadPolicy
    ? t(
        "tool.control.offloadMode.preventedFooter",
        "Won't auto-offload; you can move to background or cancel",
      )
    : t(
        "tool.control.keepMode.footerNoCountdown",
        "Stays in foreground by default; you can offload anytime",
      );

  return (
    <div
      className={`${styles.offloadBanner} ${
        isOffloadPolicy ? styles.policyOffload : styles.policyKeep
      } ${collapsing ? styles.collapsing : ""}`}
    >
      <div className={styles.offloadBar}>
        <div className={styles.offloadInfo}>{title}</div>

        {hasCountdown ? (
          <div
            className={`${styles.timerCluster} ${
              isUrgent ? styles.urgent : ""
            }`}
            title={ringAria}
            aria-label={ringAria}
          >
            <div className={styles.timerRing}>
              <svg viewBox="0 0 26 26" width="26" height="26">
                <circle className={styles.ringBg} cx="13" cy="13" r="10" />
                <circle
                  className={`${styles.ringProgress} ${
                    isUrgent ? styles.urgent : ""
                  }`}
                  cx="13"
                  cy="13"
                  r="10"
                  style={{
                    strokeDasharray: CIRCUMFERENCE,
                    strokeDashoffset: offset,
                  }}
                />
              </svg>
              <div
                className={`${styles.timerCount} ${
                  isUrgent ? styles.urgent : ""
                }`}
              >
                {displaySecs}
              </div>
            </div>
            <span className={styles.timerCaption}>{countdownCaption}</span>
          </div>
        ) : null}
      </div>

      <div
        className={`${styles.offloadActions} ${
          showForegroundUi ? styles.actionsKeep : styles.actionsOffload
        }`}
      >
        {autoOffloadArmed ? (
          <>
            <button
              className={styles.offloadBtn}
              onClick={handleBackground}
              disabled={busy !== null}
              type="button"
            >
              <span className={styles.ico}>
                <Moon size={14} aria-hidden />
              </span>
              <span className={styles.btnLabel}>
                {t(
                  "tool.control.offloadMode.offloadNow",
                  "Move to background now",
                )}
              </span>
            </button>
            <button
              className={styles.offloadBtn}
              onClick={handlePreventOffload}
              disabled={busy !== null}
              type="button"
            >
              <span className={styles.ico}>
                <Hourglass size={14} aria-hidden />
              </span>
              <span className={styles.btnLabel}>
                {t(
                  "tool.control.offloadMode.preventOffload",
                  "Don't auto-offload",
                )}
              </span>
            </button>
            <button
              className={styles.offloadBtn}
              onClick={handleDelayOffload}
              disabled={busy !== null}
              type="button"
            >
              <span className={styles.ico}>
                <RefreshCw size={14} aria-hidden />
              </span>
              <span className={styles.btnLabel}>
                {t("tool.control.offloadMode.delayOffload", "Delay offload")}
              </span>
            </button>
            <button
              className={styles.offloadBtn}
              onClick={handleExtendKill}
              disabled={busy !== null || !canExtendKill}
              title={
                canExtendKill
                  ? undefined
                  : t(
                      "tool.control.toast.conflict",
                      "Action rejected (tool state changed or limit reached).",
                    )
              }
              type="button"
            >
              <span className={styles.ico}>
                <Clock3 size={14} aria-hidden />
              </span>
              <span className={styles.btnLabel}>
                {t("tool.control.extendKill", "Extend timeout")}
              </span>
            </button>
            <button
              className={`${styles.offloadBtn} ${styles.cancelAct}`}
              onClick={handleCancel}
              disabled={busy !== null}
              type="button"
            >
              <span className={styles.ico}>
                <X size={14} aria-hidden />
              </span>
              <span className={styles.btnLabel}>
                {t("tool.control.cancel")}
              </span>
            </button>
          </>
        ) : (
          <>
            <button
              className={`${styles.offloadBtn} ${styles.primaryAct}`}
              onClick={handleBackground}
              disabled={busy !== null}
              type="button"
            >
              <span className={styles.ico}>
                <Moon size={14} aria-hidden />
              </span>
              <span className={styles.btnLabel}>
                {t("tool.control.keepMode.offload", "Move to background")}
              </span>
            </button>
            <button
              className={styles.offloadBtn}
              onClick={handleExtendKill}
              disabled={busy !== null || !canExtendKill}
              title={
                canExtendKill
                  ? undefined
                  : t(
                      "tool.control.toast.conflict",
                      "Action rejected (tool state changed or limit reached).",
                    )
              }
              type="button"
            >
              <span className={styles.ico}>
                <Clock3 size={14} aria-hidden />
              </span>
              <span className={styles.btnLabel}>
                {t("tool.control.extendKill", "Extend timeout")}
              </span>
            </button>
            <button
              className={`${styles.offloadBtn} ${styles.cancelAct}`}
              onClick={handleCancel}
              disabled={busy !== null}
              type="button"
            >
              <span className={styles.ico}>
                <X size={14} aria-hidden />
              </span>
              <span className={styles.btnLabel}>
                {t("tool.control.cancel")}
              </span>
            </button>
          </>
        )}
      </div>

      {!hasCountdown && (
        <div className={styles.offloadNote}>
          <div className={styles.noteDot} />
          {footerNoCountdown}
        </div>
      )}
    </div>
  );
};
