import React from "react";
import { Pause, Play, Square } from "lucide-react";
import { useTranslation } from "react-i18next";
import { useLoopStore } from "../../stores/loopStore";
import styles from "./index.module.less";

export const LoopStatusBar: React.FC = () => {
  const { t } = useTranslation();
  const { runtime, pauseLoop, resumeLoop, stopLoop } = useLoopStore();

  if (!runtime) return null;

  const percent = runtime.budgetUsedPercent;
  const progressColor =
    percent >= 80
      ? styles.progressFillRed
      : percent >= 50
      ? styles.progressFillYellow
      : styles.progressFillGreen;

  const dotCls = [styles.pulseDot, runtime.paused ? styles.pulseDotPaused : ""]
    .filter(Boolean)
    .join(" ");

  return (
    <div className={styles.loopStatusBar}>
      <div className={styles.statusBadge}>
        <span className={dotCls} />/{runtime.skillName}
      </div>
      <div className={styles.statusInfo}>{runtime.statusText}</div>
      <div className={styles.budgetProgress}>
        <div className={styles.progressBar}>
          <div
            className={`${styles.progressFill} ${progressColor}`}
            style={{ width: `${percent}%` }}
          />
        </div>
        <span className={styles.progressText}>{percent}%</span>
      </div>
      <div className={styles.statusActions}>
        <button
          className={styles.statusBtn}
          title={
            runtime.paused ? t("loop.status.resume") : t("loop.status.pause")
          }
          onClick={runtime.paused ? resumeLoop : pauseLoop}
        >
          {runtime.paused ? <Play size={12} /> : <Pause size={12} />}
        </button>
        <button
          className={`${styles.statusBtn} ${styles.statusBtnDanger}`}
          title={t("loop.status.stop")}
          onClick={stopLoop}
        >
          <Square size={12} />
        </button>
      </div>
    </div>
  );
};
