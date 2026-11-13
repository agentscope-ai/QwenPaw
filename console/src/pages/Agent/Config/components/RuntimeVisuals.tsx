import { retryDelays } from "./retryTiming";
import { motion, useReducedMotion } from "motion/react";
import NumberFlow from "@number-flow/react";
import { Form } from "antd";
import { useTranslation } from "react-i18next";
import styles from "./RuntimeVisuals.module.less";

export function ContextBudgetOverview({
  capacity,
  trigger,
  retained,
}: {
  capacity: number;
  trigger: number;
  retained: number;
}) {
  const { t } = useTranslation();
  const reduced = useReducedMotion();
  const triggerRatio = capacity > 0 ? Math.min(1, trigger / capacity) : 0;
  const retainedRatio = capacity > 0 ? Math.min(1, retained / capacity) : 0;
  return (
    <div className={styles.budget}>
      <div className={styles.capacity}>
        <span>{t("runtimeDesign.budgetTitle")}</span>
        <strong>
          <NumberFlow value={capacity} respectMotionPreference />
          <small>tokens</small>
        </strong>
      </div>
      <div className={styles.budgetRail} aria-hidden="true">
        <motion.div
          className={styles.used}
          animate={{ width: `${triggerRatio * 100}%` }}
          transition={{ duration: reduced ? 0 : 0.2 }}
        />
        <motion.div
          className={styles.retained}
          animate={{ width: `${retainedRatio * 100}%` }}
          transition={{ duration: reduced ? 0 : 0.2 }}
        />
        <motion.i
          animate={{ left: `${triggerRatio * 100}%` }}
          transition={{ duration: reduced ? 0 : 0.2 }}
        />
      </div>
      <div className={styles.legend}>
        <div>
          <span>{t("runtimeDesign.retained")}</span>
          <strong>
            <NumberFlow value={retained} respectMotionPreference />{" "}
            <small>tokens</small>
          </strong>
        </div>
        <div>
          <span>{t("runtimeDesign.trigger")}</span>
          <strong>
            <NumberFlow value={trigger} respectMotionPreference />{" "}
            <small>tokens</small>
          </strong>
        </div>
      </div>
      <p>{t("runtimeDesign.budgetHint")}</p>
    </div>
  );
}

export function RetryTimeline({ enabled }: { enabled: boolean }) {
  const { t } = useTranslation();
  const reduced = useReducedMotion();
  const retries = Form.useWatch("llm_max_retries") ?? 3;
  const base = Form.useWatch("llm_backoff_base") ?? 1;
  const cap = Form.useWatch("llm_backoff_cap") ?? 30;
  const delays = retryDelays(enabled ? retries : 0, base, cap);
  const max = Math.max(1, ...delays);
  return (
    <div className={styles.timeline}>
      <div className={styles.timelineHeader}>
        <span>{t("runtimeDesign.retryPreview")}</span>
        <span>{t("runtimeDesign.seconds")}</span>
      </div>
      <div className={styles.attempts}>
        {delays.map((delay, index) => (
          <div key={index} className={styles.attempt}>
            <span>
              <NumberFlow
                value={delay}
                format={{ maximumFractionDigits: 2 }}
                respectMotionPreference
              />
            </span>
            <motion.div
              animate={{ height: 12 + (delay / max) * 50 }}
              initial={false}
              transition={
                reduced
                  ? { duration: 0 }
                  : { type: "spring", stiffness: 280, damping: 30 }
              }
            />
            <small>
              {t("runtimeDesign.retryAttempt", { count: index + 1 })}
            </small>
          </div>
        ))}
        {enabled && retries > 8 && (
          <span className={styles.remaining}>+{retries - 8}</span>
        )}
        {!enabled && (
          <span className={styles.remaining}>{t("common.disabled")}</span>
        )}
      </div>
      <p>{t("runtimeDesign.retryHint")}</p>
    </div>
  );
}
