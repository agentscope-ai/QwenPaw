import { memo } from "react";
import { Button, Modal, Tooltip } from "@agentscope-ai/design";
import {
  X as CloseOutlined,
  Download as DownloadOutlined,
  Cpu as CpuOutlined,
  Zap as ZapOutlined,
} from "lucide-react";
import { Progress, Segmented } from "antd";
import { useTranslation } from "react-i18next";
import type {
  LocalDownloadProgress,
  LocalEngineId,
  LocalEngineInfo,
  LocalServerStatus,
} from "../../../../../../api/types";
import styles from "../../../index.module.less";
import {
  formatProgressText,
  getProgressPercent,
  isDownloadActive,
} from "./shared";

interface LocalRuntimePanelProps {
  engine: LocalEngineId;
  engines: LocalEngineInfo[];
  serverStatus: LocalServerStatus | null;
  hasUpdate: boolean;
  progress: LocalDownloadProgress | null;
  onEngineChange: (engine: LocalEngineId) => void;
  onStart: () => void;
  onCancel: () => void;
  onStop: () => void;
  stopping: boolean;
}

export const LocalRuntimePanel = memo(function LocalRuntimePanel({
  engine,
  engines,
  serverStatus,
  hasUpdate,
  progress,
  onEngineChange,
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
  const isMlx = engine === "mlx";
  const engineName = isMlx
    ? t("models.localEngineMlx")
    : t("models.localEngineLlamacpp");
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
  const progressText = isDownloading
    ? isMlx && progressPercent === null
      ? t("models.localMlxInstalling")
      : formatProgressText(progress)
    : null;
  const canTriggerUpdate = hasUpdate && !isDownloading;
  const mlxInfo = engines.find((item) => item.id === "mlx");
  const mlxDisabled = mlxInfo ? !mlxInfo.installable : false;
  const accelerator = serverStatus?.accelerator;
  const acceleratorLabel =
    accelerator === "metal"
      ? t("models.localRuntimeAcceleratorMetal", {
          device:
            serverStatus?.device_name ?? t("models.localRuntimeAcceleratorGpu"),
        })
      : accelerator === "cuda"
      ? t("models.localRuntimeAcceleratorCuda", {
          device:
            serverStatus?.device_name ?? t("models.localRuntimeAcceleratorGpu"),
        })
      : t("models.localRuntimeAcceleratorCpu");

  const handleConfirmUpdate = () => {
    Modal.confirm({
      className: styles.modelConfirmModal,
      title: t("models.localRuntimeUpdateConfirmTitle", {
        engine: engineName,
      }),
      content: isRunning
        ? t("models.localRuntimeUpdateConfirmContentWithServer", {
            engine: engineName,
            model: serverStatus?.model_name ?? engineName,
          })
        : t("models.localRuntimeUpdateConfirmContent", {
            engine: engineName,
          }),
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
            {t("models.localEngineSelectorLabel")}
          </span>
          <span className={styles.modelListItemId}>
            {isMlx
              ? t("models.localEngineMlxDescription")
              : t("models.localEngineLlamacppDescription")}
          </span>
        </div>
        <Segmented
          aria-label={t("models.localEngineSelectorLabel")}
          className={styles.localEngineSelector}
          value={engine}
          options={[
            {
              label: t("models.localEngineLlamacpp"),
              value: "llamacpp",
            },
            {
              label: (
                <span
                  title={mlxDisabled ? t("models.localMlxUnsupported") : ""}
                >
                  {t("models.localEngineMlx")}
                </span>
              ),
              value: "mlx",
              disabled: mlxDisabled,
            },
          ]}
          onChange={(value) => onEngineChange(value as LocalEngineId)}
        />
      </div>

      <div
        className={
          accelerator && accelerator !== "cpu"
            ? styles.localSectionNotice
            : `${styles.localSectionNotice} ${styles.localSectionNoticeMuted}`
        }
      >
        <span className={styles.localRuntimeAccelerator}>
          {accelerator && accelerator !== "cpu" ? (
            <ZapOutlined size="1em" aria-hidden="true" />
          ) : (
            <CpuOutlined size="1em" aria-hidden="true" />
          )}
          {acceleratorLabel}
        </span>
        {accelerator === "cpu" ? (
          <span>{t("models.localRuntimeAcceleratorCpuHint")}</span>
        ) : null}
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
              icon={<DownloadOutlined size="1em" />}
              onClick={onStart}
              disabled={!installable}
            >
              {isMlx
                ? t("models.localInstallMlx")
                : t("models.localInstallLlamacpp")}
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
                percent={progressPercent ?? undefined}
                showInfo={false}
                status="active"
                strokeColor="var(--app-accent)"
                strokeWidth={10}
              />
              <Tooltip title={t("models.localCancelDownloadAction")}>
                <Button
                  danger
                  size="small"
                  icon={<CloseOutlined size="1em" />}
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
