import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import {
  useCreatorSessionStore,
  type RateLimitRetryState,
} from "@/store/creatorSessionStore";

/** Backoff is derived from the real event; it is never a generation ETA. */
export default function AgentWaitHint({
  projectId,
  active,
  retrying,
  retry,
  others = [],
}: {
  projectId: string;
  active: boolean;
  retrying: boolean;
  retry?: RateLimitRetryState | null;
  others?: Array<RateLimitRetryState & { label: string }>;
}) {
  const { t } = useTranslation();
  const connection = useCreatorSessionStore((state) => state.connectionState);
  const [longWait, setLongWait] = useState(false);
  const [now, setNow] = useState(Date.now);
  useEffect(() => {
    setLongWait(false);
    if (!active) return;
    const timer = window.setTimeout(() => setLongWait(true), 30_000);
    return () => window.clearTimeout(timer);
  }, [active, projectId]);
  useEffect(() => {
    setNow(Date.now());
    if (!retry && !others.length) return;
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, [retry, others.length, projectId]);
  const reconnecting = connection === "reconnecting";
  if (!active && !reconnecting && !retrying && !others.length) return null;
  const retries = [...(retry ? [{ ...retry, label: "" }] : []), ...others];
  return (
    <div
      data-agent-wait-hint
      className={retries.length ? "agent-retry-notice" : "agent-wait-hint"}
    >
      {retries.map((notice) => {
        const started = notice.createdAt ? Date.parse(notice.createdAt) : NaN;
        const remaining =
          notice.delaySeconds != null && Number.isFinite(started)
            ? Math.max(
                0,
                Math.ceil((started + notice.delaySeconds * 1000 - now) / 1000),
              )
            : null;
        return (
          <div
            key={notice.runId}
            data-agent-retry-notice={notice.reason ?? "rate_limit"}
            role="status"
          >
            <p className="agent-retry-title">
              {notice.label && `${notice.label} · `}
              {t(`agentRetry.${notice.reason ?? "rate_limit"}`)}
            </p>
            <p className="agent-retry-detail">
              {t("agentRetry.attempt", {
                attempt: notice.attempt,
                max: notice.maxAttempts,
              })}
              {remaining != null && (
                <span className="tabular-nums">
                  {" "}
                  ·{" "}
                  {t(
                    remaining > 0
                      ? "agentRetry.backoff"
                      : "agentRetry.responding",
                    { seconds: remaining },
                  )}
                </span>
              )}
            </p>
          </div>
        );
      })}
      {(!retries.length || reconnecting) && (
        <p>
          {t(
            reconnecting
              ? "agentActivity.connectionHint"
              : retrying
              ? "agentActivity.retryHint"
              : longWait
              ? "agentActivity.longWaitHint"
              : "agentActivity.workingHint",
          )}
        </p>
      )}
    </div>
  );
}
