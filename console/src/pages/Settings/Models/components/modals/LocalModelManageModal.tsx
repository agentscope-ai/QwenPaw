import { useState, useEffect, useCallback, useRef } from "react";
import { Button, Input, Modal, Select, Tooltip } from "@agentscope-ai/design";
import { useAppMessage } from "../../../../../hooks/useAppMessage.ts";
import { CloseOutlined, DownloadOutlined } from "@ant-design/icons";
import { Progress } from "antd";
import type {
  ProviderInfo,
  LocalDownloadProgress,
  LocalDownloadSource,
  LocalModelInfo,
  LocalServerStatus,
} from "../../../../../api/types";
import api from "../../../../../api";
import { useTranslation } from "react-i18next";
import styles from "../../index.module.less";
import { LocalModelRow } from "./local-models/LocalModelRow";
import { LocalRuntimePanel } from "./local-models/LocalRuntimePanel";
import {
  formatProgressText,
  getProgressPercent,
  isDownloadActive,
} from "./local-models/shared";

const POLL_INTERVAL_MS = 3000;

type LocalDownloadStatus = LocalDownloadProgress["status"];

function isSameServerStatus(
  left: LocalServerStatus | null,
  right: LocalServerStatus | null,
): boolean {
  return (
    left?.available === right?.available &&
    left?.installed === right?.installed &&
    left?.port === right?.port &&
    left?.model_name === right?.model_name &&
    left?.message === right?.message
  );
}

function isSameDownloadProgress(
  left: LocalDownloadProgress | null,
  right: LocalDownloadProgress | null,
): boolean {
  return (
    left?.status === right?.status &&
    left?.model_name === right?.model_name &&
    left?.downloaded_bytes === right?.downloaded_bytes &&
    left?.total_bytes === right?.total_bytes &&
    left?.speed_bytes_per_sec === right?.speed_bytes_per_sec &&
    left?.source === right?.source &&
    left?.error === right?.error
  );
}

interface LocalStatusSnapshot {
  server: LocalServerStatus;
  llamacpp: LocalDownloadProgress;
  model: LocalDownloadProgress;
}

function isBusyDownloadStatus(status: LocalDownloadStatus | null | undefined) {
  return (
    status === "pending" || status === "downloading" || status === "canceling"
  );
}

interface LocalModelManageModalProps {
  provider: ProviderInfo;
  open: boolean;
  onClose: () => void;
  onSaved: () => void;
}

export function LocalModelManageModal({
  provider,
  open,
  onClose,
  onSaved,
}: LocalModelManageModalProps) {
  const { t } = useTranslation();
  const [localModels, setLocalModels] = useState<LocalModelInfo[]>([]);
  const [customModelRepoId, setCustomModelRepoId] = useState("");
  const [customModelSource, setCustomModelSource] =
    useState<LocalDownloadSource>("huggingface");
  const [loadingLocal, setLoadingLocal] = useState(false);
  const [loadingStatus, setLoadingStatus] = useState(false);
  const [serverStatus, setServerStatus] = useState<LocalServerStatus | null>(
    null,
  );
  const [llamacppDownload, setLlamacppDownload] =
    useState<LocalDownloadProgress | null>(null);
  const [modelDownload, setModelDownload] =
    useState<LocalDownloadProgress | null>(null);
  const [startingModelName, setStartingModelName] = useState<string | null>(
    null,
  );
  const [stoppingServer, setStoppingServer] = useState(false);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const modelDownloadRef = useRef<LocalDownloadProgress | null>(null);
  const previousLlamacppStatusRef = useRef<string | null>(null);
  const previousModelStatusRef = useRef<string | null>(null);

  const { message } = useAppMessage();

  const getLocalModelDisplayName = (modelId: string | null) => {
    if (!modelId) {
      return null;
    }
    return localModels.find((model) => model.id === modelId)?.name ?? modelId;
  };

  const stopPolling = useCallback(() => {
    if (pollRef.current) {
      clearInterval(pollRef.current);
      pollRef.current = null;
    }
  }, []);

  const fetchLocalModels = useCallback(async () => {
    setLoadingLocal(true);
    try {
      const data = await api.listRecommendedLocalModels();
      setLocalModels(Array.isArray(data) ? data : []);
    } catch {
      setLocalModels([]);
    } finally {
      setLoadingLocal(false);
    }
  }, []);

  const setModelDownloadState = useCallback(
    (
      value:
        | LocalDownloadProgress
        | null
        | ((
            prev: LocalDownloadProgress | null,
          ) => LocalDownloadProgress | null),
    ) => {
      setModelDownload((prev) => {
        const next = typeof value === "function" ? value(prev) : value;
        modelDownloadRef.current = next;
        return next;
      });
    },
    [],
  );

  const refreshStatus = useCallback(
    async (showLoading = false) => {
      if (showLoading) {
        setLoadingStatus(true);
      }
      try {
        const [nextServerStatus, nextLlamacppDownload, nextModelDownload] =
          await Promise.all([
            api.getLocalServerStatus(),
            api.getLlamacppDownloadProgress(),
            api.getLocalModelDownloadProgress(),
          ]);

        setServerStatus((prev) =>
          isSameServerStatus(prev, nextServerStatus) ? prev : nextServerStatus,
        );
        setLlamacppDownload((prev) =>
          isSameDownloadProgress(prev, nextLlamacppDownload)
            ? prev
            : nextLlamacppDownload,
        );
        setModelDownloadState((prev) =>
          isSameDownloadProgress(prev, nextModelDownload)
            ? prev
            : nextModelDownload,
        );

        if (
          (previousLlamacppStatusRef.current === "pending" ||
            previousLlamacppStatusRef.current === "downloading") &&
          nextLlamacppDownload.status === "completed"
        ) {
          message.success(t("models.localLlamacppInstallSuccess"));
        }

        if (
          (previousModelStatusRef.current === "pending" ||
            previousModelStatusRef.current === "downloading") &&
          nextModelDownload.status === "completed"
        ) {
          message.success(t("models.localDownloadSuccess"));
          onSaved();
          void fetchLocalModels();
        }

        if (
          previousLlamacppStatusRef.current !== "failed" &&
          nextLlamacppDownload.status === "failed" &&
          nextLlamacppDownload.error
        ) {
          message.error(nextLlamacppDownload.error);
        }
        if (
          previousModelStatusRef.current !== "failed" &&
          nextModelDownload.status === "failed" &&
          nextModelDownload.error
        ) {
          message.error(nextModelDownload.error);
        }

        previousLlamacppStatusRef.current = nextLlamacppDownload.status;
        previousModelStatusRef.current = nextModelDownload.status;

        if (
          !isBusyDownloadStatus(nextLlamacppDownload.status) &&
          !isBusyDownloadStatus(nextModelDownload.status)
        ) {
          stopPolling();
        }

        return {
          server: nextServerStatus,
          llamacpp: nextLlamacppDownload,
          model: nextModelDownload,
        } satisfies LocalStatusSnapshot;
      } catch {
        return null;
      } finally {
        if (showLoading) {
          setLoadingStatus(false);
        }
      }
    },
    [fetchLocalModels, onSaved, stopPolling, t],
  );

  const startPolling = useCallback(() => {
    if (pollRef.current) return;
    pollRef.current = setInterval(() => {
      void refreshStatus();
    }, POLL_INTERVAL_MS);
  }, [refreshStatus]);

  useEffect(() => {
    if (!open) return;

    void Promise.all([fetchLocalModels(), refreshStatus(true)]).then(
      ([, statuses]) => {
        if (
          statuses &&
          (isBusyDownloadStatus(statuses.llamacpp.status) ||
            isBusyDownloadStatus(statuses.model.status))
        ) {
          startPolling();
        }
      },
    );

    return () => stopPolling();
  }, [fetchLocalModels, open, refreshStatus, startPolling, stopPolling]);

  const handleStartLlamacppDownload = useCallback(async () => {
    const previousLlamacppDownload = llamacppDownload;
    const previousLlamacppStatus = previousLlamacppStatusRef.current;

    setLlamacppDownload({
      status: "pending",
      model_name: t("models.localLlamacppName"),
      downloaded_bytes: 0,
      total_bytes: null,
      speed_bytes_per_sec: 0,
      source: null,
      error: null,
      local_path: null,
    });
    previousLlamacppStatusRef.current = "pending";

    try {
      await api.startLlamacppDownload();
      message.success(t("models.localLlamacppInstallStarted"));
      await refreshStatus();
      startPolling();
    } catch (error) {
      setLlamacppDownload(previousLlamacppDownload);
      previousLlamacppStatusRef.current = previousLlamacppStatus;
      await refreshStatus();
      startPolling();
      const errMsg =
        error instanceof Error
          ? error.message
          : t("models.localLlamacppInstallFailed");
      message.error(errMsg);
    }
  }, [llamacppDownload, refreshStatus, startPolling, t]);

  const handleCancelLlamacppDownload = useCallback(() => {
    Modal.confirm({
      title: t("models.localCancelDownloadTitle"),
      content: t("models.localCancelDownloadConfirm", {
        repo: t("models.localLlamacppName"),
      }),
      okText: t("models.localCancelDownloadAction"),
      okButtonProps: { danger: true },
      cancelText: t("common.close"),
      onOk: async () => {
        try {
          setLlamacppDownload((prev) =>
            prev
              ? {
                  ...prev,
                  status: "canceling",
                }
              : prev,
          );
          await api.cancelLlamacppDownload();
          message.success(t("models.localDownloadCancelled"));
          await refreshStatus();
          startPolling();
        } catch (error) {
          const errMsg =
            error instanceof Error
              ? error.message
              : t("models.localCancelDownloadFailed");
          message.error(errMsg);
        }
      },
    });
  }, [refreshStatus, startPolling, t]);

  const handleStartModelDownload = useCallback(
    async (model: LocalModelInfo) => {
      const previousModelDownload = modelDownloadRef.current;
      const previousModelStatus = previousModelStatusRef.current;

      setModelDownloadState({
        status: "pending",
        model_name: model.id,
        downloaded_bytes: 0,
        total_bytes: null,
        speed_bytes_per_sec: 0,
        source: model.source,
        error: null,
        local_path: null,
      });
      previousModelStatusRef.current = "pending";

      try {
        await api.startLocalModelDownload(model.id, model.source);
        await refreshStatus();
        startPolling();
      } catch (error) {
        setModelDownloadState(previousModelDownload);
        previousModelStatusRef.current = previousModelStatus;
        const errMsg =
          error instanceof Error
            ? error.message
            : t("models.localDownloadFailed");
        message.error(errMsg);
      }
    },
    [refreshStatus, setModelDownloadState, startPolling, t],
  );

  const handleStartCustomModelDownload = useCallback(async () => {
    const trimmedRepoId = customModelRepoId.trim();

    if (!trimmedRepoId) {
      message.warning(t("models.localRepoIdRequired"));
      return;
    }

    await handleStartModelDownload({
      id: trimmedRepoId,
      name: trimmedRepoId,
      size_bytes: 0,
      downloaded: false,
      source: customModelSource,
    });
  }, [customModelRepoId, customModelSource, handleStartModelDownload, t]);

  const handleCancelModelDownload = useCallback(
    (modelName: string) => {
      Modal.confirm({
        title: t("models.localCancelDownloadTitle"),
        content: t("models.localCancelDownloadConfirm", { repo: modelName }),
        okText: t("models.localCancelDownloadAction"),
        okButtonProps: { danger: true },
        cancelText: t("common.close"),
        onOk: async () => {
          try {
            setModelDownloadState((prev) =>
              prev
                ? {
                    ...prev,
                    status: "canceling",
                  }
                : prev,
            );
            await api.cancelLocalModelDownload();
            message.success(t("models.localDownloadCancelled"));
            await refreshStatus();
            startPolling();
          } catch (error) {
            const errMsg =
              error instanceof Error
                ? error.message
                : t("models.localCancelDownloadFailed");
            message.error(errMsg);
          }
        },
      });
    },
    [refreshStatus, setModelDownloadState, startPolling, t],
  );

  const handleStartServer = useCallback(
    async (model: LocalModelInfo) => {
      const run = async () => {
        setStartingModelName(model.id);
        try {
          await api.startLocalServer({
            model_id: model.id,
          });
          await refreshStatus();
          onSaved();
        } catch (error) {
          const errMsg =
            error instanceof Error
              ? error.message
              : t("models.localServerStartFailed");
          message.error(errMsg);
        } finally {
          setStartingModelName(null);
        }
      };

      if (
        serverStatus?.available &&
        serverStatus.model_name &&
        serverStatus.model_name !== model.id
      ) {
        Modal.confirm({
          title: t("models.localServerSwitchTitle"),
          content: t("models.localServerSwitchConfirm", {
            current: getLocalModelDisplayName(serverStatus.model_name),
            next: model.name,
          }),
          okText: t("models.localSwitchModel"),
          cancelText: t("models.cancel"),
          onOk: run,
        });
        return;
      }

      await run();
    },
    [localModels, onSaved, refreshStatus, serverStatus, t],
  );

  const handleStopServer = useCallback(async () => {
    setStoppingServer(true);
    try {
      await api.stopLocalServer();
      await refreshStatus();
      onSaved();
    } catch (error) {
      const errMsg =
        error instanceof Error
          ? error.message
          : t("models.localServerStopFailed");
      message.error(errMsg);
    } finally {
      setStoppingServer(false);
    }
  }, [onSaved, refreshStatus, t]);

  const handleClose = () => {
    onClose();
  };

  const isModelDownloading = isDownloadActive(modelDownload);
  const isServerBusy = stoppingServer || startingModelName !== null;
  const isRuntimeInstalled = Boolean(serverStatus?.installed);
  const isCustomDownloadDisabled =
    customModelRepoId.trim().length === 0 || isModelDownloading || isServerBusy;
  const downloadedModelCount = localModels.filter(
    (model) => model.downloaded,
  ).length;

  const currentRunningModelName = serverStatus?.model_name ?? null;
  const currentRunningModelDisplayName = getLocalModelDisplayName(
    currentRunningModelName,
  );
  const currentModelDownloadName =
    getLocalModelDisplayName(modelDownload?.model_name ?? null) ||
    t("models.localDownloadPending");
  const currentModelDownloadPercent = getProgressPercent(modelDownload);

  return (
    <Modal
      title={t("models.localModelsTitle", { provider: provider.name })}
      open={open}
      onCancel={handleClose}
      footer={
        <div className={styles.modalFooter}>
          <div className={styles.modalFooterRight}>
            <Button onClick={handleClose}>{t("models.cancel")}</Button>
          </div>
        </div>
      }
      width={600}
      destroyOnHidden
    >
      {(loadingLocal || loadingStatus) && localModels.length === 0 ? (
        <div className={styles.modelListEmpty}>{t("common.loading")}</div>
      ) : null}

      <section className={styles.localSection}>
        <LocalRuntimePanel
          serverStatus={serverStatus}
          progress={llamacppDownload}
          onStart={handleStartLlamacppDownload}
          onCancel={handleCancelLlamacppDownload}
          onStop={handleStopServer}
          stopping={stoppingServer}
        />
      </section>

      <section className={styles.localSection}>
        <div className={styles.localSectionHeader}>
          <div>
            <div className={styles.localSectionTitle}>
              {t("models.localModelsSectionTitle")}
            </div>
          </div>
        </div>

        {isRuntimeInstalled && isModelDownloading ? (
          <div className={styles.localSectionInfoRow}>
            <div className={styles.localSectionInfoContent}>
              <span className={styles.localSectionInfoLabel}>
                {t("models.localCurrentDownloadTitle")}
              </span>
              <span className={styles.localSectionInfoValue}>
                {currentModelDownloadName}
              </span>
              <div className={styles.localRuntimeDownloadRow}>
                <div className={styles.localRuntimeProgressBlock}>
                  <div className={styles.localRuntimeProgressBarRow}>
                    <Progress
                      className={styles.localRuntimeProgress}
                      percent={currentModelDownloadPercent ?? 0}
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
                        onClick={() =>
                          handleCancelModelDownload(currentModelDownloadName)
                        }
                      />
                    </Tooltip>
                  </div>
                  <span className={styles.localRuntimeProgressMeta}>
                    {formatProgressText(modelDownload)}
                  </span>
                </div>
              </div>
            </div>
          </div>
        ) : null}

        {isRuntimeInstalled && currentRunningModelName ? (
          <div className={styles.localSectionInfoRow}>
            <span className={styles.localSectionInfoLabel}>
              {t("models.localEngineCurrentModelLabel")}
            </span>
            <span className={styles.localSectionInfoValue}>
              {currentRunningModelDisplayName}
            </span>
          </div>
        ) : null}

        {isRuntimeInstalled && downloadedModelCount === 0 ? (
          <div className={styles.localSectionNotice}>
            {t("models.localNoDownloadedModelsHint")}
          </div>
        ) : null}

        {!isRuntimeInstalled ? (
          <div className={styles.localLockedPanel}>
            <div className={styles.localLockedPanelDescription}>
              {t("models.localModelsLockedHint")}
            </div>
          </div>
        ) : (
          <div className={styles.modelList}>
            {serverStatus?.installed && loadingLocal ? (
              <div className={styles.modelListEmpty}>{t("common.loading")}</div>
            ) : serverStatus?.installed && localModels.length === 0 ? (
              <div className={styles.modelListEmpty}>
                {t("models.localNoRecommendedModels")}
              </div>
            ) : null}

            {serverStatus?.installed
              ? localModels.map((model) => (
                  <LocalModelRow
                    key={model.id}
                    model={model}
                    currentRunningModelName={currentRunningModelName}
                    isModelDownloading={isModelDownloading}
                    isServerBusy={isServerBusy}
                    startingModelName={startingModelName}
                    stoppingServer={stoppingServer}
                    onStartDownload={handleStartModelDownload}
                    onStartServer={handleStartServer}
                    onStopServer={handleStopServer}
                  />
                ))
              : null}

            {serverStatus?.installed ? (
              <div
                className={`${styles.modelListItem} ${styles.customModelListItem}`}
              >
                <div className={styles.customModelHeader}>
                  <div className={styles.customModelListItemInfo}>
                    <span className={styles.modelListItemName}>
                      {t("models.localCustomModelTitle")}
                    </span>
                    <span className={styles.customModelHint}>
                      {t("models.localCustomModelHint")}
                    </span>
                  </div>
                  <Button
                    type="primary"
                    size="small"
                    icon={<DownloadOutlined />}
                    onClick={() => {
                      void handleStartCustomModelDownload();
                    }}
                    disabled={isCustomDownloadDisabled}
                  >
                    {t("common.download")}
                  </Button>
                </div>
                <div className={styles.customModelInputRow}>
                  <Input
                    value={customModelRepoId}
                    onChange={(e) => setCustomModelRepoId(e.target.value)}
                    onPressEnter={() => {
                      void handleStartCustomModelDownload();
                    }}
                    placeholder={t("models.localRepoIdPlaceholder")}
                    className={styles.customModelRepoInput}
                  />
                  <Select
                    value={customModelSource}
                    onChange={(value) =>
                      setCustomModelSource(value as LocalDownloadSource)
                    }
                    className={styles.customModelSourceSelect}
                    options={[
                      {
                        value: "huggingface",
                        label: t("models.localSourceHuggingFace"),
                      },
                      {
                        value: "modelscope",
                        label: t("models.localSourceModelScope"),
                      },
                    ]}
                  />
                </div>
              </div>
            ) : null}
          </div>
        )}
      </section>
    </Modal>
  );
}
