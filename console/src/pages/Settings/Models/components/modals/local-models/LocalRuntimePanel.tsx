import { memo } from "react";
import { Button, Modal, Tooltip } from "@agentscope-ai/design";
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
  hasUpdate: boolean;
  progress: LocalDownloadProgress | null;
  onStart: () => void;
  onCancel: () => void;
  onStop: () => void;
  stopping: boolean;
}

export const LocalRuntimePanel = memo(function LocalRuntimePanel({
  serverStatus,
  hasUpdate,
  progress,
  onStart,
  onCancel,
}: LocalRuntimePanelProps) {
  const { t } = useTranslation();
  const installable = serverStatus?.installable ?? true;
  const installed = Boolean(serverStatus?.installed);
  const isDownloading = isDownloadActive(progress);
  const isCanceling = progress?.status === "canceling";
  const isRunning = Boolean(serverStatus?.model_name);
  const showFooterHint = installed || isDownloading;
  const installBadge = hasUpdate
    ? {
        className: styles.localStatusBadgeInstalled,
        label: t("models.localRuntimeUpdateAvailable"),
      }
    : installed
      ? {
          className: styles.localStatusBadgeInstalled,
          label: t("models.localRuntimeInstalled"),
        }
      : !installable
        ? {
            className: styles.localStatusBadgeDead,
            label: t("models.localRuntimeUnsupported"),
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
  const canTriggerUpdate = hasUpdate && !isDownloading;

  const handleConfirmUpdate = () => {
    Modal.confirm({
      title: t("models.localRuntimeUpdateConfirmTitle"),
      content: isRunning
        ? t("models.localRuntimeUpdateConfirmContentWithServer", {
            model: serverStatus?.model_name ?? t("models.localLlamacppName"),
          })
        : t("models.localRuntimeUpdateConfirmContent"),
      okText: t("common.confirm"),
      cancelText: t("common.cancel"),
      onOk: onStart,
    });
  };

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

      <div className={styles.localSectionNotice}>
        {t("models.localRuntimeComputeHint")}
      </div>

      <div className={styles.localEngineStatusRow}>
        <div className={styles.localEngineStatusItem}>
          <span className={styles.localEngineMetricLabel}>
            {t("models.localEngineInstallStateLabel")}
          </span>
          {canTriggerUpdate ? (
            <Tooltip title={t("models.localRuntimeUpdateAction")}>
              <button
                type="button"
                className={`${styles.localStatusBadge} ${styles.localStatusBadgeAction} ${styles.localStatusBadgeButton}`}
                onClick={handleConfirmUpdate}
              >
                {installBadge.label}
              </button>
            </Tooltip>
          ) : !installable && serverStatus?.message ? (
            <Tooltip title={serverStatus.message}>
              <span
                className={`${styles.localStatusBadge} ${installBadge.className}`}
              >
                {installBadge.label}
              </span>
            </Tooltip>
          ) : (
            <span
              className={`${styles.localStatusBadge} ${installBadge.className}`}
            >
              {installBadge.label}
            </span>
          )}
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
        <div className={styles.localStatusFooterContent}>
          {showFooterHint ? (
            <span className={styles.localStatusHint}>
              {isDownloading
                ? t("models.localDownloadNavigateHint")
                : t("models.localEngineStatusHint")}
            </span>
          ) : null}
          {!isDownloading && !installed ? (
            <Button
              type="primary"
              icon={<DownloadOutlined />}
              onClick={onStart}
              disabled={!installable}
            >
              {t("models.localInstallLlamacpp")}
            </Button>
          ) : null}
        </div>
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
