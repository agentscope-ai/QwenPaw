import { useEffect, useMemo, useRef, useState } from "react";
import {
  Alert,
  Button,
  Card,
  Checkbox,
  Drawer,
  Dropdown,
  Form,
  Input,
  InputNumber,
  Modal,
  Select,
  Slider,
  Switch,
  Table,
  Tabs,
  Tooltip,
  Upload,
} from "@agentscope-ai/design";
import { MoreOutlined } from "@ant-design/icons";
import { Steps } from "antd";
import type { MenuProps, UploadFile } from "antd";
import { useTranslation } from "react-i18next";
import api from "../../../api";
import type {
  KnowledgeBaseSummary,
  KnowledgeChunk,
  KnowledgeChunkConfig,
  KnowledgeDocumentSummary,
  KnowledgeIndexingTechnique,
  KnowledgeRetrievalConfig,
  KnowledgeSearchMethod,
  KnowledgeUploadFormValues,
  KnowledgeUploadCapabilities,
  KnowledgeVectorConfig,
} from "../../../api/types";
import { PageHeader } from "@/components/PageHeader";
import { EmbeddingModelConfigFields } from "./components/EmbeddingModelConfigFields";
import { KnowledgeChunkContent } from "./components/KnowledgeChunkContent";
import { useAppMessage } from "../../../hooks/useAppMessage";
import styles from "./index.module.less";

function formatDate(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }
  return date.toLocaleString();
}

function getDocumentStatusLabel(
  status: KnowledgeDocumentSummary["status"],
  t: (key: string) => string,
): string {
  switch (status) {
    case "processing":
      return t("knowledge.documentStatusProcessing");
    case "failed":
      return t("knowledge.documentStatusFailed");
    case "disabled":
      return t("knowledge.documentStatusDisabled");
    default:
      return t("knowledge.documentStatusEnabled");
  }
}

function formatSliderValue(value: number, digits = 2): string {
  if (Number.isInteger(value)) {
    return String(value);
  }
  return value.toFixed(digits);
}

const DEFAULT_VECTOR_CHUNK_CONFIG = {
  mode: "general" as const,
  granularity: "balanced" as const,
  separator: "\\n\\n",
  normalize_whitespace: false,
  llm_grouping: false,
  chunk_size: 1024,
  chunk_overlap: 50,
  parent_separator: "\\n\\n",
  parent_normalize_whitespace: false,
  parent_chunk_size: 1600,
  parent_chunk_overlap: 160,
  child_separator: "\\n",
  child_normalize_whitespace: false,
  child_chunk_size: 400,
  child_chunk_overlap: 40,
};

const DEFAULT_VECTOR_RETRIEVAL_CONFIG = {
  indexing_technique: "high_quality" as const,
  search_method: "hybrid" as const,
  top_k: 3,
  score_threshold_enabled: false,
  score_threshold: 0.35,
  reranking_enable: false,
  weights: {
    vector_weight: 0.7,
    keyword_weight: 0.3,
  },
};

const DEFAULT_VECTOR_FORM_VALUES = {
  default_chunk_config: DEFAULT_VECTOR_CHUNK_CONFIG,
  retrieval_config: DEFAULT_VECTOR_RETRIEVAL_CONFIG,
};

function getDocumentStatusClassName(status: KnowledgeDocumentSummary["status"]): string {
  switch (status) {
    case "processing":
      return styles.statusProcessing;
    case "failed":
      return styles.statusFailed;
    case "disabled":
      return styles.statusDisabled;
    default:
      return styles.statusEnabled;
  }
}

export default function KnowledgePage() {
  const { t } = useTranslation();
  const { message } = useAppMessage();
  const defaultChunkModalWidth =
    typeof window === "undefined" ? 960 : Math.floor(window.innerWidth * 0.8);
  const [activeTab, setActiveTab] = useState("list");
  const [loading, setLoading] = useState(false);
  const [knowledgeItems, setKnowledgeItems] = useState<KnowledgeBaseSummary[]>([]);
  const [knowledgeSearch, setKnowledgeSearch] = useState("");
  const [detailLoading, setDetailLoading] = useState(false);
  const [activeKnowledge, setActiveKnowledge] = useState<KnowledgeBaseSummary | null>(null);
  const [documents, setDocuments] = useState<KnowledgeDocumentSummary[]>([]);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [documentSearch, setDocumentSearch] = useState("");
  const [createOpen, setCreateOpen] = useState(false);
  const [renameKnowledgeOpen, setRenameKnowledgeOpen] = useState(false);
  const [renameDocumentOpen, setRenameDocumentOpen] = useState(false);
  const [uploadOpen, setUploadOpen] = useState(false);
  const [uploadStep, setUploadStep] = useState(0);
  const [uploadConfigExpanded, setUploadConfigExpanded] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [selectedFiles, setSelectedFiles] = useState<UploadFile[]>([]);
  const [uploadCapabilities, setUploadCapabilities] =
    useState<KnowledgeUploadCapabilities | null>(null);
  const [chunksOpen, setChunksOpen] = useState(false);
  const [chunksLoading, setChunksLoading] = useState(false);
  const [selectedDocument, setSelectedDocument] = useState<KnowledgeDocumentSummary | null>(null);
  const [chunks, setChunks] = useState<KnowledgeChunk[]>([]);
  const [chunkSearch, setChunkSearch] = useState("");
  const [chunkPage, setChunkPage] = useState(1);
  const [chunkPageSize, setChunkPageSize] = useState(20);
  const [chunkTotal, setChunkTotal] = useState(0);
  const [chunkModalWidth, setChunkModalWidth] = useState(defaultChunkModalWidth);
  const [editChunkOpen, setEditChunkOpen] = useState(false);
  const [editingChunk, setEditingChunk] = useState<KnowledgeChunk | null>(null);
  const [renameChunkOpen, setRenameChunkOpen] = useState(false);
  const [renamingChunk, setRenamingChunk] = useState<KnowledgeChunk | null>(null);
  const [vectorSaving, setVectorSaving] = useState(false);
  const [savedUploadDefaults, setSavedUploadDefaults] = useState<{
    default_chunk_config: KnowledgeChunkConfig;
    retrieval_config: KnowledgeRetrievalConfig;
  }>(DEFAULT_VECTOR_FORM_VALUES);

  const [createForm] = Form.useForm<{ name: string; id?: string }>();
  const [renameKnowledgeForm] = Form.useForm<{ name: string }>();
  const [renameDocumentForm] = Form.useForm<{ name: string }>();
  const [chunkForm] = Form.useForm<{ name: string; content: string }>();
  const [renameChunkForm] = Form.useForm<{ name: string }>();
  const [uploadForm] = Form.useForm<KnowledgeUploadFormValues>();
  const [vectorForm] = Form.useForm<KnowledgeVectorConfig>();
  const chunkResizeStartRef = useRef<{ startX: number; startWidth: number } | null>(null);

  const embeddingBaseUrl = Form.useWatch(
    ["embedding_model_config", "base_url"],
    vectorForm,
  );
  const embeddingModelName = Form.useWatch(
    ["embedding_model_config", "model_name"],
    vectorForm,
  );
  const indexingTechnique =
    Form.useWatch(["retrieval_config", "indexing_technique"], vectorForm) || "high_quality";
  const searchMethod =
    Form.useWatch(["retrieval_config", "search_method"], vectorForm) || "hybrid";
  const scoreThresholdEnabled =
    Form.useWatch(["retrieval_config", "score_threshold_enabled"], vectorForm) || false;
  const chunkMode =
    Form.useWatch(["default_chunk_config", "mode"], vectorForm) || "general";
  const topK = Form.useWatch(["retrieval_config", "top_k"], vectorForm) || 3;
  const scoreThreshold = Form.useWatch(["retrieval_config", "score_threshold"], vectorForm) ?? 0;
  const vectorWeight =
    Form.useWatch(["retrieval_config", "weights", "vector_weight"], vectorForm) || 0.7;
  const keywordWeight =
    Form.useWatch(["retrieval_config", "weights", "keyword_weight"], vectorForm) || 0.3;
  const uploadChunkMode = Form.useWatch("mode", uploadForm) || "general";
  const uploadIndexingTechnique =
    Form.useWatch(["retrieval_config", "indexing_technique"], uploadForm) || "high_quality";
  const uploadSearchMethod =
    Form.useWatch(["retrieval_config", "search_method"], uploadForm) || "hybrid";
  const uploadTopK = Form.useWatch(["retrieval_config", "top_k"], uploadForm) || 3;
  const uploadScoreThresholdEnabled =
    Form.useWatch(["retrieval_config", "score_threshold_enabled"], uploadForm) || false;
  const uploadScoreThreshold =
    Form.useWatch(["retrieval_config", "score_threshold"], uploadForm) ?? 0;
  const uploadVectorWeight =
    Form.useWatch(["retrieval_config", "weights", "vector_weight"], uploadForm) || 0.7;
  const uploadKeywordWeight =
    Form.useWatch(["retrieval_config", "weights", "keyword_weight"], uploadForm) || 0.3;
  const embeddingEnabled = !!(
    embeddingBaseUrl?.trim() && embeddingModelName?.trim()
  );
  const highQualityMode = indexingTechnique === "high_quality";
  const vectorConfigReady = !highQualityMode || embeddingEnabled;

  const setIndexingTechnique = (value: KnowledgeIndexingTechnique) => {
    const current = vectorForm.getFieldValue("retrieval_config") || {};
    const currentChunkConfig = vectorForm.getFieldValue("default_chunk_config") || {};
    vectorForm.setFieldsValue({
      retrieval_config: {
        ...current,
        indexing_technique: value,
        search_method:
          value === "economy"
            ? "keyword"
            : current.search_method === "keyword"
              ? "hybrid"
              : current.search_method || "hybrid",
      },
      default_chunk_config: {
        ...DEFAULT_VECTOR_CHUNK_CONFIG,
        ...currentChunkConfig,
        mode: value === "economy" ? "general" : currentChunkConfig.mode || "general",
      },
    });
  };

  const setSearchMethod = (value: KnowledgeSearchMethod) => {
    const current = vectorForm.getFieldValue("retrieval_config") || {};
    vectorForm.setFieldsValue({
      retrieval_config: {
        ...current,
        search_method: value,
      },
    });
  };

  const setChunkMode = (value: "general" | "parent_child") => {
    const current = vectorForm.getFieldValue("default_chunk_config") || {};
    vectorForm.setFieldsValue({
      default_chunk_config: {
        ...DEFAULT_VECTOR_CHUNK_CONFIG,
        ...current,
        mode: value,
      },
    });
  };

  const setWeightBalance = (nextVectorWeight: number) => {
    const safeVectorWeight = Number(Math.min(1, Math.max(0, nextVectorWeight)).toFixed(2));
    const current = vectorForm.getFieldValue("retrieval_config") || {};
    vectorForm.setFieldsValue({
      retrieval_config: {
        ...current,
        weights: {
          ...(current.weights || {}),
          vector_weight: safeVectorWeight,
          keyword_weight: Number((1 - safeVectorWeight).toFixed(2)),
        },
      },
    });
  };

  const replaceKnowledgeItem = (nextItem: KnowledgeBaseSummary) => {
    setKnowledgeItems((current) =>
      current.map((item) => (item.id === nextItem.id ? nextItem : item)),
    );
    setActiveKnowledge((current) =>
      current?.id === nextItem.id ? nextItem : current,
    );
  };

  const appendKnowledgeItem = (nextItem: KnowledgeBaseSummary) => {
    setKnowledgeItems((current) => [...current, nextItem]);
  };

  const replaceDocumentItem = (nextDocument: KnowledgeDocumentSummary) => {
    setDocuments((current) =>
      current.map((item) =>
        item.id === nextDocument.id ? nextDocument : item,
      ),
    );
    setSelectedDocument((current) =>
      current?.id === nextDocument.id ? nextDocument : current,
    );
  };

  const appendDocumentItem = (nextDocument: KnowledgeDocumentSummary) => {
    setDocuments((current) => [...current, nextDocument]);
  };

  const removeDocumentItem = (documentId: string) => {
    setDocuments((current) => current.filter((item) => item.id !== documentId));
    setSelectedDocument((current) =>
      current?.id === documentId ? null : current,
    );
  };

  const replaceChunkItem = (nextChunk: KnowledgeChunk) => {
    setChunks((current) =>
      current.map((item) => (item.id === nextChunk.id ? nextChunk : item)),
    );
  };

  const removeChunkItem = (chunkId: string) => {
    setChunks((current) => current.filter((item) => item.id !== chunkId));
  };

  const fetchKnowledgeBases = async () => {
    setLoading(true);
    try {
      const response = await api.listKnowledgeBases();
      setKnowledgeItems(response.items);
    } catch (error) {
      message.error((error as Error).message || t("knowledge.loadFailed"));
    } finally {
      setLoading(false);
    }
  };

  const fetchKnowledgeDetail = async (
    knowledgeId: string,
    options?: { openDrawer?: boolean; syncSummary?: boolean },
  ) => {
    setDetailLoading(true);
    try {
      const response = await api.getKnowledgeBase(knowledgeId);
      setActiveKnowledge(response.item);
      setDocuments(response.documents);
      setSelectedDocument((current) =>
        current
          ? response.documents.find((item) => item.id === current.id) ?? null
          : current,
      );
      if (options?.syncSummary !== false) {
        replaceKnowledgeItem(response.item);
      }
      if (options?.openDrawer !== false) {
        setDrawerOpen(true);
      }
    } catch (error) {
      message.error((error as Error).message || t("knowledge.detailLoadFailed"));
    } finally {
      setDetailLoading(false);
    }
  };

  const fetchUploadCapabilities = async () => {
    try {
      const response = await api.getKnowledgeUploadCapabilities();
      setUploadCapabilities(response);
    } catch (error) {
      message.error((error as Error).message || t("knowledge.uploadCapabilityFailed"));
    }
  };

  const fetchVectorConfig = async () => {
    try {
      const config = await api.getKnowledgeVectorConfig();
      const normalizedConfig = {
        ...DEFAULT_VECTOR_FORM_VALUES,
        ...config,
        default_chunk_config: {
          ...DEFAULT_VECTOR_CHUNK_CONFIG,
          ...(config.default_chunk_config || {}),
        },
        retrieval_config: {
          ...DEFAULT_VECTOR_RETRIEVAL_CONFIG,
          ...(config.retrieval_config || {}),
          weights: {
            ...DEFAULT_VECTOR_RETRIEVAL_CONFIG.weights,
            ...(config.retrieval_config?.weights || {}),
          },
        },
      };
      setSavedUploadDefaults({
        default_chunk_config: normalizedConfig.default_chunk_config,
        retrieval_config: normalizedConfig.retrieval_config,
      });
      vectorForm.setFieldsValue(normalizedConfig);
    } catch (error) {
      message.error((error as Error).message || t("knowledge.vectorLoadFailed"));
    }
  };

  useEffect(() => {
    fetchKnowledgeBases();
    fetchUploadCapabilities();
    fetchVectorConfig();
  }, []);

  useEffect(() => {
    const hasProcessingKnowledge = knowledgeItems.some(
      (item) => item.processing_document_count > 0,
    );
    const hasProcessingDocument = documents.some(
      (item) => item.status === "processing",
    );
    if (!hasProcessingKnowledge && !hasProcessingDocument) {
      return;
    }

    const timer = window.setInterval(() => {
      if (drawerOpen && activeKnowledge && hasProcessingDocument) {
        fetchKnowledgeDetail(activeKnowledge.id, {
          openDrawer: false,
          syncSummary: true,
        });
        return;
      }
      if (hasProcessingKnowledge) {
        fetchKnowledgeBases();
      }
    }, 5000);

    return () => window.clearInterval(timer);
  }, [knowledgeItems, documents, drawerOpen, activeKnowledge]);

  useEffect(() => {
    if (!uploadOpen) {
      return;
    }
    setUploadConfigExpanded(false);
    uploadForm.setFieldsValue({
      ...DEFAULT_VECTOR_CHUNK_CONFIG,
      ...(uploadCapabilities?.default_chunk_config || {}),
      ...(savedUploadDefaults.default_chunk_config || {}),
      retrieval_config: {
        ...DEFAULT_VECTOR_RETRIEVAL_CONFIG,
        ...(uploadCapabilities?.retrieval_config || {}),
        ...(savedUploadDefaults.retrieval_config || {}),
        weights: {
          ...DEFAULT_VECTOR_RETRIEVAL_CONFIG.weights,
          ...(uploadCapabilities?.retrieval_config?.weights || {}),
          ...(savedUploadDefaults.retrieval_config?.weights || {}),
        },
      },
    });
  }, [uploadOpen, uploadCapabilities, uploadForm, savedUploadDefaults]);

  const filteredKnowledgeItems = useMemo(() => {
    const keyword = knowledgeSearch.trim().toLowerCase();
    if (!keyword) return knowledgeItems;
    return knowledgeItems.filter((item) =>
      [item.name, item.slug, item.id].some((value) => value.toLowerCase().includes(keyword)),
    );
  }, [knowledgeItems, knowledgeSearch]);

  const filteredDocuments = useMemo(() => {
    const keyword = documentSearch.trim().toLowerCase();
    if (!keyword) return documents;
    return documents.filter((item) =>
      [item.name, item.source_filename].some((value) => value.toLowerCase().includes(keyword)),
    );
  }, [documents, documentSearch]);

  const loadChunkPage = async (
    document: KnowledgeDocumentSummary,
    options?: { page?: number; pageSize?: number; search?: string },
  ) => {
    if (!activeKnowledge) return;
    setChunksLoading(true);
    try {
      const response = await api.listKnowledgeChunks(activeKnowledge.id, document.id, {
        page: options?.page ?? chunkPage,
        page_size: options?.pageSize ?? chunkPageSize,
        search: options?.search ?? chunkSearch,
      });
      setChunks(response.items);
      setChunkTotal(response.total);
      setChunkPage(response.page);
      setChunkPageSize(response.page_size);
    } catch (error) {
      message.error((error as Error).message || t("knowledge.chunkLoadFailed"));
    } finally {
      setChunksLoading(false);
    }
  };

  const handleCreateKnowledge = async () => {
    const values = await createForm.validateFields();
    try {
      const response = await api.createKnowledgeBase({
        name: values.name.trim(),
        id: values.id?.trim() || undefined,
      });
      message.success(t("knowledge.createSuccess"));
      setCreateOpen(false);
      createForm.resetFields();
      appendKnowledgeItem(response.item);
    } catch (error) {
      message.error((error as Error).message || t("knowledge.createFailed"));
    }
  };

  const handleRenameKnowledge = async () => {
    if (!activeKnowledge) return;
    const values = await renameKnowledgeForm.validateFields();
    try {
      const response = await api.updateKnowledgeBase(activeKnowledge.id, { name: values.name.trim() });
      message.success(t("knowledge.renameSuccess"));
      setRenameKnowledgeOpen(false);
      replaceKnowledgeItem(response.item);
    } catch (error) {
      message.error((error as Error).message || t("knowledge.renameFailed"));
    }
  };

  const handleToggleKnowledge = async (item: KnowledgeBaseSummary, enabled: boolean) => {
    try {
      const response = await api.updateKnowledgeBase(item.id, { enabled });
      message.success(enabled ? t("knowledge.enableSuccess") : t("knowledge.disableSuccess"));
      replaceKnowledgeItem(response.item);
    } catch (error) {
      message.error((error as Error).message || t("knowledge.updateFailed"));
    }
  };

  const handleDeleteKnowledge = (item: KnowledgeBaseSummary) => {
    Modal.confirm({
      title: t("knowledge.deleteTitle", { name: item.name }),
      content: t("knowledge.deleteConfirm"),
      okText: t("common.delete"),
      okType: "danger",
      cancelText: t("common.cancel"),
      onOk: async () => {
        try {
          await api.deleteKnowledgeBase(item.id);
          message.success(t("knowledge.deleteSuccess"));
          if (activeKnowledge?.id === item.id) {
            setDrawerOpen(false);
            setActiveKnowledge(null);
            setDocuments([]);
          }
          setKnowledgeItems((current) => current.filter((currentItem) => currentItem.id !== item.id));
        } catch (error) {
          message.error((error as Error).message || t("knowledge.deleteFailed"));
        }
      },
    });
  };

  const openUploadModal = () => {
    if (!activeKnowledge) return;
    setUploadStep(0);
    setUploadConfigExpanded(false);
    setSelectedFiles([]);
    setUploadOpen(true);
  };

  const handleUploadDocument = async () => {
    if (!activeKnowledge || selectedFiles.length === 0) {
      message.warning(t("knowledge.uploadFileRequired"));
      return;
    }
    if (!uploadCapabilities?.can_upload) {
      message.warning(t("knowledge.vectorModelRequired"));
      return;
    }
    const uploadValues = await uploadForm.validateFields();
    const chunkConfig: KnowledgeChunkConfig = {
      mode: uploadValues.mode,
      granularity: uploadValues.granularity,
      separator: uploadValues.separator,
      normalize_whitespace: uploadValues.normalize_whitespace,
      llm_grouping: uploadValues.llm_grouping,
      chunk_size: uploadValues.chunk_size,
      chunk_overlap: uploadValues.chunk_overlap,
      parent_separator: uploadValues.parent_separator,
      parent_normalize_whitespace: uploadValues.parent_normalize_whitespace,
      parent_chunk_size: uploadValues.parent_chunk_size,
      parent_chunk_overlap: uploadValues.parent_chunk_overlap,
      child_separator: uploadValues.child_separator,
      child_normalize_whitespace: uploadValues.child_normalize_whitespace,
      child_chunk_size: uploadValues.child_chunk_size,
      child_chunk_overlap: uploadValues.child_chunk_overlap,
    };
    const retrievalConfig: KnowledgeRetrievalConfig = uploadValues.retrieval_config;
    setUploading(true);
    try {
      let successCount = 0;
      const failedFiles: string[] = [];
      const filesToUpload = selectedFiles
        .map((item) => item.originFileObj)
        .filter((file): file is NonNullable<typeof file> => Boolean(file));
      for (const file of filesToUpload) {
        try {
          const response = await api.uploadKnowledgeDocument(
            activeKnowledge.id,
            file,
            chunkConfig,
            retrievalConfig,
          );
          appendDocumentItem(response.document);
          successCount += 1;
        } catch (error) {
          failedFiles.push(file.name);
        }
      }
      if (successCount > 0) {
        message.success(
          successCount === 1
            ? t("knowledge.uploadQueued")
            : t("knowledge.uploadQueuedMultiple", { count: successCount }),
        );
      }
      if (failedFiles.length > 0) {
        message.warning(
          t("knowledge.uploadFailedMultiple", {
            count: failedFiles.length,
            files: failedFiles.join(", "),
          }),
        );
      }
      if (failedFiles.length === 0) {
        setUploadOpen(false);
        setSelectedFiles([]);
        setUploadStep(0);
      }
    } catch (error) {
      message.error((error as Error).message || t("knowledge.uploadFailed"));
    } finally {
      setUploading(false);
    }
  };

  const handleRenameDocument = async () => {
    if (!activeKnowledge || !selectedDocument) return;
    const values = await renameDocumentForm.validateFields();
    try {
      const response = await api.updateKnowledgeDocument(activeKnowledge.id, selectedDocument.id, {
        name: values.name.trim(),
      });
      message.success(t("knowledge.documentRenameSuccess"));
      setRenameDocumentOpen(false);
      replaceDocumentItem(response.document);
    } catch (error) {
      message.error((error as Error).message || t("knowledge.documentRenameFailed"));
    }
  };

  const handleToggleDocument = async (
    document: KnowledgeDocumentSummary,
    enabled: boolean,
  ) => {
    if (!activeKnowledge || document.status === "processing" || document.status === "failed") return;
    try {
      const response = await api.updateKnowledgeDocument(activeKnowledge.id, document.id, { enabled });
      message.success(
        enabled ? t("knowledge.documentEnableSuccess") : t("knowledge.documentDisableSuccess"),
      );
      replaceDocumentItem(response.document);
    } catch (error) {
      message.error((error as Error).message || t("knowledge.updateFailed"));
    }
  };

  const handleDeleteDocument = (document: KnowledgeDocumentSummary) => {
    if (!activeKnowledge) return;
    Modal.confirm({
      title: t("knowledge.documentDeleteTitle", { name: document.name }),
      content: t("knowledge.documentDeleteConfirm"),
      okText: t("common.delete"),
      okType: "danger",
      cancelText: t("common.cancel"),
      onOk: async () => {
        try {
          await api.deleteKnowledgeDocument(activeKnowledge.id, document.id);
          message.success(t("knowledge.documentDeleteSuccess"));
          removeDocumentItem(document.id);
        } catch (error) {
          message.error((error as Error).message || t("knowledge.documentDeleteFailed"));
        }
      },
    });
  };

  const openChunks = async (document: KnowledgeDocumentSummary) => {
    if (!activeKnowledge || document.status === "processing") return;
    setSelectedDocument(document);
    setChunksOpen(true);
    setChunkSearch("");
    setChunkPage(1);
    await loadChunkPage(document, { page: 1, pageSize: chunkPageSize, search: "" });
  };

  const handleToggleChunk = async (chunk: KnowledgeChunk, enabled: boolean) => {
    if (!activeKnowledge || !selectedDocument) return;
    try {
      const response = await api.updateKnowledgeChunk(activeKnowledge.id, selectedDocument.id, chunk.id, {
        enabled,
      });
      message.success(enabled ? t("knowledge.chunkEnableSuccess") : t("knowledge.chunkDisableSuccess"));
      replaceChunkItem(response.chunk);
    } catch (error) {
      message.error((error as Error).message || t("knowledge.chunkUpdateFailed"));
    }
  };

  const handleSaveChunk = async () => {
    if (!activeKnowledge || !selectedDocument || !editingChunk) return;
    const values = await chunkForm.validateFields();
    try {
      const response = await api.updateKnowledgeChunk(activeKnowledge.id, selectedDocument.id, editingChunk.id, {
        name: values.name.trim(),
        content: values.content,
      });
      message.success(t("knowledge.chunkEditSuccess"));
      setEditChunkOpen(false);
      setEditingChunk(null);
      replaceChunkItem(response.chunk);
    } catch (error) {
      message.error((error as Error).message || t("knowledge.chunkEditFailed"));
    }
  };

  const handleRenameChunk = async () => {
    if (!activeKnowledge || !selectedDocument || !renamingChunk) return;
    const values = await renameChunkForm.validateFields();
    try {
      const response = await api.updateKnowledgeChunk(activeKnowledge.id, selectedDocument.id, renamingChunk.id, {
        name: values.name.trim(),
      });
      message.success(t("knowledge.chunkRenameSuccess"));
      setRenameChunkOpen(false);
      setRenamingChunk(null);
      replaceChunkItem(response.chunk);
    } catch (error) {
      message.error((error as Error).message || t("knowledge.chunkRenameFailed"));
    }
  };

  const handleDeleteChunk = (chunk: KnowledgeChunk) => {
    if (!activeKnowledge || !selectedDocument) return;
    Modal.confirm({
      title: t("knowledge.chunkDeleteTitle", { name: chunk.name }),
      content: t("knowledge.chunkDeleteConfirm"),
      okText: t("common.delete"),
      okType: "danger",
      cancelText: t("common.cancel"),
      onOk: async () => {
        try {
          await api.deleteKnowledgeChunk(activeKnowledge.id, selectedDocument.id, chunk.id);
          message.success(t("knowledge.chunkDeleteSuccess"));
          removeChunkItem(chunk.id);
          setChunkTotal((current) => Math.max(0, current - 1));
        } catch (error) {
          message.error((error as Error).message || t("knowledge.chunkDeleteFailed"));
        }
      },
    });
  };

  const stopChunkResize = () => {
    chunkResizeStartRef.current = null;
    window.removeEventListener("mousemove", handleChunkResize);
    window.removeEventListener("mouseup", stopChunkResize);
  };

  const handleChunkResize = (event: MouseEvent) => {
    const resizeStart = chunkResizeStartRef.current;
    if (!resizeStart) return;
    const nextWidth = resizeStart.startWidth + (event.clientX - resizeStart.startX);
    const viewportWidth = window.innerWidth;
    setChunkModalWidth(Math.min(Math.max(nextWidth, 720), viewportWidth - 40));
  };

  const startChunkResize = (event: React.MouseEvent<HTMLDivElement>) => {
    event.preventDefault();
    event.stopPropagation();
    chunkResizeStartRef.current = {
      startX: event.clientX,
      startWidth: chunkModalWidth,
    };
    window.addEventListener("mousemove", handleChunkResize);
    window.addEventListener("mouseup", stopChunkResize);
  };

  useEffect(() => {
    return () => {
      stopChunkResize();
    };
  }, []);

  const handleSaveVectorConfig = async () => {
    const values = await vectorForm.validateFields();
    setVectorSaving(true);
    try {
      await api.updateKnowledgeVectorConfig(values);
      message.success(t("knowledge.vectorSaveSuccess"));
      await fetchUploadCapabilities();
      await fetchVectorConfig();
    } catch (error) {
      message.error((error as Error).message || t("knowledge.vectorSaveFailed"));
    } finally {
      setVectorSaving(false);
    }
  };

  const knowledgeColumns = [
    {
      title: "#",
      dataIndex: "index",
      key: "index",
      width: 72,
    },
    {
      title: t("knowledge.name"),
      dataIndex: "name",
      key: "name",
      ellipsis: true,
      minWidth: 200,
      render: (value: string) => (
        <div style={{ minWidth: 200 }}>{value}</div>
      ),
    },
    {
      title: t("knowledge.id"),
      dataIndex: "id",
      key: "id",
      width: 260,
      render: (value: string) => <span className={styles.monoText}>{value}</span>,
    },
    {
      title: t("knowledge.documentCount"),
      key: "documentCount",
      width: 120,
      render: (_: unknown, item: KnowledgeBaseSummary) => (
        <span>
          {item.enabled_document_count}/{item.document_count}
        </span>
      ),
    },
    {
      title: t("knowledge.updatedAt"),
      dataIndex: "updated_at",
      key: "updated_at",
      width: 180,
      ellipsis: true,
      render: (value: string) => formatDate(value),
    },
    {
      title: t("knowledge.status"),
      key: "status",
      width: 100,
      render: (_: unknown, item: KnowledgeBaseSummary) => (
        <div onClick={(event) => event.stopPropagation()}>
          <Switch
            size="small"
            checked={item.enabled}
            onChange={(checked) => handleToggleKnowledge(item, checked)}
          />
        </div>
      ),
    },
    {
      title: t("common.actions"),
      key: "actions",
      width: 140,
      render: (_: unknown, item: KnowledgeBaseSummary) => {
        const menuItems: MenuProps["items"] = [
          {
            key: "detail",
            label: t("knowledge.viewDetail"),
            onClick: () => fetchKnowledgeDetail(item.id),
          },
          {
            key: "rename",
            label: t("knowledge.rename"),
            onClick: () => {
              setActiveKnowledge(item);
              renameKnowledgeForm.setFieldsValue({ name: item.name });
              setRenameKnowledgeOpen(true);
            },
          },
          {
            key: "delete",
            label: t("common.delete"),
            danger: true,
            onClick: () => handleDeleteKnowledge(item),
          },
        ];
        return (
          <div onClick={(event) => event.stopPropagation()}>
            <Dropdown menu={{ items: menuItems }} placement="bottomRight">
              <Button icon={<MoreOutlined />} />
            </Dropdown>
          </div>
        );
      },
    },
  ];

  const documentColumns = [
    {
      title: "#",
      dataIndex: "index",
      key: "index",
      width: 56,
    },
    {
      title: t("knowledge.name"),
      dataIndex: "name",
      key: "name",
    },
    {
      title: t("knowledge.status"),
      dataIndex: "status",
      key: "status",
      width: 110,
      render: (value: KnowledgeDocumentSummary["status"], item: KnowledgeDocumentSummary) => {
        const statusNode = (
          <span className={`${styles.statusTag} ${getDocumentStatusClassName(value)}`}>
            {getDocumentStatusLabel(value, t)}
          </span>
        );

        if (value !== "failed" || !item.error_message) {
          return statusNode;
        }

        return <Tooltip title={item.error_message}>{statusNode}</Tooltip>;
      },
    },
    {
      title: t("knowledge.chunkCount"),
      key: "chunk_count",
      width: 88,
      render: (_: unknown, item: KnowledgeDocumentSummary) => (
        <span>
          {item.enabled_chunk_count}/{item.chunk_count}
        </span>
      ),
    },
    {
      title: t("knowledge.updatedAt"),
      dataIndex: "updated_at",
      key: "updated_at",
      width: 180,
      ellipsis: true,
      render: (value: string) => formatDate(value),
    },
    {
      title: t("common.actions"),
      key: "actions",
      width: 100,
      align: "right" as const,
      render: (_: unknown, item: KnowledgeDocumentSummary) => {
        const menuItems: MenuProps["items"] = [
          {
            key: "chunks",
            label: t("knowledge.viewChunks"),
            disabled: item.status === "processing",
            onClick: () => openChunks(item),
          },
          {
            key: "rename",
            label: t("knowledge.rename"),
            onClick: () => {
              setSelectedDocument(item);
              renameDocumentForm.setFieldsValue({ name: item.name });
              setRenameDocumentOpen(true);
            },
          },
          {
            key: "delete",
            label: t("common.delete"),
            danger: true,
            onClick: () => handleDeleteDocument(item),
          },
        ];
        return (
          <div className={styles.inlineActions} onClick={(event) => event.stopPropagation()}>
            <Switch
              size="small"
              checked={item.enabled}
              disabled={item.status === "processing" || item.status === "failed"}
              onChange={(checked) => handleToggleDocument(item, checked)}
            />
            <Dropdown menu={{ items: menuItems }} placement="bottomRight">
              <Button size="small" icon={<MoreOutlined />} />
            </Dropdown>
          </div>
        );
      },
    },
  ];

  const chunkColumns = [
    {
      title: t("knowledge.name"),
      dataIndex: "name",
      key: "name",
      width: 180,
    },
    {
      title: t("knowledge.content"),
      dataIndex: "content",
      key: "content",
      render: (_: string, item: KnowledgeChunk) => (
        <KnowledgeChunkContent content={item.content} assets={item.assets} />
      ),
    },
    {
      title: t("knowledge.charCount"),
      dataIndex: "char_count",
      key: "char_count",
      width: 100,
    },
    {
      title: t("knowledge.status"),
      key: "status",
      width: 100,
      render: (_: unknown, item: KnowledgeChunk) => (
        <Switch
          size="small"
          checked={item.enabled}
          onChange={(checked) => handleToggleChunk(item, checked)}
        />
      ),
    },
    {
      title: t("common.actions"),
      key: "actions",
      width: 100,
      render: (_: unknown, item: KnowledgeChunk) => {
        const menuItems: MenuProps["items"] = [
          {
            key: "edit",
            label: t("common.edit"),
            onClick: () => {
              setEditingChunk(item);
              chunkForm.setFieldsValue({ name: item.name, content: item.content });
              setEditChunkOpen(true);
            },
          },
          {
            key: "rename",
            label: t("knowledge.rename"),
            onClick: () => {
              setRenamingChunk(item);
              renameChunkForm.setFieldsValue({ name: item.name });
              setRenameChunkOpen(true);
            },
          },
          {
            key: "delete",
            label: t("common.delete"),
            danger: true,
            onClick: () => handleDeleteChunk(item),
          },
        ];
        return (
          <div onClick={(event) => event.stopPropagation()}>
            <Dropdown menu={{ items: menuItems }} placement="bottomRight">
              <Button size="small" icon={<MoreOutlined />} />
            </Dropdown>
          </div>
        );
      },
    },
  ];

  const uploadFooter =
    uploadStep === 0
      ? [
          <Button key="cancel" onClick={() => setUploadOpen(false)}>
            {t("common.cancel")}
          </Button>,
          <Button
            key="next"
            type="primary"
            disabled={selectedFiles.length === 0 || !uploadCapabilities?.can_upload}
            onClick={() => setUploadStep(1)}
          >
            {t("knowledge.nextStep")}
          </Button>,
        ]
      : [
          <Button key="back" onClick={() => setUploadStep(0)}>
            {t("knowledge.prevStep")}
          </Button>,
          <Button key="cancel" onClick={() => setUploadOpen(false)}>
            {t("common.cancel")}
          </Button>,
          <Button key="submit" type="primary" loading={uploading} onClick={handleUploadDocument}>
            {t("common.upload")}
          </Button>,
        ];

  return (
    <div className={styles.knowledgePage}>
      <PageHeader parent={t("nav.agent")} current={t("knowledge.title")} />

      <div className={styles.content}>
        <Tabs
          className={styles.tabs}
          activeKey={activeTab}
          onChange={setActiveTab}
          items={[
            {
              key: "list",
              label: t("knowledge.listTab"),
              children: (
                <div className={styles.tabPane}>
                  <div className={styles.toolbar}>
                    <Input
                      className={styles.searchInput}
                      allowClear
                      value={knowledgeSearch}
                      placeholder={t("knowledge.searchPlaceholder")}
                      onChange={(event) => setKnowledgeSearch(event.target.value)}
                    />
                    <div className={styles.toolbarActions}>
                      <Button onClick={fetchKnowledgeBases}>{t("common.refresh")}</Button>
                      <Button type="primary" onClick={() => setCreateOpen(true)}>
                        {t("knowledge.create")}
                      </Button>
                    </div>
                  </div>

                  <Card className={styles.tableCard}>
                    <Table
                      rowKey="id"
                      loading={loading}
                      columns={knowledgeColumns}
                      dataSource={filteredKnowledgeItems}
                      tableLayout="auto"
                      scroll={{ x: 980 }}
                      pagination={false}
                      onRow={(record) => ({
                        onClick: () => fetchKnowledgeDetail(record.id),
                      })}
                    />
                  </Card>
                </div>
              ),
            },
            {
              key: "vector",
              label: t("knowledge.settingsTab"),
              children: (
                <div className={styles.tabPane}>
                  <div className={styles.vectorPane}>
                    <Form form={vectorForm} layout="vertical" initialValues={DEFAULT_VECTOR_FORM_VALUES}>
                      <Form.Item hidden name={["retrieval_config", "indexing_technique"]}>
                        <Input />
                      </Form.Item>
                      <Form.Item hidden name={["retrieval_config", "search_method"]}>
                        <Input />
                      </Form.Item>
                      <Form.Item hidden name={["default_chunk_config", "mode"]}>
                        <Input />
                      </Form.Item>

                      <Alert
                        showIcon
                        type={vectorConfigReady ? "success" : "warning"}
                        message={
                          vectorConfigReady
                            ? highQualityMode
                              ? t("knowledge.highQualityReady")
                              : t("knowledge.economyReady")
                            : t("knowledge.embeddingRequiredForHighQuality")
                        }
                        style={{ marginBottom: 16 }}
                      />

                      <div className={styles.configSection}>
                        <div className={styles.configSectionTitle}>{t("knowledge.indexingSection")}</div>
                        <div className={styles.optionGrid}>
                          <button
                            type="button"
                            className={`${styles.optionCard} ${indexingTechnique === "high_quality" ? styles.optionCardActive : ""}`}
                            onClick={() => setIndexingTechnique("high_quality")}
                          >
                            <div className={styles.optionTitle}>{t("knowledge.highQuality")}</div>
                            <div className={styles.optionDescription}>{t("knowledge.highQualityDesc")}</div>
                          </button>
                          <button
                            type="button"
                            className={`${styles.optionCard} ${indexingTechnique === "economy" ? styles.optionCardActive : ""}`}
                            onClick={() => setIndexingTechnique("economy")}
                          >
                            <div className={styles.optionTitle}>{t("knowledge.economy")}</div>
                            <div className={styles.optionDescription}>{t("knowledge.economyDesc")}</div>
                          </button>
                        </div>
                      </div>

                      <div className={styles.configSection}>
                        <div className={styles.configSectionTitle}>{t("knowledge.chunkSection")}</div>
                        <div className={styles.optionGrid}>
                          <button
                            type="button"
                            className={`${styles.optionCard} ${chunkMode === "general" ? styles.optionCardActive : ""}`}
                            onClick={() => setChunkMode("general")}
                          >
                            <div className={styles.optionTitle}>{t("knowledge.chunkModeGeneral")}</div>
                            <div className={styles.optionDescription}>{t("knowledge.chunkModeGeneralDesc")}</div>
                          </button>
                          <button
                            type="button"
                            disabled={!highQualityMode}
                            className={`${styles.optionCard} ${chunkMode === "parent_child" ? styles.optionCardActive : ""} ${!highQualityMode ? styles.optionCardDisabled : ""}`}
                            onClick={() => {
                              if (!highQualityMode) {
                                return;
                              }
                              setChunkMode("parent_child");
                            }}
                          >
                            <div className={styles.optionTitle}>{t("knowledge.chunkModeParentChild")}</div>
                            <div className={styles.optionDescription}>
                              {highQualityMode
                                ? t("knowledge.chunkModeParentChildDesc")
                                : t("knowledge.chunkModeParentChildHighQualityOnly")}
                            </div>
                          </button>
                        </div>

                        {chunkMode === "general" ? (
                          <div className={styles.inlineFieldGrid}>
                            <Form.Item label={t("knowledge.chunkSeparator")} name={["default_chunk_config", "separator"]}>
                              <Input placeholder={t("knowledge.chunkSeparatorPlaceholder")} />
                            </Form.Item>
                            <Form.Item label={t("knowledge.chunkGranularity")} name={["default_chunk_config", "granularity"]}>
                              <Select
                                options={[
                                  { label: t("knowledge.chunkGranularityBalanced"), value: "balanced" },
                                  { label: t("knowledge.chunkGranularityParagraph"), value: "paragraph" },
                                  { label: t("knowledge.chunkGranularitySentence"), value: "sentence" },
                                ]}
                              />
                            </Form.Item>
                            <Form.Item label={t("knowledge.chunkSize")} name={["default_chunk_config", "chunk_size"]}>
                              <InputNumber min={100} step={100} style={{ width: "100%" }} />
                            </Form.Item>
                            <Form.Item label={t("knowledge.chunkOverlap")} name={["default_chunk_config", "chunk_overlap"]}>
                              <InputNumber min={0} step={10} style={{ width: "100%" }} />
                            </Form.Item>
                            <Form.Item
                              label={t("knowledge.normalizeWhitespace")}
                              tooltip={t("knowledge.normalizeWhitespaceHelp")}
                              name={["default_chunk_config", "normalize_whitespace"]}
                              valuePropName="checked"
                            >
                              <Switch />
                            </Form.Item>
                            <Form.Item
                              label={t("knowledge.llmGrouping")}
                              tooltip={t("knowledge.llmGroupingHelp")}
                              name={["default_chunk_config", "llm_grouping"]}
                              valuePropName="checked"
                            >
                              <Switch />
                            </Form.Item>
                          </div>
                        ) : (
                          <>
                            <div className={styles.subSectionTitle}>{t("knowledge.parentChunkSection")}</div>
                            <div className={styles.inlineFieldGrid}>
                              <Form.Item label={t("knowledge.parentChunkSeparator")} name={["default_chunk_config", "parent_separator"]}>
                                <Input placeholder={t("knowledge.chunkSeparatorPlaceholder")} />
                              </Form.Item>
                              <Form.Item label={t("knowledge.parentChunkSize")} name={["default_chunk_config", "parent_chunk_size"]}>
                                <InputNumber min={100} step={100} style={{ width: "100%" }} />
                              </Form.Item>
                              <Form.Item label={t("knowledge.parentChunkOverlap")} name={["default_chunk_config", "parent_chunk_overlap"]}>
                                <InputNumber min={0} step={10} style={{ width: "100%" }} />
                              </Form.Item>
                              <Form.Item
                                label={t("knowledge.normalizeWhitespace")}
                                tooltip={t("knowledge.normalizeWhitespaceHelp")}
                                name={["default_chunk_config", "parent_normalize_whitespace"]}
                                valuePropName="checked"
                              >
                                <Switch />
                              </Form.Item>
                              <Form.Item
                                label={t("knowledge.llmGrouping")}
                                tooltip={t("knowledge.llmGroupingHelp")}
                                name={["default_chunk_config", "llm_grouping"]}
                                valuePropName="checked"
                              >
                                <Switch />
                              </Form.Item>
                            </div>
                            <div className={styles.subSectionTitle}>{t("knowledge.childChunkSection")}</div>
                            <div className={styles.inlineFieldGrid}>
                              <Form.Item label={t("knowledge.childChunkSeparator")} name={["default_chunk_config", "child_separator"]}>
                                <Input placeholder={t("knowledge.chunkSeparatorPlaceholder")} />
                              </Form.Item>
                              <Form.Item label={t("knowledge.childChunkSize")} name={["default_chunk_config", "child_chunk_size"]}>
                                <InputNumber min={100} step={50} style={{ width: "100%" }} />
                              </Form.Item>
                              <Form.Item label={t("knowledge.childChunkOverlap")} name={["default_chunk_config", "child_chunk_overlap"]}>
                                <InputNumber min={0} step={10} style={{ width: "100%" }} />
                              </Form.Item>
                              <Form.Item
                                label={t("knowledge.normalizeWhitespace")}
                                tooltip={t("knowledge.normalizeWhitespaceHelp")}
                                name={["default_chunk_config", "child_normalize_whitespace"]}
                                valuePropName="checked"
                              >
                                <Switch />
                              </Form.Item>
                            </div>
                          </>
                        )}
                      </div>

                      <div className={styles.configSection}>
                        <div className={styles.configSectionTitle}>{t("knowledge.retrievalSection")}</div>
                        <div className={styles.optionGrid}>
                          {highQualityMode ? (
                            <>
                              <button
                                type="button"
                                className={`${styles.optionCard} ${searchMethod === "semantic" ? styles.optionCardActive : ""}`}
                                onClick={() => setSearchMethod("semantic")}
                              >
                                <div className={styles.optionTitle}>{t("knowledge.semanticSearch")}</div>
                                <div className={styles.optionDescription}>{t("knowledge.semanticSearchDesc")}</div>
                              </button>
                              <button
                                type="button"
                                className={`${styles.optionCard} ${searchMethod === "full_text" ? styles.optionCardActive : ""}`}
                                onClick={() => setSearchMethod("full_text")}
                              >
                                <div className={styles.optionTitle}>{t("knowledge.fullTextSearch")}</div>
                                <div className={styles.optionDescription}>{t("knowledge.fullTextSearchDesc")}</div>
                              </button>
                              <button
                                type="button"
                                className={`${styles.optionCard} ${searchMethod === "hybrid" ? styles.optionCardActive : ""}`}
                                onClick={() => setSearchMethod("hybrid")}
                              >
                                <div className={styles.optionTitle}>{t("knowledge.hybridSearch")}</div>
                                <div className={styles.optionDescription}>{t("knowledge.hybridSearchDesc")}</div>
                              </button>
                            </>
                          ) : (
                            <button
                              type="button"
                              className={`${styles.optionCard} ${styles.optionCardActive}`}
                              onClick={() => setSearchMethod("keyword")}
                            >
                              <div className={styles.optionTitle}>{t("knowledge.keywordSearch")}</div>
                              <div className={styles.optionDescription}>{t("knowledge.keywordSearchDesc")}</div>
                            </button>
                          )}
                        </div>

                        <div className={styles.inlineFieldGrid}>
                          <Form.Item label={t("knowledge.topK")}>
                            <div className={styles.controlRow}>
                              <Form.Item noStyle name={["retrieval_config", "top_k"]}>
                                <InputNumber min={1} max={20} className={styles.controlInput} />
                              </Form.Item>
                              <Slider
                                className={styles.controlSlider}
                                min={1}
                                max={20}
                                step={1}
                                value={topK}
                                onChange={(value) => vectorForm.setFieldValue(["retrieval_config", "top_k"], value)}
                              />
                            </div>
                          </Form.Item>
                          {searchMethod !== "keyword" ? (
                            <Form.Item label={t("knowledge.scoreThreshold")}>
                                <div className={styles.thresholdControlRow}>
                                <Form.Item
                                  noStyle
                                  name={["retrieval_config", "score_threshold_enabled"]}
                                  valuePropName="checked"
                                >
                                  <Checkbox>{t("knowledge.enableScoreThreshold")}</Checkbox>
                                </Form.Item>
                                <Form.Item noStyle name={["retrieval_config", "score_threshold"]}>
                                  <InputNumber
                                    min={0}
                                    max={1}
                                    step={0.05}
                                    precision={2}
                                    className={styles.controlInput}
                                    disabled={!scoreThresholdEnabled}
                                  />
                                </Form.Item>
                                <Slider
                                  className={`${styles.controlSlider} ${styles.thresholdSlider}`}
                                  min={0}
                                  max={1}
                                  step={0.01}
                                  value={scoreThreshold}
                                  disabled={!scoreThresholdEnabled}
                                  onChange={(value) => vectorForm.setFieldValue(["retrieval_config", "score_threshold"], Number(value.toFixed(2)))}
                                />
                              </div>
                            </Form.Item>
                          ) : null}
                        </div>

                        {searchMethod === "hybrid" ? (
                          <div className={styles.inlineFieldGrid}>
                            <Form.Item label={t("knowledge.vectorWeight")}>
                              <div className={styles.controlRow}>
                                <Form.Item noStyle name={["retrieval_config", "weights", "vector_weight"]}>
                                  <InputNumber
                                    min={0}
                                    max={1}
                                    step={0.01}
                                    precision={2}
                                    className={styles.controlInput}
                                    onChange={(value) => {
                                      if (typeof value === "number") {
                                        setWeightBalance(value);
                                      }
                                    }}
                                  />
                                </Form.Item>
                                <Slider
                                  className={styles.controlSlider}
                                  min={0}
                                  max={1}
                                  step={0.01}
                                  value={vectorWeight}
                                  onChange={setWeightBalance}
                                />
                              </div>
                              <div className={styles.weightLegend}>
                                <span>{`${formatSliderValue(vectorWeight)} ${t("knowledge.vectorWeight")}`}</span>
                                <span>{`${formatSliderValue(keywordWeight)} ${t("knowledge.keywordWeight")}`}</span>
                              </div>
                            </Form.Item>
                          </div>
                        ) : null}
                      </div>

                      {highQualityMode ? (
                        <div className={styles.configSection}>
                          <div className={styles.configSectionTitle}>{t("knowledge.embeddingSection")}</div>
                          <EmbeddingModelConfigFields
                            namePath={["embedding_model_config"]}
                            showRestartAlert={false}
                          />
                        </div>
                      ) : null}

                      <div className={styles.vectorActions}>
                        <Button onClick={fetchVectorConfig}>{t("common.reset")}</Button>
                        <Button type="primary" loading={vectorSaving} onClick={handleSaveVectorConfig}>
                          {t("common.save")}
                        </Button>
                      </div>
                    </Form>
                  </div>
                </div>
              ),
            },
          ]}
        />
      </div>

      <Drawer
        width={980}
        open={drawerOpen}
        onClose={() => setDrawerOpen(false)}
        title={activeKnowledge ? `${t("knowledge.detailTitle")} · ${activeKnowledge.name}` : t("knowledge.detailTitle")}
      >
        <div className={styles.drawerContent}>
          {activeKnowledge ? (
            <div className={styles.drawerHeaderMeta}>
              <span>{t("knowledge.id")}: <span className={styles.monoText}>{activeKnowledge.id}</span></span>
              <span>{t("knowledge.slug")}: {activeKnowledge.slug}</span>
              <span>{t("knowledge.updatedAt")}: {formatDate(activeKnowledge.updated_at)}</span>
            </div>
          ) : null}

          <div className={styles.toolbar}>
            <Input
              className={styles.searchInput}
              allowClear
              value={documentSearch}
              placeholder={t("knowledge.documentSearchPlaceholder")}
              onChange={(event) => setDocumentSearch(event.target.value)}
            />
            <div className={styles.toolbarActions}>
              <Button onClick={() => activeKnowledge && fetchKnowledgeDetail(activeKnowledge.id)}>
                {t("common.refresh")}
              </Button>
              <Button
                type="primary"
                disabled={!uploadCapabilities?.can_upload}
                onClick={openUploadModal}
              >
                {t("knowledge.addFile")}
              </Button>
            </div>
          </div>

          {!uploadCapabilities?.can_upload ? (
            <Alert showIcon type="warning" message={t("knowledge.vectorModelRequired")} />
          ) : null}

          <Card className={styles.tableCard} loading={detailLoading}>
            <Table
              rowKey="id"
              columns={documentColumns}
              dataSource={filteredDocuments}
              tableLayout="fixed"
              pagination={false}
              locale={{ emptyText: t("knowledge.noDocuments") }}
              onRow={(record) => ({
                onClick: () => {
                  if (record.status !== "processing" && record.status !== "failed") {
                    openChunks(record);
                  }
                },
              })}
            />
          </Card>
        </div>
      </Drawer>

      <Modal
        open={createOpen}
        title={t("knowledge.createTitle")}
        onCancel={() => setCreateOpen(false)}
        onOk={handleCreateKnowledge}
      >
        <Form form={createForm} layout="vertical">
          <Form.Item
            label={t("knowledge.name")}
            name="name"
            rules={[{ required: true, message: t("knowledge.nameRequired") }]}
          >
            <Input placeholder={t("knowledge.namePlaceholder")} />
          </Form.Item>
          <Form.Item
            label={t("knowledge.id")}
            name="id"
            extra={t("knowledge.idHelp")}
            rules={[
              {
                pattern: /^[a-z0-9-]{6,32}$/,
                message: t("knowledge.idPattern"),
              },
            ]}
          >
            <Input placeholder={t("knowledge.idPlaceholder")} />
          </Form.Item>
        </Form>
      </Modal>

      <Modal
        open={renameKnowledgeOpen}
        title={t("knowledge.renameTitle")}
        onCancel={() => setRenameKnowledgeOpen(false)}
        onOk={handleRenameKnowledge}
      >
        <Form form={renameKnowledgeForm} layout="vertical">
          <Form.Item
            label={t("knowledge.name")}
            name="name"
            rules={[{ required: true, message: t("knowledge.nameRequired") }]}
          >
            <Input />
          </Form.Item>
        </Form>
      </Modal>

      <Modal
        open={renameDocumentOpen}
        title={t("knowledge.renameDocumentTitle")}
        onCancel={() => setRenameDocumentOpen(false)}
        onOk={handleRenameDocument}
      >
        <Form form={renameDocumentForm} layout="vertical">
          <Form.Item
            label={t("knowledge.name")}
            name="name"
            rules={[{ required: true, message: t("knowledge.nameRequired") }]}
          >
            <Input />
          </Form.Item>
        </Form>
      </Modal>

      <Modal
        open={uploadOpen}
        width="50%"
        className={styles.uploadModal}
        title={t("knowledge.uploadTitle")}
        onCancel={() => setUploadOpen(false)}
        footer={uploadFooter}
      >
        <Steps
          current={uploadStep}
          size="small"
          items={[
            { title: t("knowledge.uploadStepFile") },
            { title: t("knowledge.uploadStepChunk") },
          ]}
          style={{ width: "80%", marginLeft: "10%"}}
        />

        {uploadStep === 0 ? (
          <div className={styles.uploadStepPane}>
            <Alert
              showIcon
              type={uploadCapabilities?.can_upload ? "info" : "warning"}
              message={
                uploadCapabilities?.can_upload
                  ? t("knowledge.uploadHint")
                  : t("knowledge.vectorModelRequired")
              }
            />
            <div className={styles.uploadField}>
              <label className={styles.fieldLabel}>{t("knowledge.selectedFiles")}</label>
              <Upload.Dragger
                multiple
                accept=".pdf,.docx,.xlsx,.xls,.txt,.md,.markdown,.csv,.json,.yaml,.yml"
                beforeUpload={() => false}
                fileList={selectedFiles}
                onChange={({ fileList }) => setSelectedFiles(fileList)}
                onRemove={(file) => {
                  setSelectedFiles((current) => current.filter((item) => item.uid !== file.uid));
                  return true;
                }}
                showUploadList={{ showDownloadIcon: false }}
              >
                <p className={styles.uploadDragTitle}>{t("knowledge.uploadDragTitle")}</p>
                <p className={styles.uploadDragHint}>{t("knowledge.uploadDragHint")}</p>
              </Upload.Dragger>
              <div className={styles.metaText}>
                {selectedFiles.length > 0
                  ? t("knowledge.selectedFileCount", { count: selectedFiles.length })
                  : t("knowledge.noFilesSelected")}
              </div>
              <div className={styles.metaText}>
                {t("knowledge.supportedFormats", {
                  formats: uploadCapabilities?.supported_extensions.join(", ") || ".pdf, .docx, .xlsx, .xls, .txt, .md",
                })}
              </div>
            </div>
          </div>
        ) : (
          <div className={styles.uploadStepPane}>
            <Alert
              showIcon
              type="success"
              message={t("knowledge.vectorModelSummary", {
                provider: uploadCapabilities?.vector_model.provider || "-",
                model: uploadCapabilities?.vector_model.model_name || "-",
              })}
            />
            <div
              className={`${styles.uploadConfigContent} ${
                !uploadConfigExpanded ? styles.uploadConfigCollapsed : ""
              }`}
            >
            <Form form={uploadForm} layout="vertical">
              <Form.Item hidden name={["retrieval_config", "indexing_technique"]}>
                <Input />
              </Form.Item>
              <Form.Item hidden name={["retrieval_config", "search_method"]}>
                <Input />
              </Form.Item>
              <Form.Item hidden name={["retrieval_config", "reranking_enable"]}>
                <Input />
              </Form.Item>
              <Form.Item hidden name="mode">
                <Input />
              </Form.Item>
              <Form.Item hidden name="parent_chunk_size">
                <InputNumber />
              </Form.Item>
              <Form.Item hidden name="parent_chunk_overlap">
                <InputNumber />
              </Form.Item>
              <Form.Item hidden name="child_chunk_size">
                <InputNumber />
              </Form.Item>
              <Form.Item hidden name="child_chunk_overlap">
                <InputNumber />
              </Form.Item>
              <div className={styles.configSection}>
                <div className={styles.configSectionTitle}>{t("knowledge.indexingSection")}</div>
                <div className={styles.optionGridSingle}>
                  {uploadIndexingTechnique === "high_quality" ? (
                    <div className={`${styles.optionCard} ${styles.optionCardActive}`}>
                      <div className={styles.optionTitle}>{t("knowledge.highQuality")}</div>
                      <div className={styles.optionDescription}>{t("knowledge.highQualityDesc")}</div>
                    </div>
                  ) : (
                    <div className={`${styles.optionCard} ${styles.optionCardActive}`}>
                      <div className={styles.optionTitle}>{t("knowledge.economy")}</div>
                      <div className={styles.optionDescription}>{t("knowledge.economyDesc")}</div>
                    </div>
                  )}
                </div>
              </div>

              <div className={styles.configSection}>
                <div className={styles.configSectionTitle}>{t("knowledge.chunkSection")}</div>
                <div className={styles.optionGridSingle}>
                  {uploadChunkMode === "general" ? (
                    <div className={`${styles.optionCard} ${styles.optionCardActive}`}>
                      <div className={styles.optionTitle}>{t("knowledge.chunkModeGeneral")}</div>
                      <div className={styles.optionDescription}>{t("knowledge.chunkModeGeneralDesc")}</div>
                    </div>
                  ) : (
                    <div className={`${styles.optionCard} ${styles.optionCardActive}`}>
                      <div className={styles.optionTitle}>{t("knowledge.chunkModeParentChild")}</div>
                      <div className={styles.optionDescription}>
                        {uploadIndexingTechnique === "high_quality"
                          ? t("knowledge.chunkModeParentChildDesc")
                          : t("knowledge.chunkModeParentChildHighQualityOnly")}
                      </div>
                    </div>
                  )}
                </div>
              {uploadChunkMode === "general" ? (
                <div className={styles.inlineFieldGrid}>
                  <Form.Item label={t("knowledge.chunkSeparator")} name="separator">
                    <Input placeholder={t("knowledge.chunkSeparatorPlaceholder")} />
                  </Form.Item>
                  <Form.Item label={t("knowledge.chunkGranularity")} name="granularity">
                    <Select
                      options={[
                        { label: t("knowledge.chunkGranularityBalanced"), value: "balanced" },
                        { label: t("knowledge.chunkGranularityParagraph"), value: "paragraph" },
                        { label: t("knowledge.chunkGranularitySentence"), value: "sentence" },
                      ]}
                    />
                  </Form.Item>
                  <Form.Item label={t("knowledge.chunkSize")} name="chunk_size">
                    <InputNumber min={100} max={4000} step={100} style={{ width: "100%" }} />
                  </Form.Item>
                  <Form.Item label={t("knowledge.chunkOverlap")} name="chunk_overlap">
                    <InputNumber min={0} max={1000} step={10} style={{ width: "100%" }} />
                  </Form.Item>
                  <Form.Item
                    label={t("knowledge.normalizeWhitespace")}
                    tooltip={t("knowledge.normalizeWhitespaceHelp")}
                    name="normalize_whitespace"
                    valuePropName="checked"
                  >
                    <Switch />
                  </Form.Item>
                  <Form.Item
                    label={t("knowledge.llmGrouping")}
                    tooltip={t("knowledge.llmGroupingHelp")}
                    name="llm_grouping"
                    valuePropName="checked"
                  >
                    <Switch />
                  </Form.Item>
                </div>
              ) : (
                <>
                  <div className={styles.subSectionTitle}>{t("knowledge.parentChunkSection")}</div>
                  <div className={styles.inlineFieldGrid}>
                  <Form.Item label={t("knowledge.parentChunkSize")} name="parent_chunk_size">
                    <InputNumber min={100} max={8000} step={100} style={{ width: "100%" }} />
                  </Form.Item>
                  <Form.Item label={t("knowledge.parentChunkOverlap")} name="parent_chunk_overlap">
                    <InputNumber min={0} max={2000} step={10} style={{ width: "100%" }} />
                  </Form.Item>
                  <Form.Item label={t("knowledge.parentChunkSeparator")} name="parent_separator">
                    <Input placeholder={t("knowledge.chunkSeparatorPlaceholder")} />
                  </Form.Item>
                  <Form.Item
                    label={t("knowledge.normalizeWhitespace")}
                    tooltip={t("knowledge.normalizeWhitespaceHelp")}
                    name="parent_normalize_whitespace"
                    valuePropName="checked"
                  >
                    <Switch />
                  </Form.Item>
                  <Form.Item
                    label={t("knowledge.llmGrouping")}
                    tooltip={t("knowledge.llmGroupingHelp")}
                    name="llm_grouping"
                    valuePropName="checked"
                  >
                    <Switch />
                  </Form.Item>
                  </div>
                  <div className={styles.subSectionTitle}>{t("knowledge.childChunkSection")}</div>
                  <div className={styles.inlineFieldGrid}>
                  <Form.Item label={t("knowledge.childChunkSize")} name="child_chunk_size">
                    <InputNumber min={100} max={4000} step={50} style={{ width: "100%" }} />
                  </Form.Item>
                  <Form.Item label={t("knowledge.childChunkOverlap")} name="child_chunk_overlap">
                    <InputNumber min={0} max={1000} step={10} style={{ width: "100%" }} />
                  </Form.Item>
                  <Form.Item label={t("knowledge.childChunkSeparator")} name="child_separator">
                    <Input placeholder={t("knowledge.chunkSeparatorPlaceholder")} />
                  </Form.Item>
                  <Form.Item
                    label={t("knowledge.normalizeWhitespace")}
                    tooltip={t("knowledge.normalizeWhitespaceHelp")}
                    name="child_normalize_whitespace"
                    valuePropName="checked"
                  >
                    <Switch />
                  </Form.Item>
                  <Form.Item label={t("knowledge.chunkGranularity")} name="granularity">
                    <Select
                      options={[
                        { label: t("knowledge.chunkGranularityBalanced"), value: "balanced" },
                        { label: t("knowledge.chunkGranularityParagraph"), value: "paragraph" },
                        { label: t("knowledge.chunkGranularitySentence"), value: "sentence" },
                      ]}
                    />
                  </Form.Item>
                  </div>
                </>
              )}
              <div className={styles.separatorHint}>{t("knowledge.chunkSeparatorHelp")}</div>
              </div>

              <div className={styles.configSection}>
                <div className={styles.configSectionTitle}>{t("knowledge.retrievalSection")}</div>
                <div className={styles.optionGridSingle}>
                  {uploadIndexingTechnique === "high_quality" ? (
                    <>
                      {uploadSearchMethod === "semantic" ? (
                        <div className={`${styles.optionCard} ${styles.optionCardActive}`}>
                          <div className={styles.optionTitle}>{t("knowledge.semanticSearch")}</div>
                          <div className={styles.optionDescription}>{t("knowledge.semanticSearchDesc")}</div>
                        </div>
                      ) : null}
                      {uploadSearchMethod === "full_text" ? (
                        <div className={`${styles.optionCard} ${styles.optionCardActive}`}>
                          <div className={styles.optionTitle}>{t("knowledge.fullTextSearch")}</div>
                          <div className={styles.optionDescription}>{t("knowledge.fullTextSearchDesc")}</div>
                        </div>
                      ) : null}
                      {uploadSearchMethod === "hybrid" ? (
                        <div className={`${styles.optionCard} ${styles.optionCardActive}`}>
                          <div className={styles.optionTitle}>{t("knowledge.hybridSearch")}</div>
                          <div className={styles.optionDescription}>{t("knowledge.hybridSearchDesc")}</div>
                        </div>
                      ) : null}
                    </>
                  ) : (
                    <div className={`${styles.optionCard} ${styles.optionCardActive}`}>
                      <div className={styles.optionTitle}>{t("knowledge.keywordSearch")}</div>
                      <div className={styles.optionDescription}>{t("knowledge.keywordSearchDesc")}</div>
                    </div>
                  )}
                </div>

                <div className={styles.inlineFieldGrid}>
                <Form.Item label={t("knowledge.topK")}>
                  <div className={styles.controlRow}>
                    <Form.Item noStyle name={["retrieval_config", "top_k"]}>
                      <InputNumber min={1} max={20} className={styles.controlInput} />
                    </Form.Item>
                    <Slider
                      className={styles.controlSlider}
                      min={1}
                      max={20}
                      step={1}
                      value={uploadTopK}
                      onChange={(value) => uploadForm.setFieldValue(["retrieval_config", "top_k"], value)}
                    />
                  </div>
                </Form.Item>
                {uploadSearchMethod !== "keyword" ? (
                  <Form.Item label={t("knowledge.scoreThreshold")}>
                    <div className={styles.thresholdControlRow}>
                      <Form.Item
                        noStyle
                        name={["retrieval_config", "score_threshold_enabled"]}
                        valuePropName="checked"
                      >
                        <Checkbox>{t("knowledge.enableScoreThreshold")}</Checkbox>
                      </Form.Item>
                      <Form.Item noStyle name={["retrieval_config", "score_threshold"]}>
                        <InputNumber
                          min={0}
                          max={1}
                          step={0.05}
                          precision={2}
                          className={styles.controlInput}
                          disabled={!uploadScoreThresholdEnabled}
                        />
                      </Form.Item>
                      <Slider
                        className={`${styles.controlSlider} ${styles.thresholdSlider}`}
                        min={0}
                        max={1}
                        step={0.01}
                        value={uploadScoreThreshold}
                        disabled={!uploadScoreThresholdEnabled}
                        onChange={(value) => uploadForm.setFieldValue(["retrieval_config", "score_threshold"], Number(value.toFixed(2)))}
                      />
                    </div>
                  </Form.Item>
                ) : null}
                </div>
              {uploadSearchMethod === "hybrid" ? (
                <div className={styles.inlineFieldGrid}>
                  <Form.Item label={t("knowledge.vectorWeight")}>
                    <div className={styles.controlRow}>
                      <Form.Item noStyle name={["retrieval_config", "weights", "vector_weight"]}>
                        <InputNumber
                          min={0}
                          max={1}
                          step={0.01}
                          precision={2}
                          className={styles.controlInput}
                          onChange={(value) => {
                            if (typeof value === "number") {
                              const safeVectorWeight = Number(
                                Math.min(1, Math.max(0, value)).toFixed(2),
                              );
                              uploadForm.setFieldsValue({
                                retrieval_config: {
                                  ...uploadForm.getFieldValue("retrieval_config"),
                                  weights: {
                                    vector_weight: safeVectorWeight,
                                    keyword_weight: Number((1 - safeVectorWeight).toFixed(2)),
                                  },
                                },
                              });
                            }
                          }}
                        />
                      </Form.Item>
                      <Slider
                        className={styles.controlSlider}
                        min={0}
                        max={1}
                        step={0.01}
                        value={uploadVectorWeight}
                        onChange={(value) => {
                          const safeVectorWeight = Number(
                            Math.min(1, Math.max(0, value)).toFixed(2),
                          );
                          uploadForm.setFieldsValue({
                            retrieval_config: {
                              ...uploadForm.getFieldValue("retrieval_config"),
                              weights: {
                                vector_weight: safeVectorWeight,
                                keyword_weight: Number((1 - safeVectorWeight).toFixed(2)),
                              },
                            },
                          });
                        }}
                      />
                    </div>
                    <div className={styles.weightLegend}>
                      <span>{`${formatSliderValue(uploadVectorWeight)} ${t("knowledge.vectorWeight")}`}</span>
                      <span>{`${formatSliderValue(uploadKeywordWeight)} ${t("knowledge.keywordWeight")}`}</span>
                    </div>
                  </Form.Item>
                </div>
              ) : null}
              </div>
            </Form>
            {!uploadConfigExpanded ? <div className={styles.uploadConfigFade} /> : null}
            </div>
            <div className={styles.uploadConfigToggleRow}>
              <Button type="link" onClick={() => setUploadConfigExpanded((current) => !current)}>
                {uploadConfigExpanded
                  ? t("knowledge.collapseAll")
                  : t("knowledge.expandAll")}
              </Button>
            </div>
          </div>
        )}
      </Modal>

      <Modal
        width={chunkModalWidth}
        open={chunksOpen}
        onCancel={() => setChunksOpen(false)}
        title={selectedDocument ? `${t("knowledge.chunkTitle")} · ${selectedDocument.name}` : t("knowledge.chunkTitle")}
        footer={null}
        className={styles.chunkModal}
        styles={{ body: { overflow: "hidden" } }}
      >
        <div className={styles.chunkModalShell}>
          <div
            className={styles.chunkResizeHandle}
            onMouseDown={startChunkResize}
            role="separator"
            aria-orientation="vertical"
            aria-label={t("knowledge.chunkResizeHandle")}
          />
          <div className={styles.chunkModalContent}>
          <div className={styles.toolbar}>
            <Input
              className={styles.searchInput}
              allowClear
              value={chunkSearch}
              placeholder={t("knowledge.chunkSearchPlaceholder")}
              onChange={(event) => setChunkSearch(event.target.value)}
              onPressEnter={() => selectedDocument && loadChunkPage(selectedDocument, { page: 1, search: chunkSearch })}
            />
            <div className={styles.toolbarActions}>
              <Button
                onClick={() => selectedDocument && loadChunkPage(selectedDocument, { page: 1, search: chunkSearch })}
              >
                {t("common.refresh")}
              </Button>
            </div>
          </div>

          <Card className={`${styles.tableCard} ${styles.chunkTableCard}`}>
            <Table
              rowKey="id"
              loading={chunksLoading}
              columns={chunkColumns}
              dataSource={chunks}
              scroll={{ y: "calc(100vh - 320px)" }}
              pagination={{
                current: chunkPage,
                pageSize: chunkPageSize,
                total: chunkTotal,
                showSizeChanger: true,
                onChange: (page, pageSize) => {
                  if (selectedDocument) {
                    loadChunkPage(selectedDocument, { page, pageSize, search: chunkSearch });
                  }
                },
              }}
            />
          </Card>
          </div>
        </div>
      </Modal>

      <Modal
        width="50%"
        open={editChunkOpen}
        title={t("knowledge.chunkEditTitle")}
        onCancel={() => {
          setEditChunkOpen(false);
          setEditingChunk(null);
        }}
        onOk={handleSaveChunk}
      >
        <Form form={chunkForm} layout="vertical">
          <Form.Item
            label={t("knowledge.name")}
            name="name"
            rules={[{ required: true, message: t("knowledge.nameRequired") }]}
          >
            <Input />
          </Form.Item>
          <Form.Item
            label={t("knowledge.content")}
            name="content"
            rules={[{ required: true, message: t("knowledge.chunkContentRequired") }]}
          >
            <Input.TextArea rows={8} />
          </Form.Item>
        </Form>
      </Modal>

      <Modal
        open={renameChunkOpen}
        title={t("knowledge.chunkRenameTitle")}
        onCancel={() => {
          setRenameChunkOpen(false);
          setRenamingChunk(null);
        }}
        onOk={handleRenameChunk}
      >
        <Form form={renameChunkForm} layout="vertical">
          <Form.Item
            label={t("knowledge.name")}
            name="name"
            rules={[{ required: true, message: t("knowledge.nameRequired") }]}
          >
            <Input />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  );
}
