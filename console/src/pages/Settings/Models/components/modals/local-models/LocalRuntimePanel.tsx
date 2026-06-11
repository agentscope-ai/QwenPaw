import { memo, useState } from "react";
import { Button } from "@/components/ui/button";
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import { Download, X } from "lucide-react";
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
  const [updateDialogOpen, setUpdateDialogOpen] = useState(false);
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
    setUpdateDialogOpen(true);
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
            <Tooltip>
              <TooltipTrigger asChild>
                <button
                  type="button"
                  className={`${styles.localStatusBadge} ${styles.localStatusBadgeAction} ${styles.localStatusBadgeButton}`}
                  onClick={handleConfirmUpdate}
                >
                  {installBadge.label}
                </button>
              </TooltipTrigger>
              <TooltipContent>
                {t("models.localRuntimeUpdateAction")}
              </TooltipContent>
            </Tooltip>
          ) : !installable && serverStatus?.message ? (
            <Tooltip>
              <TooltipTrigger asChild>
                <span
                  className={`${styles.localStatusBadge} ${installBadge.className}`}
                >
                  {installBadge.label}
                </span>
              </TooltipTrigger>
              <TooltipContent>{serverStatus.message}</TooltipContent>
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
            <Tooltip>
              <TooltipTrigger asChild>
                <span
                  className={`${styles.localStatusBadge} ${runBadge.className}`}
                >
                  {runBadge.label}
                </span>
              </TooltipTrigger>
              <TooltipContent>{serverStatus.message}</TooltipContent>
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
            <Button onClick={onStart} disabled={!installable}>
              <Download className="mr-2 h-4 w-4" />
              {t("models.localInstallLlamacpp")}
            </Button>
          ) : null}
        </div>
      </div>

      {isDownloading ? (
        <div className={styles.localRuntimeDownloadRow}>
          <div className={styles.localRuntimeProgressBlock}>
            <div className={styles.localRuntimeProgressBarRow}>
              <div
                className={`${styles.localRuntimeProgress} flex-1 h-2 rounded-full bg-muted overflow-hidden`}
              >
                <div
                  className="h-full rounded-full transition-all"
                  style={{
                    width: `${progressPercent ?? 0}%`,
                    backgroundColor: "var(--primary)",
                  }}
                />
              </div>
              <Tooltip>
                <TooltipTrigger asChild>
                  <Button
                    variant="destructive"
                    size="sm"
                    disabled={isCanceling}
                    onClick={onCancel}
                  >
                    <X className="h-3 w-3" />
                  </Button>
                </TooltipTrigger>
                <TooltipContent>
                  {t("models.localCancelDownloadAction")}
                </TooltipContent>
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

      <AlertDialog open={updateDialogOpen} onOpenChange={setUpdateDialogOpen}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>
              {t("models.localRuntimeUpdateConfirmTitle")}
            </AlertDialogTitle>
            <AlertDialogDescription>
              {isRunning
                ? t("models.localRuntimeUpdateConfirmContentWithServer", {
                    model:
                      serverStatus?.model_name ?? t("models.localLlamacppName"),
                  })
                : t("models.localRuntimeUpdateConfirmContent")}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>{t("common.cancel")}</AlertDialogCancel>
            <AlertDialogAction
              onClick={() => {
                setUpdateDialogOpen(false);
                onStart();
              }}
            >
              {t("common.confirm")}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
});
