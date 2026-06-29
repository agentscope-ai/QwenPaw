import React from "react";
import { Pause, Play, Square } from "lucide-react";
import { useLoopStore } from "../../stores/loopStore";
import styles from "./index.module.less";

/**
 * Persistent status bar shown above the sender when a loop is actively
 * running. Displays iteration count, budget usage, and pause/stop controls.
 */
export const LoopStatusBar: React.FC = () => {
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
          title={runtime.paused ? "Resume" : "Pause"}
          onClick={runtime.paused ? resumeLoop : pauseLoop}
        >
          {runtime.paused ? <Play size={12} /> : <Pause size={12} />}
        </button>
        <button
          className={`${styles.statusBtn} ${styles.statusBtnDanger}`}
          title="Stop"
          onClick={stopLoop}
        >
          <Square size={12} />
        </button>
      </div>
    </div>
  );
};
