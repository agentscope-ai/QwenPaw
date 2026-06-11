/**
 * Pure presentational component that displays a progress bar and a status
 * message during a backup stream. Used by both CreateBackupModal (while the
 * user waits after confirming) and SilentBackupModal (pre-restore snapshot).
 */
import styles from "./BackupProgress.module.less";

interface Props {
  progress: number;
  progressMsg: string;
}

export default function BackupProgress({ progress, progressMsg }: Props) {
  const isComplete = progress >= 100;
  return (
    <div className={styles.wrapper}>
      <div className="w-full rounded-full bg-muted h-2 overflow-hidden">
        <div
          className={`h-full rounded-full transition-all duration-300 ${
            isComplete ? "bg-green-500" : "bg-primary"
          }`}
          style={{ width: `${Math.min(progress, 100)}%` }}
        />
      </div>
      <p className={`${styles.msg} text-sm text-muted-foreground`}>
        {progressMsg}
      </p>
    </div>
  );
}
