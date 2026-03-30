import { memo } from "react";
import { Button, Tooltip } from "@agentscope-ai/design";
import { CloseOutlined, DownloadOutlined } from "@ant-design/icons";
import { Progress } from "antd";
import { useTranslation } from "react-i18next";
import type {
  LocalDownloadProgress,
  LocalServerStatus,
} from "../../../../../../api/types";
import styles from "../../../index.module.less";
import {
  formatProgressText,
  getProgressPercent,
  isDownloadActive,
} from "./shared";

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
  const isDownloading = isDownloadActive(progress);
  const isCanceling = progress?.status === "canceling";
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
  const progressText = isDownloading ? formatProgressText(progress) : null;

  return (
    <div className={styles.localRuntimePanel}>
      <div className={styles.localRuntimePanelHeader}>
        <div className={styles.modelListItemInfo}>
          <span className={styles.modelListItemName}>
            {t("models.localLlamacppName")}
          </span>
          <span className={styles.modelListItemId}>
            {t("models.localRuntimeSectionDescription")}
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
        {!isDownloading && !installed ? (
          <Button type="primary" icon={<DownloadOutlined />} onClick={onStart}>
            {t("models.localInstallLlamacpp")}
          </Button>
        ) : null}
      </div>

      {isDownloading ? (
        <div className={styles.localRuntimeDownloadRow}>
          <div className={styles.localRuntimeProgressBlock}>
            <div className={styles.localRuntimeProgressBarRow}>
              <Progress
                className={styles.localRuntimeProgress}
                percent={progressPercent ?? 0}
                showInfo={false}
                status="active"
                strokeColor="#ff7f16"
                strokeWidth={10}
              />
              <Tooltip title={t("models.localCancelDownloadAction")}>
                <Button
                  danger
                  size="small"
                  icon={<CloseOutlined />}
                  loading={isCanceling}
                  disabled={isCanceling}
                  onClick={onCancel}
                />
              </Tooltip>
            </div>
            {progressText ? (
              <span className={styles.localRuntimeProgressMeta}>
                {progressText}
              </span>
            ) : null}
          </div>
        </div>
      ) : null}
    </div>
  );
});
