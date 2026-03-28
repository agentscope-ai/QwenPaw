import { memo } from "react";
import { Button, Tooltip } from "@agentscope-ai/design";
import { CloseOutlined, DownloadOutlined } from "@ant-design/icons";
import { useTranslation } from "react-i18next";
import type {
  LocalDownloadProgress,
  LocalServerStatus,
} from "../../../../../../api/types";
import styles from "../../../index.module.less";
import { formatProgressText, getProgressPercent } from "./shared";

interface LocalRuntimePanelProps {
  serverStatus: LocalServerStatus | null;
  progress: LocalDownloadProgress | null;
  onStart: () => void;
  onCancel: () => void;
  onStop: () => void;
  stopping: boolean;
}

export const LocalRuntimePanel = memo(function LocalRuntimePanel({
  serverStatus,
  progress,
  onStart,
  onCancel,
}: LocalRuntimePanelProps) {
  const { t } = useTranslation();
  const installed = Boolean(serverStatus?.installed);
  const isDownloading =
    progress?.status === "pending" || progress?.status === "downloading";
  const isRunning = Boolean(serverStatus?.model_name);
  const installBadge = installed
    ? {
        className: styles.localStatusBadgeInstalled,
        label: t("models.localRuntimeInstalled"),
      }
    : {
        className: styles.localStatusBadgeMuted,
        label: t("models.localRuntimeMissing"),
      };
  const runBadge =
    serverStatus?.message && !serverStatus.available
      ? {
          className: styles.localStatusBadgeDead,
          label: t("models.localServerIdle"),
        }
      : isRunning
      ? {
          className: styles.localStatusBadgeRunning,
          label: t("models.localServerOnline"),
        }
      : {
          className: styles.localStatusBadgeDead,
          label: t("models.localServerIdle"),
        };
  const progressPercent = getProgressPercent(progress);
  const progressBadgeLabel =
    progressPercent !== null
      ? `${progressPercent}%`
      : t("models.localDownloadPending");

  return (
    <div className={styles.localRuntimePanel}>
      <div className={styles.localRuntimePanelHeader}>
        <div className={styles.modelListItemInfo}>
          <span className={styles.modelListItemName}>
            {t("models.localLlamacppName")}
          </span>
          <span className={styles.modelListItemId}>
            {isDownloading
              ? formatProgressText(progress)
              : t("models.localRuntimeSectionDescription")}
          </span>
        </div>
      </div>

      <div className={styles.localEngineStatusRow}>
        <div className={styles.localEngineStatusItem}>
          <span className={styles.localEngineMetricLabel}>
            {t("models.localEngineInstallStateLabel")}
          </span>
          <span
            className={`${styles.localStatusBadge} ${installBadge.className}`}
          >
            {installBadge.label}
          </span>
        </div>
        <div className={styles.localEngineStatusItem}>
          <span className={styles.localEngineMetricLabel}>
            {t("models.localEngineRunStateLabel")}
          </span>
          {serverStatus?.message && !serverStatus.available ? (
            <Tooltip title={serverStatus.message}>
              <span
                className={`${styles.localStatusBadge} ${runBadge.className}`}
              >
                {runBadge.label}
              </span>
            </Tooltip>
          ) : isRunning && serverStatus?.model_name ? (
            <div className={styles.localEngineStatusValue}>
              <span
                className={`${styles.localStatusBadge} ${runBadge.className}`}
              >
                {runBadge.label}
              </span>
            </div>
          ) : (
            <span
              className={`${styles.localStatusBadge} ${runBadge.className}`}
            >
              {runBadge.label}
            </span>
          )}
        </div>
      </div>

      <div className={styles.localStatusCardFooter}>
        <span className={styles.localStatusHint}>
          {isDownloading
            ? t("models.localDownloadNavigateHint")
            : t("models.localEngineStatusHint")}
        </span>
        {isDownloading ? (
          <div className={styles.localStatusActions}>
            <span className={styles.localStatusActionPill}>
              {progressBadgeLabel}
            </span>
            <Button danger icon={<CloseOutlined />} onClick={onCancel}>
              {t("models.localCancelDownload")}
            </Button>
          </div>
        ) : !installed ? (
          <Button type="primary" icon={<DownloadOutlined />} onClick={onStart}>
            {t("models.localInstallLlamacpp")}
          </Button>
        ) : null}
      </div>
    </div>
  );
});
