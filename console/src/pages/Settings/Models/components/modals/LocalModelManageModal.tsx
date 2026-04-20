import { useState, useEffect, useCallback, useRef, useMemo } from "react";
import {
  Button,
  Input,
  InputNumber,
  Modal,
  Select,
  Tooltip,
} from "@agentscope-ai/design";
import { useAppMessage } from "../../../../../hooks/useAppMessage.ts";
import {
  CloseOutlined,
  DownloadOutlined,
  DownOutlined,
  SaveOutlined,
} from "@ant-design/icons";
import { Progress } from "antd";
import type {
  LocalModelConfig,
  ProviderInfo,
  LocalDownloadProgress,
  LocalDownloadSource,
  LocalModelInfo,
  LocalServerStatus,
  LocalServerUpdateStatus,
} from "../../../../../api/types";
import api from "../../../../../api";
import { useTranslation } from "react-i18next";
import styles from "../../index.module.less";
import { JsonConfigEditor } from "./JsonConfigEditor.tsx";
import { LocalModelRow } from "./local-models/LocalModelRow";
import { LocalRuntimePanel } from "./local-models/LocalRuntimePanel";
import {
  formatProgressText,
  getProgressPercent,
  isDownloadActive,
} from "./local-models/shared";

const POLL_INTERVAL_MS = 3000;
const DEFAULT_LOCAL_MAX_CONTEXT_LENGTH = 65536;
const MIN_LOCAL_MAX_CONTEXT_LENGTH = 32768;
const MIN_LOCAL_SERVER_PORT = 1;
const MAX_LOCAL_SERVER_PORT = 65535;

type LocalDownloadStatus = LocalDownloadProgress["status"];

function getInitialLocalModelConfig(
  config?: LocalModelConfig | null,
): { maxContextLength: number; port: number | null } {
  return {
    maxContextLength:
      typeof config?.max_context_length === "number" &&
      Number.isInteger(config.max_context_length) &&
      config.max_context_length >= MIN_LOCAL_MAX_CONTEXT_LENGTH
        ? config.max_context_length
        : DEFAULT_LOCAL_MAX_CONTEXT_LENGTH,
    port:
      typeof config?.port === "number" &&
      Number.isInteger(config.port) &&
      config.port >= MIN_LOCAL_SERVER_PORT &&
      config.port <= MAX_LOCAL_SERVER_PORT
        ? config.port
        : null,
  };
}

function isSameServerStatus(
  left: LocalServerStatus | null,
  right: LocalServerStatus | null,
): boolean {
  return (
    left?.available === right?.available &&
    left?.installable === right?.installable &&
    left?.installed === right?.installed &&
    left?.port === right?.port &&
    left?.model_name === right?.model_name &&
    left?.message === right?.message
  );
}

function isSameServerUpdateStatus(
  left: LocalServerUpdateStatus | null,
  right: LocalServerUpdateStatus | null,
): boolean {
  return left?.has_update === right?.has_update;
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
  const [serverUpdateStatus, setServerUpdateStatus] =
    useState<LocalServerUpdateStatus | null>(null);
  const [llamacppDownload, setLlamacppDownload] =
    useState<LocalDownloadProgress | null>(null);
  const [modelDownload, setModelDownload] =
    useState<LocalDownloadProgress | null>(null);
  const [startingModelName, setStartingModelName] = useState<string | null>(
    null,
  );
  const [stoppingServer, setStoppingServer] = useState(false);
  const [advancedOpen, setAdvancedOpen] = useState(false);
  const [advancedSaving, setAdvancedSaving] = useState(false);
  const [loadingLocalConfig, setLoadingLocalConfig] = useState(false);
  const [maxContextLength, setMaxContextLength] = useState<number>(
    DEFAULT_LOCAL_MAX_CONTEXT_LENGTH,
  );
  const [savedMaxContextLength, setSavedMaxContextLength] = useState<number>(
    DEFAULT_LOCAL_MAX_CONTEXT_LENGTH,
  );
  const [serverPort, setServerPort] = useState<number | null>(null);
  const [savedServerPort, setSavedServerPort] = useState<number | null>(null);
  const [generateKwargsText, setGenerateKwargsText] = useState("");
  const [savedGenerateKwargsText, setSavedGenerateKwargsText] = useState("");
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const modelDownloadRef = useRef<LocalDownloadProgress | null>(null);
  const previousLlamacppStatusRef = useRef<string | null>(null);
  const previousModelStatusRef = useRef<string | null>(null);
  const onSavedRef = useRef(onSaved);
  const initializedOpenRef = useRef(false);

  const { message } = useAppMessage();

  useEffect(() => {
    onSavedRef.current = onSaved;
  }, [onSaved]);

  const initialLocalConfig = useMemo(
    () => ({
      generateKwargsText:
        Object.keys(provider.generate_kwargs ?? {}).length > 0
          ? JSON.stringify(provider.generate_kwargs, null, 2)
          : "",
    }),
    [provider.generate_kwargs],
  );

  const parseGenerateConfig = useCallback(
    (value?: string) => {
      const trimmed = value?.trim();
      if (!trimmed) {
        return undefined;
      }

      let parsed: unknown;
      try {
        parsed = JSON.parse(trimmed);
      } catch {
        throw new Error(t("models.generateConfigInvalidJson"));
      }

      if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
        throw new Error(t("models.generateConfigMustBeObject"));
      }

      return parsed as Record<string, unknown>;
    },
    [t],
  );

  const generateKwargsError = useMemo(() => {
    try {
      parseGenerateConfig(generateKwargsText);
      return null;
    } catch (error) {
      return error instanceof Error
        ? error.message
        : t("models.generateConfigInvalidJson");
    }
  }, [generateKwargsText, parseGenerateConfig, t]);

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

  const fetchLocalConfig = useCallback(async () => {
    setLoadingLocalConfig(true);
    try {
      const config = await api.getLocalModelConfig();
      const normalizedConfig = getInitialLocalModelConfig(config);
      setMaxContextLength(normalizedConfig.maxContextLength);
      setSavedMaxContextLength(normalizedConfig.maxContextLength);
      setServerPort(normalizedConfig.port);
      setSavedServerPort(normalizedConfig.port);
      return normalizedConfig;
    } catch {
      const fallbackConfig = getInitialLocalModelConfig();
      setMaxContextLength(fallbackConfig.maxContextLength);
      setSavedMaxContextLength(fallbackConfig.maxContextLength);
      setServerPort(fallbackConfig.port);
      setSavedServerPort(fallbackConfig.port);
      return fallbackConfig;
    } finally {
      setLoadingLocalConfig(false);
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

  const refreshUpdateStatus = useCallback(
    async (nextServerStatus?: LocalServerStatus | null) => {
      const effectiveServerStatus = nextServerStatus ?? serverStatus;

      if (
        !effectiveServerStatus?.installable ||
        !effectiveServerStatus.installed
      ) {
        const fallbackStatus = { has_update: false };
        setServerUpdateStatus((prev) =>
          isSameServerUpdateStatus(prev, fallbackStatus)
            ? prev
            : fallbackStatus,
        );
        return fallbackStatus;
      }

      try {
        const nextUpdateStatus = await api.getLocalServerUpdateStatus();
        setServerUpdateStatus((prev) =>
          isSameServerUpdateStatus(prev, nextUpdateStatus)
            ? prev
            : nextUpdateStatus,
        );
        return nextUpdateStatus;
      } catch {
        return null;
      }
    },
    [serverStatus],
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
        if (!nextServerStatus.installable || !nextServerStatus.installed) {
          setServerUpdateStatus((prev) =>
            isSameServerUpdateStatus(prev, { has_update: false })
              ? prev
              : { has_update: false },
          );
        }
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
          setServerUpdateStatus((prev) =>
            isSameServerUpdateStatus(prev, { has_update: false })
              ? prev
              : { has_update: false },
          );
          void refreshUpdateStatus(nextServerStatus);
        }

        if (
          (previousModelStatusRef.current === "pending" ||
            previousModelStatusRef.current === "downloading") &&
          nextModelDownload.status === "completed"
        ) {
          message.success(t("models.localDownloadSuccess"));
          onSavedRef.current();
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
    [fetchLocalModels, refreshUpdateStatus, stopPolling, t],
  );

  const startPolling = useCallback(() => {
    if (pollRef.current) return;
    pollRef.current = setInterval(() => {
      void refreshStatus();
    }, POLL_INTERVAL_MS);
  }, [refreshStatus]);

  useEffect(() => {
    if (!open) {
      initializedOpenRef.current = false;
      return;
    }

    if (initializedOpenRef.current) {
      return;
    }
    initializedOpenRef.current = true;

    setAdvancedOpen(false);
    setMaxContextLength(DEFAULT_LOCAL_MAX_CONTEXT_LENGTH);
    setSavedMaxContextLength(DEFAULT_LOCAL_MAX_CONTEXT_LENGTH);
    setServerPort(null);
    setSavedServerPort(null);
    setGenerateKwargsText(initialLocalConfig.generateKwargsText);
    setSavedGenerateKwargsText(initialLocalConfig.generateKwargsText);

    void Promise.all([
      fetchLocalConfig(),
      fetchLocalModels(),
      refreshStatus(true),
    ]).then(([, , statuses]) => {
      void refreshUpdateStatus(statuses?.server ?? null);
      if (
        statuses &&
        (isBusyDownloadStatus(statuses.llamacpp.status) ||
          isBusyDownloadStatus(statuses.model.status))
      ) {
        startPolling();
      }
    });

    return () => stopPolling();
  }, [
    fetchLocalConfig,
    fetchLocalModels,
    open,
    refreshStatus,
    refreshUpdateStatus,
    startPolling,
    stopPolling,
    initialLocalConfig,
  ]);

  const handleSaveMaxContextLength = useCallback(async () => {
    if (!Number.isInteger(maxContextLength)) {
      message.error(t("models.localMaxContextLengthRequired"));
      return;
    }

    if (maxContextLength < MIN_LOCAL_MAX_CONTEXT_LENGTH) {
      message.error(
        t("models.localMaxContextLengthMin", {
          min: MIN_LOCAL_MAX_CONTEXT_LENGTH,
        }),
      );
      return;
    }

    setAdvancedSaving(true);
    try {
      await api.configureLocalModelSettings({
        max_context_length: maxContextLength,
      });
      setSavedMaxContextLength(maxContextLength);
      message.success(t("models.localAdvancedConfigSaved"));
      await onSavedRef.current();
    } catch (error) {
      const errMsg =
        error instanceof Error
          ? error.message
          : t("models.localAdvancedConfigSaveFailed");
      message.error(errMsg);
    } finally {
      setAdvancedSaving(false);
    }
  }, [maxContextLength, message, t]);

  const handleSaveServerPort = useCallback(async () => {
    if (
      serverPort !== null &&
      (!Number.isInteger(serverPort) ||
        serverPort < MIN_LOCAL_SERVER_PORT ||
        serverPort > MAX_LOCAL_SERVER_PORT)
    ) {
      message.error(
        t("models.localServerPortRange", {
          min: MIN_LOCAL_SERVER_PORT,
          max: MAX_LOCAL_SERVER_PORT,
        }),
      );
      return;
    }

    setAdvancedSaving(true);
    try {
      await api.configureLocalModelSettings({
        port: serverPort,
      });
      setSavedServerPort(serverPort);
      message.success(t("models.localAdvancedConfigSaved"));
      await onSavedRef.current();
    } catch (error) {
      const errMsg =
        error instanceof Error
          ? error.message
          : t("models.localAdvancedConfigSaveFailed");
      message.error(errMsg);
    } finally {
      setAdvancedSaving(false);
    }
  }, [message, serverPort, t]);

  const handleSaveGenerateKwargs = useCallback(async () => {
    let parsed: Record<string, unknown> = {};

    try {
      parsed = parseGenerateConfig(generateKwargsText) ?? {};
    } catch (error) {
      message.error(
        error instanceof Error
          ? error.message
          : t("models.generateConfigInvalidJson"),
      );
      return;
    }

    const trimmed = generateKwargsText.trim();
    const normalizedText = trimmed ? JSON.stringify(parsed, null, 2) : "";

    setAdvancedSaving(true);
    try {
      await api.configureLocalModelSettings({
        generate_kwargs: parsed,
      });
      setGenerateKwargsText(normalizedText);
      setSavedGenerateKwargsText(normalizedText);
      message.success(t("models.localAdvancedConfigSaved"));
      await onSavedRef.current();
    } catch (error) {
      const errMsg =
        error instanceof Error
          ? error.message
          : t("models.localAdvancedConfigSaveFailed");
      message.error(errMsg);
    } finally {
      setAdvancedSaving(false);
    }
  }, [generateKwargsText, message, parseGenerateConfig, t]);

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
      setServerUpdateStatus({ has_update: false });
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
  const isRuntimeInstallable = serverStatus?.installable ?? true;
  const isRuntimeInstalled = Boolean(serverStatus?.installed);
  const runtimeLockedMessage =
    !isRuntimeInstallable && serverStatus?.message
      ? serverStatus.message
      : t("models.localModelsLockedHint");
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
  // Removed isAdvancedDirty, now handled per-field

  return (
    <Modal
      title={t("models.localModelsTitle", { provider: provider.name })}
      open={open}
      onCancel={handleClose}
      footer={null}
      width={800}
      destroyOnHidden
    >
      {(loadingLocal || loadingStatus || loadingLocalConfig) &&
      localModels.length === 0 ? (
        <div className={styles.modelListEmpty}>{t("common.loading")}</div>
      ) : null}

      <section className={styles.localSection}>
        <LocalRuntimePanel
          serverStatus={serverStatus}
          hasUpdate={Boolean(serverUpdateStatus?.has_update)}
          progress={llamacppDownload}
          onStart={handleStartLlamacppDownload}
          onCancel={handleCancelLlamacppDownload}
          onStop={handleStopServer}
          stopping={stoppingServer}
        />
        {!isRuntimeInstalled ? (
          <div className={styles.localLockedPanel}>
            <div className={styles.localLockedPanelTitle}>
              {isRuntimeInstallable
                ? t("models.localRuntimeMissing")
                : t("models.localRuntimeUnsupported")}
            </div>
            <div className={styles.localLockedPanelDescription}>
              <div>{runtimeLockedMessage}</div>
              {!isRuntimeInstallable ? (
                <div>{t("models.localAlternativeRuntimeHint")}</div>
              ) : null}
            </div>
          </div>
        ) : null}
      </section>

      {isRuntimeInstalled ? (
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
        </section>
      ) : null}

      <section className={styles.localAdvancedConfigSection}>
        <div className={styles.localAdvancedConfigHeader}>
          <button
            type="button"
            className={styles.advancedConfigToggle}
            onClick={() => setAdvancedOpen((prev) => !prev)}
          >
            <span className={styles.advancedConfigToggleLabel}>
              {t("models.localAdvancedConfigTitle")}
            </span>
            <DownOutlined
              className={
                advancedOpen
                  ? styles.localAdvancedConfigChevronOpen
                  : styles.localAdvancedConfigChevronClosed
              }
            />
          </button>
        </div>

        {advancedOpen ? (
          <div className={styles.localAdvancedConfigFields}>
            <div
              className={`${styles.localAdvancedConfigField} ${styles.localAdvancedConfigFieldRow}`}
            >
              <div
                className={`${styles.localAdvancedConfigLabel} ${styles.localAdvancedConfigLabelRow}`}
              >
                <span>{t("models.localMaxContextLengthLabel")}</span>
                <Button
                  type="primary"
                  size="small"
                  icon={<SaveOutlined />}
                  loading={advancedSaving}
                  disabled={maxContextLength === savedMaxContextLength}
                  onClick={() => {
                    if (maxContextLength !== savedMaxContextLength) {
                      void handleSaveMaxContextLength();
                    }
                  }}
                >
                  {t("models.save")}
                </Button>
              </div>
              <InputNumber
                min={MIN_LOCAL_MAX_CONTEXT_LENGTH}
                step={1024}
                precision={0}
                value={maxContextLength}
                onChange={(value) =>
                  setMaxContextLength(
                    typeof value === "number"
                      ? Math.trunc(value)
                      : DEFAULT_LOCAL_MAX_CONTEXT_LENGTH,
                  )
                }
                className={styles.localAdvancedConfigInput}
                placeholder={t("models.localMaxContextLengthPlaceholder")}
              />
              <div className={styles.localAdvancedConfigHint}>
                {t("models.localMaxContextLengthHint")}
              </div>
            </div>

            <div
              className={`${styles.localAdvancedConfigField} ${styles.localAdvancedConfigFieldRow}`}
            >
              <div
                className={`${styles.localAdvancedConfigLabel} ${styles.localAdvancedConfigLabelRow}`}
              >
                <span>{t("models.localServerPortLabel")}</span>
                <Button
                  type="primary"
                  size="small"
                  icon={<SaveOutlined />}
                  loading={advancedSaving}
                  disabled={serverPort === savedServerPort}
                  onClick={() => {
                    if (serverPort !== savedServerPort) {
                      void handleSaveServerPort();
                    }
                  }}
                >
                  {t("models.save")}
                </Button>
              </div>
              <InputNumber
                min={MIN_LOCAL_SERVER_PORT}
                max={MAX_LOCAL_SERVER_PORT}
                step={1}
                precision={0}
                value={serverPort}
                onChange={(value) =>
                  setServerPort(
                    typeof value === "number" ? Math.trunc(value) : null,
                  )
                }
                className={styles.localAdvancedConfigInput}
                placeholder={t("models.localServerPortPlaceholder")}
              />
              <div className={styles.localAdvancedConfigHint}>
                {t("models.localServerPortHint")}
              </div>
            </div>

            <div className={styles.localAdvancedConfigField}>
              <div
                className={`${styles.localAdvancedConfigLabel} ${styles.localAdvancedConfigLabelRow}`}
              >
                <span>{t("models.modelGenerateConfig")}</span>
                <Button
                  type="primary"
                  size="small"
                  icon={<SaveOutlined />}
                  loading={advancedSaving}
                  disabled={
                    generateKwargsText === savedGenerateKwargsText ||
                    Boolean(generateKwargsError)
                  }
                  onClick={() => {
                    if (
                      generateKwargsText !== savedGenerateKwargsText &&
                      !generateKwargsError
                    ) {
                      void handleSaveGenerateKwargs();
                    }
                  }}
                >
                  {t("models.save")}
                </Button>
              </div>
              <JsonConfigEditor
                value={generateKwargsText}
                onChange={setGenerateKwargsText}
                placeholder={`Example:\n{\n  "temperature": 0.7,\n  "top_p": 0.95\n}`}
                variant="expanded"
              />
              {generateKwargsError ? (
                <div className={styles.localAdvancedConfigError}>
                  {generateKwargsError}
                </div>
              ) : null}
              <div className={styles.localAdvancedConfigHint}>
                {t("models.localGenerateConfigHint")}
              </div>
            </div>
          </div>
        ) : null}
      </section>
    </Modal>
  );
}
