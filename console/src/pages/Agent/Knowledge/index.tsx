import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  Button,
  Card,
  Drawer,
  Empty,
  Form,
  Input,
  InputNumber,
  Modal,
  Select,
  Switch,
  Tag,
  message,
} from "@agentscope-ai/design";
import { Divider, Progress, Segmented, Space, Spin, Typography } from "antd";
import { useNavigate } from "react-router-dom";
import {
  BookOutlined,
  DatabaseOutlined,
  DeleteOutlined,
  MoonOutlined,
  PlusOutlined,
  ReloadOutlined,
  SearchOutlined,
} from "@ant-design/icons";
import { useTranslation } from "react-i18next";
import api from "../../../api";
import { getApiToken, getApiUrl } from "../../../api/config";
import type {
  AgentsRunningConfig,
  KnowledgeConfig,
  KnowledgeHistoryBackfillProgress,
  KnowledgeHistoryBackfillStatus,
  KnowledgeSearchHit,
  KnowledgeSourceContent,
  KnowledgeSourceItem,
  KnowledgeSourceSpec,
  KnowledgeSourceType,
} from "../../../api/types";
import { MarkdownCopy } from "../../../components/MarkdownCopy/MarkdownCopy";
import styles from "./index.module.less";

const KNOWLEDGE_NOTE_STYLE_STORAGE_KEY = "copaw_knowledge_note_style";

type KnowledgeNoteStyle = "notion" | "obsidian";

const SOURCE_TYPE_OPTIONS: Array<{
  label: string;
  value: KnowledgeSourceType;
}> = [
  { label: "File", value: "file" },
  { label: "Directory", value: "directory" },
  { label: "URL", value: "url" },
  { label: "Text", value: "text" },
  { label: "Chat", value: "chat" },
];

type SourceOriginFilter = "all" | "manual" | "auto";

function inferSourceOrigin(source: KnowledgeSourceItem): Exclude<
  SourceOriginFilter,
  "all"
> {
  const tags = source.tags || [];
  const isAuto =
    tags.includes("auto") ||
    tags.includes("origin:auto") ||
    source.id.startsWith("auto-");
  return isAuto ? "auto" : "manual";
}

function getSourceOriginText(
  source: KnowledgeSourceItem,
  t: (key: string) => string,
): string {
  const origin = inferSourceOrigin(source);
  return origin === "manual"
    ? t("knowledge.originManual")
    : t("knowledge.originAuto");
}

function formatRemoteStatus(
  source: KnowledgeSourceItem,
  t: (key: string, options?: Record<string, unknown>) => string,
): string {
  const state = source.status.remote_cache_state;
  if (!state) {
    return "";
  }
  if (state === "cached") {
    return t("knowledge.remoteStateCached");
  }
  if (state === "waiting_retry") {
    return t("knowledge.remoteStateWaitingRetry", {
      time: source.status.remote_next_retry_at || "-",
    });
  }
  if (state === "ready_retry") {
    return t("knowledge.remoteStateReadyRetry");
  }
  if (state === "missing") {
    return t("knowledge.remoteStateMissing");
  }
  return t("knowledge.remoteStateUnknown");
}

function KnowledgePage() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const [form] = Form.useForm<KnowledgeSourceSpec>();
  const [enableConfigForm] = Form.useForm<AgentsRunningConfig>();
  const [config, setConfig] = useState<KnowledgeConfig | null>(null);
  const [runningConfig, setRunningConfig] = useState<AgentsRunningConfig | null>(
    null,
  );
  const [backfillStatus, setBackfillStatus] =
    useState<KnowledgeHistoryBackfillStatus | null>(null);
  const [backfillProgress, setBackfillProgress] =
    useState<KnowledgeHistoryBackfillProgress | null>(null);
  const [sources, setSources] = useState<KnowledgeSourceItem[]>([]);
  const [hits, setHits] = useState<KnowledgeSearchHit[]>([]);
  const [searchQuery, setSearchQuery] = useState("");
  const [searchTypeFilter, setSearchTypeFilter] = useState<
    KnowledgeSourceType | "all"
  >("all");
  const [searching, setSearching] = useState(false);
  const [sourceOriginFilter, setSourceOriginFilter] =
    useState<SourceOriginFilter>("all");
  const [sourceTypeFilter, setSourceTypeFilter] = useState<
    KnowledgeSourceType | "all"
  >("all");
  const [loading, setLoading] = useState(false);
  const [modalOpen, setModalOpen] = useState(false);
  const [enableModalOpen, setEnableModalOpen] = useState(false);
  const [enableModalNeedsBackfillChoice, setEnableModalNeedsBackfillChoice] =
    useState(false);
  const [enableModalSubmitting, setEnableModalSubmitting] = useState(false);
  const [saving, setSaving] = useState(false);
  const [indexingAll, setIndexingAll] = useState(false);
  const [clearingKnowledge, setClearingKnowledge] = useState(false);
  const [indexingId, setIndexingId] = useState<string | null>(null);
  const [detailDrawerOpen, setDetailDrawerOpen] = useState(false);
  const [selectedSource, setSelectedSource] =
    useState<KnowledgeSourceItem | null>(null);
  const [sourceContent, setSourceContent] =
    useState<KnowledgeSourceContent | null>(null);
  const [sourceContentLoading, setSourceContentLoading] = useState(false);
  const [backfillingHistory, setBackfillingHistory] = useState(false);
  const [selectedType, setSelectedType] = useState<KnowledgeSourceType>("file");
  const [isFileDragActive, setIsFileDragActive] = useState(false);
  const [selectedUploadFile, setSelectedUploadFile] = useState<File | null>(null);
  const [selectedFileName, setSelectedFileName] = useState("");
  const [selectedDirectoryFiles, setSelectedDirectoryFiles] = useState<
    Array<{ file: File; relativePath: string }>
  >([]);
  const [selectedDirectorySummary, setSelectedDirectorySummary] = useState("");
  const [noteStyle, setNoteStyle] = useState<KnowledgeNoteStyle>(() => {
    if (typeof window === "undefined") {
      return "notion";
    }
    const saved = window.localStorage.getItem(KNOWLEDGE_NOTE_STYLE_STORAGE_KEY);
    if (saved === "obsidian" || saved === "notion") {
      return saved;
    }
    return "notion";
  });
  const singleFileInputRef = useRef<HTMLInputElement>(null);
  const directoryInputRef = useRef<HTMLInputElement>(null);
  const remoteStateRef = useRef<Record<string, string | undefined>>({});
  const hasLoadedOnceRef = useRef(false);
  const backfillProgressWsRef = useRef<WebSocket | null>(null);
  const backfillProgressReconnectTimerRef = useRef<number | null>(null);

  const loadData = useCallback(async () => {
    setLoading(true);
    try {
      const [knowledgeConfig, sourceData, runtimeConfig, historyStatus] = await Promise.all([
        api.getKnowledgeConfig(),
        api.listKnowledgeSources(),
        api.getAgentRunningConfig(),
        api.getKnowledgeHistoryBackfillStatus(),
      ]);

      const nextRemoteStateMap: Record<string, string | undefined> = {};
      sourceData.sources.forEach((source) => {
        nextRemoteStateMap[source.id] = source.status.remote_cache_state;
      });

      if (hasLoadedOnceRef.current) {
        const recoveredSources = sourceData.sources.filter((source) => {
          const currentState = source.status.remote_cache_state;
          const previousState = remoteStateRef.current[source.id];
          return (
            currentState === "cached" &&
            previousState !== "cached" &&
            previousState !== undefined
          );
        });
        recoveredSources.slice(0, 2).forEach((source) => {
          message.success(
            t("knowledge.remoteRecovered", {
              name: source.name,
            }),
          );
        });
      }

      remoteStateRef.current = nextRemoteStateMap;
      hasLoadedOnceRef.current = true;
      setConfig(knowledgeConfig);
      setSources(sourceData.sources);
      setRunningConfig(runtimeConfig);
      setBackfillStatus(historyStatus);
      setBackfillProgress(historyStatus.progress ?? null);
    } catch (error) {
      console.error("Failed to load knowledge data", error);
      message.error(t("knowledge.loadFailed"));
    } finally {
      setLoading(false);
    }
  }, [t]);

  const refreshKnowledgeCards = useCallback(async () => {
    try {
      const sourceData = await api.listKnowledgeSources();
      const nextRemoteStateMap: Record<string, string | undefined> = {};
      sourceData.sources.forEach((source) => {
        nextRemoteStateMap[source.id] = source.status.remote_cache_state;
      });
      remoteStateRef.current = nextRemoteStateMap;
      setSources(sourceData.sources);
    } catch {
      // best-effort polling during backfill, ignore transient errors
    }
  }, []);

  useEffect(() => {
    loadData();
  }, [loadData]);

  useEffect(() => {
    if (typeof window === "undefined") {
      return;
    }
    window.localStorage.setItem(KNOWLEDGE_NOTE_STYLE_STORAGE_KEY, noteStyle);
  }, [noteStyle]);

  // While history backfill is running, poll existing sources API to refresh cards.
  useEffect(() => {
    if (!backfillProgress?.running) {
      return;
    }

    refreshKnowledgeCards();
    const id = window.setInterval(() => {
      refreshKnowledgeCards();
    }, 3000);

    return () => {
      window.clearInterval(id);
    };
  }, [backfillProgress?.running, refreshKnowledgeCards]);

  useEffect(() => {
    let disposed = false;

    const connect = () => {
      if (disposed) {
        return;
      }
      const baseUrl = getApiUrl("/knowledge/history-backfill/progress/ws");
      const wsUrl = new URL(baseUrl, window.location.origin);
      wsUrl.protocol = wsUrl.protocol === "https:" ? "wss:" : "ws:";
      wsUrl.searchParams.set("interval_ms", "1000");
      const token = getApiToken();
      if (token) {
        wsUrl.searchParams.set("token", token);
      }

      const ws = new WebSocket(wsUrl.toString());
      backfillProgressWsRef.current = ws;

      ws.onmessage = (event) => {
        if (disposed) {
          return;
        }
        try {
          const payload = JSON.parse(event.data || "{}");
          const progress = payload?.progress;
          if (!progress || typeof progress !== "object") {
            return;
          }
          setBackfillProgress(progress as KnowledgeHistoryBackfillProgress);
        } catch {
          // ignore malformed websocket messages
        }
      };

      ws.onclose = () => {
        if (disposed) {
          return;
        }
        backfillProgressReconnectTimerRef.current = window.setTimeout(() => {
          connect();
        }, 1500);
      };
    };

    connect();

    return () => {
      disposed = true;
      if (backfillProgressReconnectTimerRef.current) {
        window.clearTimeout(backfillProgressReconnectTimerRef.current);
        backfillProgressReconnectTimerRef.current = null;
      }
      if (backfillProgressWsRef.current) {
        backfillProgressWsRef.current.close();
        backfillProgressWsRef.current = null;
      }
    };
  }, []);

  useEffect(() => {
    if (directoryInputRef.current) {
      directoryInputRef.current.setAttribute("webkitdirectory", "");
      directoryInputRef.current.setAttribute("directory", "");
    }
  }, []);

  const resetDraftState = useCallback(() => {
    setSelectedType("file");
    setIsFileDragActive(false);
    setSelectedUploadFile(null);
    setSelectedFileName("");
    setSelectedDirectoryFiles([]);
    setSelectedDirectorySummary("");
    if (singleFileInputRef.current) {
      singleFileInputRef.current.value = "";
    }
    if (directoryInputRef.current) {
      directoryInputRef.current.value = "";
    }
  }, []);

  const persistKnowledgeConfig = useCallback(
    async (nextConfig: KnowledgeConfig) => {
      try {
        const updated = await api.updateKnowledgeConfig(nextConfig);
        setConfig(updated);
        message.success(t("knowledge.configSaved"));
        return updated;
      } catch (error) {
        console.error("Failed to update knowledge config", error);
        message.error(t("knowledge.configSaveFailed"));
        return null;
      }
    },
    [t],
  );

  const handleRunHistoryBackfillNow = useCallback(async () => {
    try {
      setBackfillingHistory(true);
      const response = await api.runKnowledgeHistoryBackfillNow();
      setBackfillStatus(response.status);
      const processed = response.result.processed_sessions ?? 0;
      if (response.result.skipped) {
        message.info(t("knowledge.backfillSkipped"));
      } else {
        message.success(
          t("knowledge.backfillSuccess", {
            count: processed,
          }),
        );
      }
      await loadData();
    } catch (error) {
      console.error("Failed to run knowledge history backfill", error);
      message.error(t("knowledge.backfillFailed"));
    } finally {
      setBackfillingHistory(false);
    }
  }, [loadData, t]);

  const closeEnableModal = useCallback(() => {
    if (enableModalSubmitting) {
      return;
    }
    setEnableModalOpen(false);
    setEnableModalNeedsBackfillChoice(false);
  }, [enableModalSubmitting]);

  const openEnableModal = useCallback(
    (needsBackfillChoice: boolean) => {
      if (!runningConfig) {
        return;
      }
      enableConfigForm.setFieldsValue(runningConfig);
      setEnableModalNeedsBackfillChoice(needsBackfillChoice);
      setEnableModalOpen(true);
    },
    [enableConfigForm, runningConfig],
  );

  const handleConfirmEnable = useCallback(
    async (runBackfillNow: boolean) => {
      if (!config) {
        return;
      }
      try {
        const nextRunningConfig = await enableConfigForm.validateFields();
        setEnableModalSubmitting(true);
        const updatedRunningConfig = await api.updateAgentRunningConfig(
          nextRunningConfig as AgentsRunningConfig,
        );
        setRunningConfig(updatedRunningConfig);
        const updatedKnowledge = await persistKnowledgeConfig({
          ...config,
          enabled: true,
        });
        if (!updatedKnowledge) {
          return;
        }
        setEnableModalOpen(false);
        setEnableModalNeedsBackfillChoice(false);
        if (runBackfillNow) {
          await handleRunHistoryBackfillNow();
        } else if (enableModalNeedsBackfillChoice) {
          message.info(t("knowledge.backfillDeferredHint"));
          await loadData();
        }
      } catch (error) {
        if (error instanceof Error && "errorFields" in error) {
          return;
        }
        console.error("Failed to enable knowledge with runtime config", error);
        message.error(t("knowledge.configSaveFailed"));
      } finally {
        setEnableModalSubmitting(false);
      }
    },
    [
      config,
      enableConfigForm,
      enableModalNeedsBackfillChoice,
      handleRunHistoryBackfillNow,
      loadData,
      persistKnowledgeConfig,
      t,
    ],
  );

  const handleToggleEnabled = async (checked: boolean) => {
    if (!config) {
      return;
    }

    if (!checked) {
      await persistKnowledgeConfig({
        ...config,
        enabled: false,
      });
      return;
    }

    const firstEnableWithPendingHistory =
      !config.enabled &&
      Boolean(backfillStatus?.has_pending_history) &&
      !backfillStatus?.has_backfill_record;

    if (firstEnableWithPendingHistory) {
      openEnableModal(true);
      return;
    }

    openEnableModal(false);
  };

  const handleAddSource = async () => {
    try {
      const values = await form.validateFields();
      setSaving(true);
      const sourceId = `manual-${values.type}-${Math.random().toString(36).slice(2, 8)}`;
      let location = values.location ?? "";
      let content = values.content ?? "";

      if (values.type === "file") {
        if (!selectedUploadFile) {
          message.error(t("knowledge.fileRequired"));
          return;
        }
        const uploaded = await api.uploadKnowledgeFile(sourceId, selectedUploadFile);
        location = uploaded.location;
        content = "";
      }

      if (values.type === "directory") {
        if (selectedDirectoryFiles.length === 0) {
          message.error(t("knowledge.directoryRequired"));
          return;
        }
        const uploaded = await api.uploadKnowledgeDirectory(
          sourceId,
          selectedDirectoryFiles,
        );
        location = uploaded.location;
        content = "";
      }

      const payload = {
        ...values,
        id: sourceId,
        name: sourceId,
        location,
        content,
        recursive: values.recursive ?? true,
        tags: values.tags ?? [],
        description: values.description ?? "",
      };

      await api.upsertKnowledgeSource(payload);

      if (
        values.type === "url" ||
        values.type === "chat" ||
        values.type === "file" ||
        values.type === "directory"
      ) {
        await api.indexKnowledgeSource(sourceId);
      }

      message.success(t("knowledge.sourceSaved"));
      setModalOpen(false);
      form.resetFields();
      resetDraftState();
      await loadData();
    } catch (error) {
      if ((error as Error)?.message) {
        console.error("Failed to save knowledge source", error);
      }
    } finally {
      setSaving(false);
    }
  };

  const handleIndexSource = useCallback(async (sourceId: string) => {
    try {
      setIndexingId(sourceId);
      await api.indexKnowledgeSource(sourceId);
      message.success(t("knowledge.indexSuccess"));
      await loadData();
    } catch (error) {
      console.error("Failed to index knowledge source", error);
      message.error(t("knowledge.indexFailed"));
    } finally {
      setIndexingId(null);
    }
  }, [loadData, t]);

  const handleIndexAll = async () => {
    try {
      setIndexingAll(true);
      await api.indexAllKnowledgeSources();
      message.success(t("knowledge.indexAllSuccess"));
      await loadData();
    } catch (error) {
      console.error("Failed to index all knowledge sources", error);
      message.error(t("knowledge.indexFailed"));
    } finally {
      setIndexingAll(false);
    }
  };

  const handleClearKnowledge = useCallback(() => {
    Modal.confirm({
      title: t("knowledge.clearConfirmTitle"),
      content: t("knowledge.clearConfirmContent"),
      okText: t("knowledge.clearConfirmOk"),
      cancelText: t("common.cancel"),
      okButtonProps: {
        danger: true,
      },
      onOk: async () => {
        try {
          setClearingKnowledge(true);
          const result = await api.clearKnowledge({ removeSources: true });
          message.success(
            t("knowledge.clearSuccess", {
              sources: result.cleared_sources,
              indexes: result.cleared_indexes,
            }),
          );
          await loadData();
        } catch (error) {
          console.error("Failed to clear knowledge", error);
          message.error(t("knowledge.clearFailed"));
        } finally {
          setClearingKnowledge(false);
        }
      },
    });
  }, [loadData, t]);

  const handleSearch = async () => {
    const query = searchQuery.trim();
    if (!query) {
      setHits([]);
      return;
    }
    try {
      setSearching(true);
      const result = await api.searchKnowledge({
        query,
        limit: 10,
        sourceTypes:
          searchTypeFilter === "all" ? undefined : [searchTypeFilter],
      });
      setHits(result.hits);
    } catch (error) {
      console.error("Failed to search knowledge", error);
      message.error(t("knowledge.searchFailed"));
    } finally {
      setSearching(false);
    }
  };

  const handleDeleteSource = useCallback(async (sourceId: string) => {
    try {
      await api.deleteKnowledgeSource(sourceId);
      message.success(t("knowledge.deleteSuccess"));
      await loadData();
    } catch (error) {
      console.error("Failed to delete knowledge source", error);
      message.error(t("knowledge.deleteFailed"));
    }
  }, [loadData, t]);

  const handleConfirmDeleteSource = useCallback(
    (sourceId: string, sourceName: string) => {
      Modal.confirm({
        title: t("knowledge.deleteConfirmTitle"),
        content: t("knowledge.deleteConfirmContent", { name: sourceName }),
        okText: t("common.delete"),
        cancelText: t("common.cancel"),
        okButtonProps: {
          danger: true,
        },
        onOk: async () => {
          await handleDeleteSource(sourceId);
        },
      });
    },
    [handleDeleteSource, t],
  );

  const handleFilePicked = (event: React.ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0] ?? null;
    setIsFileDragActive(false);
    setSelectedUploadFile(file);
    setSelectedFileName(file?.name ?? "");
  };

  const handleFileDrop = (event: React.DragEvent<HTMLDivElement>) => {
    event.preventDefault();
    setIsFileDragActive(false);
    const file = event.dataTransfer.files?.[0] ?? null;
    if (!file) {
      return;
    }
    setSelectedUploadFile(file);
    setSelectedFileName(file.name);
  };

  const handleFileDragOver = (event: React.DragEvent<HTMLDivElement>) => {
    event.preventDefault();
    if (!isFileDragActive) {
      setIsFileDragActive(true);
    }
  };

  const handleFileDragLeave = (event: React.DragEvent<HTMLDivElement>) => {
    event.preventDefault();
    if (event.currentTarget.contains(event.relatedTarget as Node | null)) {
      return;
    }
    setIsFileDragActive(false);
  };

  const handleDirectoryPicked = (
    event: React.ChangeEvent<HTMLInputElement>,
  ) => {
    const rawFiles = Array.from(event.target.files ?? []);
    const prepared = rawFiles.map((file) => ({
      file,
      relativePath:
        (file as File & { webkitRelativePath?: string }).webkitRelativePath ||
        file.name,
    }));
    setSelectedDirectoryFiles(prepared);
    if (prepared.length === 0) {
      setSelectedDirectorySummary("");
      return;
    }
    const topLevel = prepared[0].relativePath.split("/")[0];
    setSelectedDirectorySummary(
      t("knowledge.directorySelected", {
        name: topLevel,
        count: prepared.length,
      }),
    );
  };

  const filteredSources = useMemo(() => {
    return sources.filter((source) => {
      if (sourceOriginFilter !== "all") {
        const origin = inferSourceOrigin(source);
        if (origin !== sourceOriginFilter) return false;
      }
      if (sourceTypeFilter !== "all" && source.type !== sourceTypeFilter) {
        return false;
      }
      return true;
    });
  }, [sourceOriginFilter, sourceTypeFilter, sources]);

  const selectedSourceOriginText = useMemo(() => {
    if (!selectedSource) {
      return "";
    }
    return getSourceOriginText(selectedSource, t);
  }, [selectedSource, t]);

  const selectedSourceRemoteLine = useMemo(() => {
    if (!selectedSource) {
      return "";
    }
    return formatRemoteStatus(selectedSource, t);
  }, [selectedSource, t]);

  const selectedSourceIndexedCountText = useMemo(() => {
    if (!selectedSource) {
      return "-";
    }
    return selectedSource.status.indexed
      ? t("knowledge.indexedCount", {
          documents: selectedSource.status.document_count,
          chunks: selectedSource.status.chunk_count,
        })
      : "-";
  }, [selectedSource, t]);

  const openDetailDrawer = useCallback((record: KnowledgeSourceItem) => {
    setSelectedSource(record);
    setSourceContent(null);
    setDetailDrawerOpen(true);
    setSourceContentLoading(true);
    api.getKnowledgeSourceContent(record.id)
      .then((data) => setSourceContent(data))
      .catch(() => setSourceContent({ indexed: false, documents: [] }))
      .finally(() => setSourceContentLoading(false));
  }, []);

  const handleDetailDrawerValueKeyDown = useCallback(
    (
      event: React.KeyboardEvent<HTMLDivElement>,
      record: KnowledgeSourceItem,
    ) => {
      if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        openDetailDrawer(record);
      }
    },
    [openDetailDrawer],
  );

  const dragZoneClassName = `${styles.dragZone} ${
    isFileDragActive ? styles.dragZoneActive : ""
  }`;
  const enableModalAutoCollectLongText = Form.useWatch(
    "auto_collect_long_text",
    enableConfigForm,
  );
  const showBackfillNowButton = Boolean(
    config?.enabled &&
      backfillStatus?.marked_unbackfilled &&
      backfillStatus?.has_pending_history,
  );
  const unifiedBatchProgress = useMemo(() => {
    if (indexingAll) {
      return {
        visible: true,
        percent: 0,
        status: "active" as const,
        label: t("knowledge.unifiedProgressIndexAll"),
      };
    }

    if (backfillProgress?.running) {
      const total = Math.max(1, backfillProgress.total_sessions || 1);
      const traversed = Math.max(
        0,
        Math.min(total, backfillProgress.traversed_sessions || 0),
      );
      return {
        visible: true,
        percent: Math.round((traversed / total) * 100),
        status: "active" as const,
        label: t("knowledge.unifiedProgressBackfill", {
          traversed,
          total,
        }),
      };
    }

    if (backfillingHistory) {
      return {
        visible: true,
        percent: 0,
        status: "active" as const,
        label: t("knowledge.unifiedProgressBackfillStarting"),
      };
    }

    if (clearingKnowledge) {
      return {
        visible: true,
        percent: 0,
        status: "active" as const,
        label: t("knowledge.unifiedProgressClearing"),
      };
    }

    return {
      visible: false,
      percent: 0,
      status: "normal" as const,
      label: "",
    };
  }, [
    backfillProgress,
    backfillingHistory,
    clearingKnowledge,
    indexingAll,
    t,
  ]);

  const noteStyleOptions = useMemo(
    () => [
      {
        label: (
          <span className={styles.noteStyleOptionLabel}>
            <BookOutlined />
            <span className={styles.noteStyleOptionText}>
              {t("knowledge.noteStyleNotion")}
            </span>
          </span>
        ),
        value: "notion",
      },
      {
        label: (
          <span className={styles.noteStyleOptionLabel}>
            <MoonOutlined />
            <span className={styles.noteStyleOptionText}>
              {t("knowledge.noteStyleObsidian")}
            </span>
          </span>
        ),
        value: "obsidian",
      },
    ],
    [t],
  );

  const noteStyleClassName = useMemo(() => {
    if (noteStyle === "obsidian") {
      return styles.noteStyleObsidian;
    }
    return styles.noteStyleNotion;
  }, [noteStyle]);

  return (
    <div className={`${styles.knowledgePage} ${noteStyleClassName}`}>
      <div className={styles.header}>
        <div className={styles.headerInfo}>
          <Typography.Title level={3} className={styles.title}>
            <Space align="center" size={8}>
              <DatabaseOutlined />
              {t("knowledge.title")}
            </Space>
          </Typography.Title>
          <Typography.Paragraph className={styles.description}>
            {t("knowledge.description")}
          </Typography.Paragraph>
        </div>
        <div className={styles.headerActions}>
          <Typography.Text className={styles.noteStyleLabel}>
            {t("knowledge.noteStyle")}
          </Typography.Text>
          <Segmented
            options={noteStyleOptions}
            value={noteStyle}
            onChange={(value) => setNoteStyle(value as KnowledgeNoteStyle)}
            className={styles.noteStyleSegment}
          />
          <Typography.Text>{t("knowledge.enabled")}</Typography.Text>
          <Switch
            checked={config?.enabled ?? false}
            onChange={handleToggleEnabled}
          />
          <Button icon={<PlusOutlined />} onClick={() => setModalOpen(true)}>
            {t("knowledge.addSource")}
          </Button>
          <Button
            icon={<ReloadOutlined />}
            onClick={handleIndexAll}
            loading={indexingAll}
          >
            {t("knowledge.indexAll")}
          </Button>
          <Button onClick={() => navigate("/agent-config")}>
            {t("knowledge.goToRuntimeConfig")}
          </Button>
          <Button
            danger
            icon={<DeleteOutlined />}
            onClick={handleClearKnowledge}
            loading={clearingKnowledge}
          >
            {t("knowledge.clearKnowledge")}
          </Button>
          {showBackfillNowButton ? (
            <Button
              icon={<ReloadOutlined />}
              onClick={handleRunHistoryBackfillNow}
              loading={backfillingHistory}
            >
              {t("knowledge.backfillNowButton")}
            </Button>
          ) : null}
        </div>
      </div>

      {unifiedBatchProgress.visible ? (
        <div className={styles.unifiedProgressRow}>
          <Typography.Text className={styles.unifiedProgressLabel}>
            {unifiedBatchProgress.label}
          </Typography.Text>
          <Progress
            percent={unifiedBatchProgress.percent}
            size="small"
            status={unifiedBatchProgress.status}
          />
        </div>
      ) : null}

      <Space direction="vertical" size={16} className={styles.contentStack}>

      <Card>
        <Space className={styles.fullWidth} direction="vertical" size={12}>
          <div className={styles.searchHeader}>
            <Typography.Text >{t("knowledge.search")}</Typography.Text>
            {hits.length > 0 ? (
              <Tag color="blue">
                {t("knowledge.searchHitCount", { count: hits.length })}
              </Tag>
            ) : null}
          </div>
          <Space.Compact className={styles.fullWidth}>
            <Select
              value={searchTypeFilter}
              onChange={(value) =>
                setSearchTypeFilter(value as KnowledgeSourceType | "all")
              }
              options={[
                { label: t("knowledge.allTypes"), value: "all" },
                ...SOURCE_TYPE_OPTIONS,
              ]}
              className={styles.searchTypeSelect}
            />
            <Input
              value={searchQuery}
              onChange={(event) => setSearchQuery(event.target.value)}
              placeholder={t("knowledge.searchPlaceholder")}
              onPressEnter={handleSearch}
            />
            <Button
              type="primary"
              icon={<SearchOutlined />}
              loading={searching}
              onClick={handleSearch}
            >
              {t("knowledge.search")}
            </Button>
          </Space.Compact>
        </Space>
        <div className={styles.searchResultsWrap}>
          {hits.length === 0 ? (
            <Empty description={t("knowledge.searchEmpty")} />
          ) : (
            <Space direction="vertical" size={12} className={styles.fullWidth}>
              {hits.map((hit) => (
                <Card
                  key={`${hit.source_id}-${hit.document_path}-${hit.score}`}
                  className={styles.searchHitCard}
                >
                  <div className={styles.searchHitTopRow}>
                    <Space>
                      <Tag color="blue">{hit.source_name}</Tag>
                      <Tag>{hit.source_type}</Tag>
                    </Space>
                    <Tag color="geekblue">
                      {t("knowledge.scoreLabel", {
                        score: Number(hit.score).toFixed(2),
                      })}
                    </Tag>
                  </div>
                  <Typography.Text >{hit.document_title}</Typography.Text>
                  <Typography.Text type="secondary" className={styles.searchHitPath}>
                    {hit.document_path}
                  </Typography.Text>
                  <Typography.Paragraph className={styles.searchHitSnippet}>
                    {hit.snippet}
                  </Typography.Paragraph>
                </Card>
              ))}
            </Space>
          )}
        </div>
      </Card>

      <Card loading={loading}>
        <div className={styles.filterBar}>
          <div className={styles.filterGroup}>
            <Typography.Text className={styles.filterLabel}>
              {t("knowledge.sourceOriginFilter")}
            </Typography.Text>
            <Select
              value={sourceOriginFilter}
              onChange={(value) => setSourceOriginFilter(value as SourceOriginFilter)}
              options={[
                { label: t("knowledge.originAll"), value: "all" },
                { label: t("knowledge.originManual"), value: "manual" },
                { label: t("knowledge.originAuto"), value: "auto" },
              ]}
              className={styles.filterSelect}
            />
          </div>
          <div className={styles.filterGroup}>
            <Typography.Text className={styles.filterLabel}>
              {t("knowledge.sourceTypeFilter")}
            </Typography.Text>
            <Select
              value={sourceTypeFilter}
              onChange={(value) => setSourceTypeFilter(value as KnowledgeSourceType | "all")}
              options={[
                { label: t("knowledge.allTypes"), value: "all" },
                ...SOURCE_TYPE_OPTIONS,
              ]}
              className={styles.filterSelect}
            />
          </div>
        </div>
        {filteredSources.length === 0 ? (
          <Empty description={t("knowledge.empty")} />
        ) : (
          <div className={styles.cardsGrid}>
            {filteredSources.map((record) => {
              const originText = getSourceOriginText(record, t);
              const remoteLine = formatRemoteStatus(record, t);
              const isActiveCard = indexingId === record.id;
              const cardTitle = record.name?.trim() || "";
              const descriptionText = record.description?.trim() || "";
              const indexedCountText = record.status.indexed
                ? t("knowledge.indexedCount", {
                    documents: record.status.document_count,
                    chunks: record.status.chunk_count,
                  })
                : "-";
              return (
                <div key={record.id}>
                  <div
                    className={`${styles.cardContainer} ${isActiveCard ? styles.cardContainerActive : ""}`}
                    aria-busy={isActiveCard}
                  >
                        <div className={styles.cardHeader}>
                          <div className={styles.cardHeaderRow}>
                            <Typography.Text type="secondary" className={styles.cardHeaderId}>
                              {record.id}
                            </Typography.Text>
                            <span className={styles.typeTag}>{record.type}</span>
                            <span className={styles.originTag}>{originText}</span>
                          </div>
                        </div>

                        <div className={styles.cardMeta}>
                          {cardTitle ? (
                            <div className={styles.infoSection}>
                              <div className={styles.infoLabel}>
                                {t("knowledge.table.title")}
                              </div>
                              <div
                                role="button"
                                tabIndex={0}
                                onClick={() => openDetailDrawer(record)}
                                onKeyDown={(event) =>
                                  handleDetailDrawerValueKeyDown(event, record)
                                }
                                className={`${styles.infoBlock} ${styles.clickableBlock}`}
                                title={cardTitle}
                              >
                                <Typography.Text
                                  className={styles.cardTitle}
                                  title={cardTitle}
                                >
                                  {cardTitle}
                                </Typography.Text>
                              </div>
                            </div>
                          ) : null}

                          <div className={styles.infoSection}>
                            <div className={styles.infoLabel}>
                              {t("knowledge.table.source")}
                            </div>
                            <div
                              role="button"
                              tabIndex={0}
                              onClick={() => openDetailDrawer(record)}
                              onKeyDown={(event) =>
                                handleDetailDrawerValueKeyDown(event, record)
                              }
                              className={`${styles.infoBlock} ${styles.clickableBlock}`}
                              title={descriptionText || t("knowledge.inlineText")}
                            >
                              <Typography.Text
                                className={styles.cardTitle}
                                title={descriptionText || t("knowledge.inlineText")}
                              >
                                {descriptionText || t("knowledge.inlineText")}
                              </Typography.Text>
                            </div>
                          </div>

                          {record.location ? (
                            <div className={styles.infoSection}>
                              <div className={styles.infoLabel}>
                                {t("knowledge.table.location")}
                              </div>
                              <div
                                role="button"
                                tabIndex={0}
                                onClick={() => openDetailDrawer(record)}
                                onKeyDown={(event) =>
                                  handleDetailDrawerValueKeyDown(event, record)
                                }
                                className={`${styles.infoBlock} ${styles.singleLineValue} ${styles.clickableBlock}`}
                                title={record.location}
                              >
                                {record.location}
                              </div>
                            </div>
                          ) : null}

                          <div className={styles.infoSection}>
                            <div className={styles.infoLabel}>
                              {t("knowledge.statusAndStats")}
                            </div>
                            <div
                              role="button"
                              tabIndex={0}
                              onClick={() => openDetailDrawer(record)}
                              onKeyDown={(event) =>
                                handleDetailDrawerValueKeyDown(event, record)
                              }
                              className={`${styles.infoBlock} ${styles.clickableBlock}`}
                            >
                              <div className={styles.statusRow}>
                                <div>
                                  <span
                                    className={
                                      record.status.indexed
                                        ? styles.indexedTag
                                        : styles.notIndexedTag
                                    }
                                  >
                                    {record.status.indexed
                                      ? t("knowledge.indexed")
                                      : t("knowledge.notIndexed")}
                                  </span>
                                </div>
                                <Typography.Text type="secondary">
                                  {indexedCountText}
                                </Typography.Text>
                              </div>
                              {remoteLine ? (
                                <div className={styles.statusSubRow}>
                                  <Typography.Text type="secondary">Remote</Typography.Text>
                                  <Typography.Text type="secondary">{remoteLine}</Typography.Text>
                                </div>
                              ) : null}
                              {record.status.remote_last_error ? (
                                <Typography.Text type="secondary" className={styles.remoteError}>
                                  {t("knowledge.remoteLastError", {
                                    error: record.status.remote_last_error,
                                  })}
                                </Typography.Text>
                              ) : null}
                            </div>
                          </div>
                        </div>

                        <div className={styles.cardFooter}>
                          <div className={styles.actionRow}>
                            <Button
                              type="link"
                              size="small"
                              className={styles.actionButton}
                              loading={indexingId === record.id}
                              onClick={() => handleIndexSource(record.id)}
                            >
                              {record.status.indexed
                                ? t("knowledge.reindex")
                                : t("knowledge.indexNow")}
                            </Button>
                            <Button
                              type="text"
                              size="small"
                              danger
                              icon={<DeleteOutlined />}
                              className={styles.deleteButton}
                              onClick={() =>
                                handleConfirmDeleteSource(record.id, record.name)
                              }
                              title={t("common.delete")}
                            />
                          </div>
                        </div>
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </Card>

      </Space>

      <Modal
        open={modalOpen}
        title={t("knowledge.addSource")}
        onOk={handleAddSource}
        onCancel={() => {
          setModalOpen(false);
          form.resetFields();
          resetDraftState();
        }}
        confirmLoading={saving}
        destroyOnClose
      >
        <Form
          form={form}
          layout="vertical"
          initialValues={{
            type: "file",
            recursive: true,
            enabled: true,
            location: "",
            content: "",
            tags: [],
            description: "",
          }}
        >
          <Form.Item
            name="type"
            label={t("knowledge.form.type")}
            rules={[{ required: true }]}
          >
            <Select
              options={SOURCE_TYPE_OPTIONS}
              onChange={(value) => {
                setSelectedType(value as KnowledgeSourceType);
                setIsFileDragActive(false);
                setSelectedUploadFile(null);
                setSelectedFileName("");
                setSelectedDirectoryFiles([]);
                setSelectedDirectorySummary("");
                form.setFieldsValue({ location: "", content: "" });
              }}
            />
          </Form.Item>
          {selectedType === "file" && (
            <Form.Item label={t("knowledge.form.fileUpload")}>
              <Space direction="vertical" size={8} className={styles.fullWidth}>
                <div
                  onClick={() => singleFileInputRef.current?.click()}
                  onDrop={handleFileDrop}
                  onDragOver={handleFileDragOver}
                  onDragLeave={handleFileDragLeave}
                  role="button"
                  tabIndex={0}
                  onKeyDown={(event) => {
                    if (event.key === "Enter" || event.key === " ") {
                      event.preventDefault();
                      singleFileInputRef.current?.click();
                    }
                  }}
                  className={dragZoneClassName}
                >
                  <Space direction="vertical" size={6} className={styles.fullWidth}>
                    <Typography.Text >
                      {t("knowledge.dragFileTitle")}
                    </Typography.Text>
                    <Typography.Text type="secondary">
                      {t("knowledge.dragFileHint")}
                    </Typography.Text>
                    <Typography.Text type="secondary">
                      {selectedFileName || t("knowledge.noFileSelected")}
                    </Typography.Text>
                  </Space>
                </div>
                <Button onClick={() => singleFileInputRef.current?.click()}>
                  {t("knowledge.pickFile")}
                </Button>
                <Typography.Text type="secondary">
                  {t("knowledge.fileUploadHint")}
                </Typography.Text>
              </Space>
            </Form.Item>
          )}
          {selectedType === "directory" && (
            <Form.Item label={t("knowledge.form.directoryUpload")}>
              <Space direction="vertical" size={8} className={styles.fullWidth}>
                <Button onClick={() => directoryInputRef.current?.click()}>
                  {t("knowledge.pickDirectory")}
                </Button>
                <Typography.Text type="secondary">
                  {selectedDirectorySummary || t("knowledge.noDirectorySelected")}
                </Typography.Text>
              </Space>
            </Form.Item>
          )}
          {selectedType === "url" && (
            <>
              <Form.Item
                name="location"
                label={t("knowledge.form.location")}
                rules={[{ required: true }]}
              >
                <Input placeholder={t("knowledge.form.urlPlaceholder")} />
              </Form.Item>
              <Typography.Text type="secondary">
                {t("knowledge.urlHint")}
              </Typography.Text>
            </>
          )}
          {selectedType === "text" && (
            <Form.Item
              name="content"
              label={t("knowledge.form.content")}
              rules={[{ required: true }]}
            >
              <Input.TextArea rows={5} placeholder={t("knowledge.form.contentPlaceholder")} />
            </Form.Item>
          )}
          {selectedType === "chat" && (
            <>
              <Form.Item
                name="location"
                label={t("knowledge.form.chatSessionId")}
                rules={[{ required: true }]}
              >
                <Input placeholder={t("knowledge.chatSessionIdPlaceholder")} />
              </Form.Item>
              <Typography.Text type="secondary">
                {t("knowledge.chatHint")}
              </Typography.Text>
            </>
          )}
          <Form.Item name="description" label={t("knowledge.form.description")}>
            <Input placeholder={t("knowledge.form.descriptionPlaceholder")} />
          </Form.Item>
          <Form.Item name="enabled" valuePropName="checked">
            <Switch checkedChildren={t("knowledge.form.enabled")} unCheckedChildren={t("knowledge.form.disabled")} />
          </Form.Item>
        </Form>
      </Modal>
      <Modal
        open={enableModalOpen}
        title={t("knowledge.enableConfirmTitle")}
        onCancel={closeEnableModal}
        footer={
          enableModalNeedsBackfillChoice ? (
            <Space>
              <Button onClick={closeEnableModal}>{t("common.cancel")}</Button>
              <Button
                loading={enableModalSubmitting}
                onClick={() => void handleConfirmEnable(false)}
              >
                {t("knowledge.enableAndBackfillLater")}
              </Button>
              <Button
                type="primary"
                loading={enableModalSubmitting}
                onClick={() => void handleConfirmEnable(true)}
              >
                {t("knowledge.enableAndBackfillNow")}
              </Button>
            </Space>
          ) : (
            <Space>
              <Button onClick={closeEnableModal}>{t("common.cancel")}</Button>
              <Button
                type="primary"
                loading={enableModalSubmitting}
                onClick={() => void handleConfirmEnable(false)}
              >
                {t("knowledge.enableConfirmOk")}
              </Button>
            </Space>
          )
        }
        destroyOnClose={false}
      >
        <Space direction="vertical" size={12} className={styles.fullWidth}>
          <Typography.Paragraph style={{ marginBottom: 0 }}>
            {t("knowledge.enableConfirmDescription")}
          </Typography.Paragraph>
          <Form
            form={enableConfigForm}
            layout="vertical"
            className={styles.enableConfigForm}
          >
            <Form.Item
              label={t("agentConfig.autoCollectChatFiles")}
              name="auto_collect_chat_files"
              valuePropName="checked"
              tooltip={t("agentConfig.autoCollectChatFilesTooltip")}
            >
              <Switch />
            </Form.Item>
            <Form.Item
              label={t("agentConfig.autoCollectChatUrls")}
              name="auto_collect_chat_urls"
              valuePropName="checked"
              tooltip={t("agentConfig.autoCollectChatUrlsTooltip")}
            >
              <Switch />
            </Form.Item>
            <Form.Item
              label={t("agentConfig.autoCollectLongText")}
              name="auto_collect_long_text"
              valuePropName="checked"
              tooltip={t("agentConfig.autoCollectLongTextTooltip")}
            >
              <Switch />
            </Form.Item>
            <Form.Item
              label={t("agentConfig.longTextMinChars")}
              name="long_text_min_chars"
              rules={[
                {
                  required: true,
                  message: t("agentConfig.longTextMinCharsRequired"),
                },
                {
                  type: "number",
                  min: 200,
                  message: t("agentConfig.longTextMinCharsMin"),
                },
              ]}
              tooltip={t("agentConfig.longTextMinCharsTooltip")}
            >
              <InputNumber
                style={{ width: "100%" }}
                min={200}
                max={20000}
                step={100}
                disabled={!enableModalAutoCollectLongText}
                placeholder={t("agentConfig.longTextMinCharsPlaceholder")}
              />
            </Form.Item>
            <Form.Item
              label={t("agentConfig.knowledgeChunkSize")}
              name="knowledge_chunk_size"
              rules={[
                {
                  required: true,
                  message: t("agentConfig.knowledgeChunkSizeRequired"),
                },
                {
                  type: "number",
                  min: 200,
                  message: t("agentConfig.knowledgeChunkSizeMin"),
                },
              ]}
              tooltip={t("agentConfig.knowledgeChunkSizeTooltip")}
            >
              <InputNumber
                style={{ width: "100%" }}
                min={200}
                max={8000}
                step={100}
                placeholder={t("agentConfig.knowledgeChunkSizePlaceholder")}
              />
            </Form.Item>
          </Form>
          {enableModalNeedsBackfillChoice ? (
            <Typography.Paragraph className={styles.enableBackfillHint}>
              {t("knowledge.firstEnableBackfillPrompt", {
                count: backfillStatus?.history_chat_count ?? 0,
              })}
            </Typography.Paragraph>
          ) : (
            <Typography.Paragraph className={styles.enableBackfillHint}>
              {t("knowledge.enableConfigInlineHint")}
            </Typography.Paragraph>
          )}
        </Space>
      </Modal>
      <Drawer
        width={520}
        placement="right"
        title={selectedSource?.name?.trim() || t("knowledge.form.id")}
        open={detailDrawerOpen}
        onClose={() => setDetailDrawerOpen(false)}
        destroyOnClose
      >
        {selectedSource ? (
          <Space direction="vertical" size={12} className={styles.fullWidth}>
            {selectedSource.name?.trim() ? (
              <div className={styles.infoSection}>
                <div className={styles.infoLabel}>{t("knowledge.table.title")}</div>
                <div className={`${styles.infoBlock} ${styles.singleLineValue}`}>
                  {selectedSource.name}
                </div>
              </div>
            ) : null}

            <div className={styles.infoSection}>
              <div className={styles.infoLabel}>{t("knowledge.table.source")}</div>
              <div className={styles.infoBlock}>
                {selectedSource.description || t("knowledge.inlineText")}
              </div>
            </div>

            <div className={styles.detailTagRow}>
              <span className={styles.originTag}>{selectedSourceOriginText}</span>
              <span className={styles.typeTag}>{selectedSource.type}</span>
            </div>

            <div className={styles.infoSection}>
              <div className={styles.infoLabel}>{t("knowledge.form.id")}</div>
              <div className={`${styles.infoBlock} ${styles.singleLineValue}`}>
                {selectedSource.id}
              </div>
            </div>

            {selectedSource.location ? (
              <div className={styles.infoSection}>
                <div className={styles.infoLabel}>{t("knowledge.table.location")}</div>
                <div className={styles.infoBlock}>{selectedSource.location}</div>
              </div>
            ) : null}

            <div className={styles.infoSection}>
              <div className={styles.infoLabel}>{t("knowledge.table.chunkStats")}</div>
              <div className={`${styles.infoBlock} ${styles.singleLineValue}`}>
                {selectedSourceIndexedCountText}
              </div>
            </div>

            <div className={styles.infoSection}>
              <div className={styles.infoLabel}>{t("knowledge.table.status")}</div>
              <div>
                <span
                  className={
                    selectedSource.status.indexed
                      ? styles.indexedTag
                      : styles.notIndexedTag
                  }
                >
                  {selectedSource.status.indexed
                    ? t("knowledge.indexed")
                    : t("knowledge.notIndexed")}
                </span>
              </div>
            </div>

            {selectedSourceRemoteLine ? (
              <div className={styles.infoSection}>
                <div className={styles.infoLabel}>Remote</div>
                <div className={styles.infoBlock}>{selectedSourceRemoteLine}</div>
              </div>
            ) : null}

            {selectedSource.status.remote_last_error ? (
              <Typography.Text type="secondary" className={styles.remoteError}>
                {t("knowledge.remoteLastError", {
                  error: selectedSource.status.remote_last_error,
                })}
              </Typography.Text>
            ) : null}

            <Divider style={{ margin: "4px 0" }} />

            <div className={styles.infoSection}>
              <div className={styles.infoLabel}>{t("knowledge.documentContent")}</div>
              {sourceContentLoading ? (
                <div className={styles.contentLoadingWrap}>
                  <Spin size="small" />
                </div>
              ) : !sourceContent?.indexed ? (
                <Typography.Text type="secondary" className={styles.contentEmpty}>
                  {selectedSource.status.indexed
                    ? t("knowledge.documentContentEmpty")
                    : t("knowledge.documentContentNotIndexed")}
                </Typography.Text>
              ) : (
                <div className={styles.documentList}>
                  {sourceContent.documents.map((doc, idx) => (
                    <div key={doc.path || idx} className={styles.documentItem}>
                      {sourceContent.documents.length > 1 && (
                        <Typography.Text  className={styles.documentTitle}>
                          {doc.title || doc.path}
                        </Typography.Text>
                      )}
                      <div className={styles.documentMarkdown}>
                        <MarkdownCopy
                          content={doc.text}
                          showMarkdown
                          showControls
                          markdownViewerProps={{
                            className: styles.documentMarkdownViewer,
                            style: {
                              backgroundColor: "transparent",
                              border: "none",
                              maxHeight: 360,
                              padding: 12,
                            },
                          }}
                        />
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </Space>
        ) : null}
      </Drawer>
      <input
        type="file"
        ref={singleFileInputRef}
        className={styles.hiddenInput}
        onChange={handleFilePicked}
      />
      <input
        type="file"
        ref={directoryInputRef}
        className={styles.hiddenInput}
        multiple
        onChange={handleDirectoryPicked}
      />
    </div>
  );
}

export default KnowledgePage;