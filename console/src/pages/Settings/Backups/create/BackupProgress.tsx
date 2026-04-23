/**
 * Pure presentational component that displays a progress bar and a status
 * message during a backup stream. Used by both CreateBackupModal (while the
 * user waits after confirming) and SilentBackupModal (pre-restore snapshot).
 */
import { Progress, Typography } from "antd";
import styles from "./BackupProgress.module.less";

interface Props {
  progress: number;
  progressMsg: string;
}
export default function BackupProgress({ progress, progressMsg }: Props) {
  return (
    <div className={styles.wrapper}>
      <Progress
        percent={progress}
        status={progress < 100 ? "active" : "success"}
      />
      <Typography.Text type="secondary" className={styles.msg}>
        {progressMsg}
      </Typography.Text>
    </div>
  );
}
