import {
  useState,
  useEffect,
  useMemo,
  useCallback,
  useDeferredValue,
  useRef,
} from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
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
import {
  Trash2,
  Plus,
  Network,
  Eye,
  Settings,
  ChevronDown,
  Search,
  FlaskConical,
  Database,
  User,
  Gift,
  VideoIcon,
  FileText,
  Layers,
  HelpCircle,
} from "lucide-react";
import type {
  ProviderInfo,
  SeriesResponse,
  ModelInfo,
  ExtendedModelInfo,
} from "../../../../../api/types";

import api from "../../../../../api";
import { useTranslation } from "react-i18next";
import { useTheme } from "../../../../../contexts/ThemeContext";
import { useAppMessage } from "../../../../../hooks/useAppMessage";
import { JsonConfigEditor } from "./JsonConfigEditor.tsx";
import {
  getLocalizedTestConnectionMessage,
  getTestConnectionFailureDetail,
} from "./testConnectionMessage";
import { OpenRouterFilterSection } from "./OpenRouterFilterSection";
import styles from "../../index.module.less";

const tagColors = (isDark: boolean) => ({
  multimodal: {
    backgroundColor: isDark ? "rgba(24,144,255,0.15)" : "#e6f7ff",
    color: "#1890ff",
    borderColor: isDark ? "rgba(24,144,255,0.3)" : "#91d5ff",
  },
  vision: {
    backgroundColor: isDark ? "rgba(19,194,194,0.15)" : "#e6fffb",
    color: "#13c2c2",
    borderColor: isDark ? "rgba(19,194,194,0.3)" : "#87e8de",
  },
  video: {
    backgroundColor: isDark ? "rgba(114,46,211,0.15)" : "#f9f0ff",
    color: "#722ed1",
    borderColor: isDark ? "rgba(114,46,211,0.3)" : "#d3adf7",
  },
  text: {
    backgroundColor: isDark ? "rgba(255,255,255,0.1)" : "#f5f5f5",
    color: isDark ? "rgba(255,255,255,0.65)" : "#595959",
    borderColor: isDark ? "rgba(255,255,255,0.15)" : "#d9d9d9",
  },
  notProbed: {
    backgroundColor: isDark ? "rgba(255,255,255,0.1)" : "#f5f5f5",
    color: isDark ? "rgba(255,255,255,0.65)" : "#8c8c8c",
    borderColor: isDark ? "rgba(255,255,255,0.15)" : "#d9d9d9",
  },
  builtin: {
    backgroundColor: isDark ? "rgba(82,196,26,0.15)" : "#f6ffed",
    color: "#52c41a",
    borderColor: isDark ? "rgba(82,196,26,0.3)" : "#b7eb8f",
  },
  free: {
    backgroundColor: isDark ? "rgba(82,196,26,0.15)" : "#f6ffed",
    color: "#52c41a",
    borderColor: isDark ? "rgba(82,196,26,0.3)" : "#b7eb8f",
  },
  userAdded: {
    backgroundColor: isDark ? "rgba(24,144,255,0.15)" : "#e6f7ff",
    color: "#1890ff",
    borderColor: isDark ? "rgba(24,144,255,0.3)" : "#91d5ff",
  },
});

interface RemoteModelManageModalProps {
  provider: ProviderInfo;
  open: boolean;
  onClose: () => void;
  onSaved: () => void | Promise<void>;
}

function CapabilityTags({
  model,
  isDark,
}: {
  model: ModelInfo;
  isDark: boolean;
}) {
  const { t } = useTranslation();
  const c = tagColors(isDark);
  if (model.supports_image && model.supports_video) {
    return (
      <Badge
        variant="outline"
        style={{ fontSize: 11, marginRight: 4, ...c.multimodal }}
      >
        <Layers
          style={{ fontSize: 10, marginRight: 3, height: 10, width: 10 }}
        />
        {t("models.tagMultimodal", "多模态")}
      </Badge>
    );
  }
  if (model.supports_image) {
    return (
      <Badge
        variant="outline"
        style={{ fontSize: 11, marginRight: 4, ...c.vision }}
      >
        <Eye style={{ fontSize: 10, marginRight: 3, height: 10, width: 10 }} />
        {t("models.tagVision", "视觉")}
      </Badge>
    );
  }
  if (model.supports_video) {
    return (
      <Badge
        variant="outline"
        style={{ fontSize: 11, marginRight: 4, ...c.video }}
      >
        <VideoIcon
          style={{ fontSize: 10, marginRight: 3, height: 10, width: 10 }}
        />
        {t("models.tagVideo", "视频")}
      </Badge>
    );
  }
  if (model.supports_multimodal === false) {
    return (
      <Badge
        variant="outline"
        style={{ fontSize: 11, marginRight: 4, ...c.text }}
      >
        <FileText
          style={{ fontSize: 10, marginRight: 3, height: 10, width: 10 }}
        />
        {t("models.tagText", "文本")}
      </Badge>
    );
  }
  return (
    <Badge
      variant="outline"
      style={{ fontSize: 11, marginRight: 4, ...c.notProbed }}
    >
      <HelpCircle
        style={{ fontSize: 10, marginRight: 3, height: 10, width: 10 }}
      />
      {t("models.tagNotProbed", "未检测")}
    </Badge>
  );
}

function ModelConfigEditor({
  providerId,
  model,
  onSaved,
  onClose,
  isDark,
}: {
  providerId: string;
  model: ModelInfo;
  onSaved: () => void | Promise<void>;
  onClose: () => void;
  isDark: boolean;
}) {
  const { t } = useTranslation();
  const { message } = useAppMessage();
  const [saving, setSaving] = useState(false);

  const [maxTokens, setMaxTokens] = useState<number | null>(
    model.max_tokens ?? 8192,
  );
  const [maxInputLength, setMaxInputLength] = useState<number | null>(
    model.max_input_length ?? 131072,
  );

  const initialText = useMemo(
    () =>
      model.generate_kwargs && Object.keys(model.generate_kwargs).length > 0
        ? JSON.stringify(model.generate_kwargs, null, 2)
        : "",
    [model.generate_kwargs],
  );

  const [text, setText] = useState(initialText);
  const [dirty, setDirty] = useState(false);

  useEffect(() => {
    setText(initialText);
    setMaxTokens(model.max_tokens ?? 8192);
    setMaxInputLength(model.max_input_length ?? 131072);
    setDirty(false);
  }, [initialText, model.max_tokens, model.max_input_length]);

  const effectiveMaxTokens = maxTokens ?? 8192;
  const effectiveMaxInputLength = maxInputLength ?? 131072;

  const handleChange = useCallback((val: string) => {
    setText(val);
    setDirty(true);
  }, []);

  const handleSave = async () => {
    const trimmed = text.trim();
    let parsed: Record<string, unknown> = {};
    if (trimmed) {
      try {
        const obj = JSON.parse(trimmed);
        if (!obj || typeof obj !== "object" || Array.isArray(obj)) {
          message.error(t("models.generateConfigMustBeObject"));
          return;
        }
        parsed = obj;
      } catch {
        message.error(t("models.generateConfigInvalidJson"));
        return;
      }
    }

    setSaving(true);
    try {
      await api.configureModel(providerId, model.id, {
        max_tokens: effectiveMaxTokens,
        max_input_length: effectiveMaxInputLength,
        generate_kwargs: parsed,
      });
      message.success(t("models.modelConfigSaved", { name: model.name }));
      setDirty(false);
      await onSaved();
      onClose();
    } catch (error) {
      const errMsg =
        error instanceof Error
          ? error.message
          : t("models.modelConfigSaveFailed");
      message.error(errMsg);
    } finally {
      setSaving(false);
    }
  };

  const labelClass = `text-sm font-medium mb-1 ${
    isDark ? "text-white/85" : "text-gray-800"
  }`;
  const hintClass = `text-xs mt-1 ${
    isDark ? "text-white/35" : "text-gray-400"
  }`;

  return (
    <div className="py-2">
      <div className="flex gap-4 mb-3">
        <div className="flex-1">
          <div className={labelClass}>
            {t("models.maxTokensLabel", "Max Tokens")}
          </div>
          <Input
            type="number"
            min={1}
            step={1024}
            value={maxTokens ?? ""}
            placeholder="8192"
            onChange={(e) => {
              const v = parseInt(e.target.value, 10);
              setMaxTokens(isNaN(v) ? null : v);
              setDirty(true);
            }}
          />
          <div className={hintClass}>
            {t("models.maxTokensHint", "每次响应的最大输出 token 数")}
          </div>
        </div>
        <div className="flex-1">
          <div className={labelClass}>
            {t("models.maxInputLengthLabel", "Max Context Length")}
          </div>
          <Input
            type="number"
            min={1000}
            step={1024}
            value={maxInputLength ?? ""}
            placeholder="131072"
            onChange={(e) => {
              const v = parseInt(e.target.value, 10);
              setMaxInputLength(isNaN(v) ? null : v);
              setDirty(true);
            }}
          />
          <div className={hintClass}>
            {t("models.maxInputLengthHint", "模型上下文窗口大小")}
          </div>
        </div>
      </div>
      <div
        className={`text-xs mb-1 ${isDark ? "text-white/45" : "text-gray-500"}`}
      >
        {t("models.modelGenerateConfigHint")}
      </div>
      <JsonConfigEditor
        value={text}
        onChange={handleChange}
        placeholder={`Example:\n{\n  "extra_body": {\n    "enable_thinking": false\n  }\n}`}
      />
      <div className="flex justify-end mt-2 gap-2">
        <Button size="sm" disabled={!dirty || saving} onClick={handleSave}>
          {t("models.save")}
        </Button>
      </div>
    </div>
  );
}

export function RemoteModelManageModal({
  provider,
  open,
  onClose,
  onSaved,
}: RemoteModelManageModalProps) {
  const { t } = useTranslation();
  const { isDark } = useTheme();
  const { message } = useAppMessage();
  const supportsAutoDiscover = provider.support_model_discovery;
  const [adding, setAdding] = useState(false);
  const [saving, setSaving] = useState(false);
  const [discoveringModels, setDiscoveringModels] = useState(false);
  const [testingModelId, setTestingModelId] = useState<string | null>(null);
  const [probingModelId, setProbingModelId] = useState<string | null>(null);
  const [configOpenModelId, setConfigOpenModelId] = useState<string | null>(
    null,
  );
  const [modelSearchQuery, setModelSearchQuery] = useState("");
  const [modelIdInput, setModelIdInput] = useState("");
  const [modelNameInput, setModelNameInput] = useState("");
  const [showSuggestions, setShowSuggestions] = useState(false);

  // AlertDialog states
  const [testFailDialog, setTestFailDialog] = useState<{
    open: boolean;
    id: string;
    name: string;
    message: string;
  } | null>(null);
  const [removeDialog, setRemoveDialog] = useState<{
    open: boolean;
    id: string;
    name: string;
  } | null>(null);

  // OpenRouter filter state
  const isOpenRouter = provider.id === "openrouter";
  const [showFilters, setShowFilters] = useState(false);
  const [availableSeries, setAvailableSeries] = useState<string[]>([]);
  const [discoveredModels, setDiscoveredModels] = useState<ExtendedModelInfo[]>(
    [],
  );
  const [selectedSeries, setSelectedSeries] = useState<string[]>([]);
  const [selectedInputModalities, setSelectedInputModalities] = useState<
    string[]
  >([]);
  const [showFreeOnly, setShowFreeOnly] = useState(false);
  const [loadingFilters, setLoadingFilters] = useState(false);
  const [loadingDiscoveredModels, setLoadingDiscoveredModels] = useState(false);

  const PAGE_SIZE = 30;
  const [visibleCount, setVisibleCount] = useState(PAGE_SIZE);

  const extraModelIds = new Set((provider.extra_models || []).map((m) => m.id));
  const suggestionsRef = useRef<HTMLDivElement>(null);

  const doAddModel = async (id: string, name: string) => {
    await api.addModel(provider.id, { id, name });
    message.success(t("models.modelAdded", { name }));
    setModelIdInput("");
    setModelNameInput("");
    setAdding(false);
    onSaved();
  };

  const handleAddModel = async () => {
    const id = modelIdInput.trim();
    if (!id) return;
    const name = modelNameInput.trim() || id;
    const modelAlreadyExists = [
      ...(provider.models ?? []),
      ...(provider.extra_models ?? []),
    ].some((model) => model.id.trim() === id);

    if (modelAlreadyExists) {
      message.warning(t("models.modelAlreadyExists", { id }));
      return;
    }

    setSaving(true);
    const testResult = await api.testModelConnection(provider.id, {
      model_id: id,
    });

    if (!testResult.success) {
      setSaving(false);
      const failureDetail =
        getTestConnectionFailureDetail(testResult.message) ||
        t("models.modelTestFailed");
      setTestFailDialog({ open: true, id, name, message: failureDetail });
      return;
    }

    try {
      await doAddModel(id, name);
    } catch (error) {
      const errMsg =
        error instanceof Error ? error.message : t("models.modelAddFailed");
      message.error(errMsg);
    } finally {
      setSaving(false);
    }
  };

  const handleTestModel = async (modelId: string) => {
    setTestingModelId(modelId);
    try {
      const result = await api.testModelConnection(provider.id, {
        model_id: modelId,
      });
      if (result.success) {
        message.success(getLocalizedTestConnectionMessage(result, t));
      } else {
        message.warning(getLocalizedTestConnectionMessage(result, t));
      }
    } catch (error) {
      const errMsg =
        error instanceof Error
          ? error.message
          : t("models.testConnectionError");
      message.error(errMsg);
    } finally {
      setTestingModelId(null);
    }
  };

  const handleProbeMultimodal = async (modelId: string) => {
    setProbingModelId(modelId);
    try {
      const result = await api.probeMultimodal(provider.id, modelId);
      const parts: string[] = [];
      if (result.supports_image) parts.push(t("models.probeImage"));
      if (result.supports_video) parts.push(t("models.probeVideo"));
      if (parts.length > 0) {
        message.success(
          t("models.probeSupported", { types: parts.join(", ") }),
        );
      } else {
        message.info(t("models.probeNotSupported"));
      }
      await onSaved();
    } catch (error) {
      const errMsg =
        error instanceof Error ? error.message : t("models.probeFailed");
      message.error(errMsg);
    } finally {
      setProbingModelId(null);
    }
  };

  const handleRemoveModel = (modelId: string, modelName: string) => {
    setRemoveDialog({ open: true, id: modelId, name: modelName });
  };

  const confirmRemoveModel = async () => {
    if (!removeDialog) return;
    try {
      await api.removeModel(provider.id, removeDialog.id);
      message.success(t("models.modelRemoved", { name: removeDialog.name }));
      await onSaved();
    } catch (error) {
      const errMsg =
        error instanceof Error ? error.message : t("models.modelRemoveFailed");
      message.error(errMsg);
    } finally {
      setRemoveDialog(null);
    }
  };

  const handleClose = () => {
    setAdding(false);
    setConfigOpenModelId(null);
    setModelSearchQuery("");
    setVisibleCount(PAGE_SIZE);
    setModelIdInput("");
    setModelNameInput("");
    onClose();
  };

  // Load available series for OpenRouter
  useEffect(() => {
    if (isOpenRouter) {
      api
        .getOpenRouterSeries()
        .then((res: SeriesResponse) => {
          const series = res.series || [];
          setAvailableSeries(series);
          setSelectedSeries((prev) =>
            prev.length === 0
              ? series
              : prev.filter((item) => series.includes(item)),
          );
        })
        .catch(() => {
          setAvailableSeries([]);
          setSelectedSeries([]);
        });
    }
  }, [isOpenRouter]);

  const handleFetchModels = async () => {
    if (!isOpenRouter) return;
    setLoadingFilters(true);
    try {
      const filterBody: Record<string, unknown> = {};
      const hasPartialProviderSelection =
        selectedSeries.length > 0 &&
        selectedSeries.length < availableSeries.length;
      if (hasPartialProviderSelection) {
        filterBody.providers = selectedSeries;
      }
      if (selectedInputModalities.length > 0) {
        filterBody.input_modalities = selectedInputModalities;
      }
      if (showFreeOnly) {
        filterBody.is_free = true;
      }
      const result = await api.filterOpenRouterModels(filterBody);
      if (result.success) {
        setDiscoveredModels(result.models || []);
        message.success(
          t("models.filteredModelsLoaded", { count: result.total_count }),
        );
      } else {
        message.error(t("models.filterFailed"));
      }
    } catch {
      message.error(t("models.filterFailed"));
    } finally {
      setLoadingFilters(false);
    }
  };

  const handleAddFilteredModel = async (model: ExtendedModelInfo) => {
    setSaving(true);
    try {
      await api.addModel(provider.id, {
        id: model.id,
        name: model.name,
        is_free: model.is_free,
        supports_multimodal: model.supports_multimodal,
        supports_image: model.supports_image,
        supports_video: model.supports_video,
        probe_source: model.probe_source,
      });
      message.success(t("models.modelAdded", { name: model.name }));
      await onSaved();
      setDiscoveredModels((prev) => prev.filter((m) => m.id !== model.id));
    } catch {
      message.error(t("models.modelAddFailed"));
    } finally {
      setSaving(false);
    }
  };

  const handleAutoDiscoverModels = async () => {
    setDiscoveringModels(true);
    try {
      const result = await api.discoverModels(provider.id, undefined, true);
      if (!result.success) {
        message.error(result.message || t("models.autoDiscoverModelsFailed"));
        return;
      }
      await onSaved();
      if (result.added_count > 0) {
        message.success(
          t("models.autoDiscoverModelsSuccess", { count: result.added_count }),
        );
        return;
      }
      message.info(
        result.message ||
          t("models.autoDiscoverModelsNoNew", { count: result.models.length }),
      );
    } catch (error) {
      const errMsg =
        error instanceof Error
          ? error.message
          : t("models.autoDiscoverModelsFailed");
      message.error(errMsg);
    } finally {
      setDiscoveringModels(false);
    }
  };

  useEffect(() => {
    if (!adding) {
      setDiscoveredModels([]);
      return;
    }
    setLoadingDiscoveredModels(true);
    api
      .discoverModels(provider.id, undefined, false)
      .then((result) => {
        const sorted = result.models
          .slice()
          .sort((a, b) => a.id.localeCompare(b.id));
        setDiscoveredModels(sorted as unknown as ExtendedModelInfo[]);
      })
      .catch(() => setDiscoveredModels([]))
      .finally(() => setLoadingDiscoveredModels(false));
  }, [adding, provider.id]);

  useEffect(() => {
    if (!isOpenRouter || !adding) return;
    setAdding(false);
    setModelIdInput("");
    setModelNameInput("");
  }, [adding, isOpenRouter]);

  const deferredSearchQuery = useDeferredValue(modelSearchQuery);

  useEffect(() => {
    setVisibleCount(PAGE_SIZE);
  }, [deferredSearchQuery]);

  const filteredModels = useMemo(() => {
    const all_models = [
      ...(provider.extra_models ?? []),
      ...(provider.models ?? []),
    ];
    const q = deferredSearchQuery.trim().toLowerCase();
    if (!q) return all_models;
    return all_models.filter(
      (m) => m.name.toLowerCase().includes(q) || m.id.toLowerCase().includes(q),
    );
  }, [provider.models, provider.extra_models, deferredSearchQuery]);

  const colors = tagColors(isDark);

  const filteredSuggestions = useMemo(() => {
    const q = modelIdInput.trim().toLowerCase();
    if (!q) return discoveredModels;
    return discoveredModels.filter((m) => m.id.toLowerCase().includes(q));
  }, [discoveredModels, modelIdInput]);

  return (
    <>
      <Dialog
        open={open}
        onOpenChange={(v) => {
          if (!v) handleClose();
        }}
      >
        <DialogContent className="max-w-3xl max-h-[90vh] overflow-y-auto">
          <DialogHeader>
            <DialogTitle>
              {t("models.manageModelsTitle", { provider: provider.name })}
            </DialogTitle>
          </DialogHeader>

          <div className="relative">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
            <Input
              className="pl-9"
              placeholder={t("models.searchModelPlaceholder", "搜索模型...")}
              value={modelSearchQuery}
              onChange={(e) => setModelSearchQuery(e.target.value)}
            />
          </div>

          {/* Model list */}
          <div className={styles.modelList}>
            {filteredModels.length === 0 ? (
              <div className={styles.modelListEmpty}>
                {t("models.noModels")}
              </div>
            ) : (
              <>
                {filteredModels.slice(0, visibleCount).map((m) => {
                  const isDeletable =
                    provider.is_custom || extraModelIds.has(m.id);
                  const isConfigOpen = configOpenModelId === m.id;
                  return (
                    <div key={m.id}>
                      <div className={styles.modelListItem}>
                        <div className={styles.modelListItemInfo}>
                          <span className={styles.modelListItemName}>
                            {m.name}
                          </span>
                          <span className={styles.modelListItemId}>{m.id}</span>
                        </div>
                        <div className={styles.modelListItemActions}>
                          <CapabilityTags model={m} isDark={isDark} />
                          {m.is_free && (
                            <Badge
                              variant="outline"
                              style={{
                                fontSize: 11,
                                marginRight: 4,
                                ...colors.free,
                              }}
                            >
                              <Gift
                                style={{
                                  height: 10,
                                  width: 10,
                                  marginRight: 3,
                                }}
                              />
                              {t("models.free")}
                            </Badge>
                          )}
                          <Badge
                            variant="outline"
                            style={{
                              fontSize: 11,
                              marginRight: 4,
                              ...(isDeletable
                                ? colors.userAdded
                                : colors.builtin),
                            }}
                          >
                            {isDeletable ? (
                              <User
                                style={{
                                  height: 10,
                                  width: 10,
                                  marginRight: 3,
                                }}
                              />
                            ) : (
                              <Database
                                style={{
                                  height: 10,
                                  width: 10,
                                  marginRight: 3,
                                }}
                              />
                            )}
                            {t(
                              isDeletable
                                ? "models.userAdded"
                                : "models.builtin",
                            )}
                          </Badge>
                          <span
                            style={{
                              display: "inline-block",
                              width: 1,
                              height: 16,
                              background: isDark
                                ? "rgba(255,255,255,0.15)"
                                : "#e5e7eb",
                              margin: "0 8px",
                              flexShrink: 0,
                            }}
                          />
                          {m.probe_source !== "documentation" && (
                            <Tooltip>
                              <TooltipTrigger asChild>
                                <Button
                                  variant="ghost"
                                  size="sm"
                                  disabled={probingModelId === m.id}
                                  onClick={() => handleProbeMultimodal(m.id)}
                                  className="h-7 w-7 p-0"
                                >
                                  <FlaskConical className="h-4 w-4" />
                                </Button>
                              </TooltipTrigger>
                              <TooltipContent>
                                {t("models.probeMultimodal", "测试多模态")}
                              </TooltipContent>
                            </Tooltip>
                          )}
                          <Tooltip>
                            <TooltipTrigger asChild>
                              <Button
                                variant="ghost"
                                size="sm"
                                disabled={testingModelId === m.id}
                                onClick={() => handleTestModel(m.id)}
                                className="h-7 w-7 p-0"
                              >
                                <Network className="h-4 w-4" />
                              </Button>
                            </TooltipTrigger>
                            <TooltipContent>
                              {t("models.testConnection")}
                            </TooltipContent>
                          </Tooltip>
                          <Tooltip>
                            <TooltipTrigger asChild>
                              <Button
                                variant="ghost"
                                size="sm"
                                onClick={() =>
                                  setConfigOpenModelId(
                                    isConfigOpen ? null : m.id,
                                  )
                                }
                                className="h-7 w-7 p-0"
                              >
                                {isConfigOpen ? (
                                  <ChevronDown className="h-4 w-4" />
                                ) : (
                                  <Settings className="h-4 w-4" />
                                )}
                              </Button>
                            </TooltipTrigger>
                            <TooltipContent>
                              {t("models.modelConfigLabel", "模型配置")}
                            </TooltipContent>
                          </Tooltip>
                          {isDeletable && (
                            <Button
                              variant="ghost"
                              size="sm"
                              className="h-7 w-7 p-0 text-destructive hover:text-destructive"
                              onClick={() => handleRemoveModel(m.id, m.name)}
                            >
                              <Trash2 className="h-4 w-4" />
                            </Button>
                          )}
                        </div>
                      </div>
                      {isConfigOpen && (
                        <div
                          style={{
                            padding: "0 16px 12px",
                            borderBottom: isDark
                              ? "1px solid rgba(255,255,255,0.06)"
                              : "1px solid #f5f5f5",
                          }}
                        >
                          <ModelConfigEditor
                            providerId={provider.id}
                            model={m}
                            onSaved={onSaved}
                            onClose={() => setConfigOpenModelId(null)}
                            isDark={isDark}
                          />
                        </div>
                      )}
                    </div>
                  );
                })}
                {filteredModels.length > visibleCount && (
                  <div className={styles.modelListLoadMore}>
                    <Button
                      variant="link"
                      size="sm"
                      onClick={() => setVisibleCount((c) => c + PAGE_SIZE)}
                    >
                      {t("models.loadMore", {
                        count: Math.min(
                          PAGE_SIZE,
                          filteredModels.length - visibleCount,
                        ),
                        total: filteredModels.length,
                      })}
                    </Button>
                    <span className={styles.modelListCount}>
                      {visibleCount} / {filteredModels.length}
                    </span>
                  </div>
                )}
              </>
            )}
          </div>

          {isOpenRouter && (
            <OpenRouterFilterSection
              showFilters={showFilters}
              availableSeries={availableSeries}
              selectedSeries={selectedSeries}
              selectedInputModalities={selectedInputModalities}
              showFreeOnly={showFreeOnly}
              loadingFilters={loadingFilters}
              discoveredModels={discoveredModels}
              saving={saving}
              isDark={isDark}
              freeTagStyle={colors.free}
              onToggleFilters={() => setShowFilters(!showFilters)}
              onSelectedSeriesChange={setSelectedSeries}
              onSelectedInputModalitiesChange={setSelectedInputModalities}
              onShowFreeOnlyChange={setShowFreeOnly}
              onFetchModels={handleFetchModels}
              onAddModel={handleAddFilteredModel}
            />
          )}

          {/* Add model section */}
          {!isOpenRouter &&
            (adding ? (
              <div className={styles.modelAddForm}>
                <div className="flex flex-col gap-3">
                  <div>
                    <label className="text-sm font-medium mb-1 block">
                      {t("models.modelIdLabel")}
                    </label>
                    <div className="relative" ref={suggestionsRef}>
                      <Input
                        value={modelIdInput}
                        onChange={(e) => {
                          setModelIdInput(e.target.value);
                          setShowSuggestions(true);
                        }}
                        onFocus={() => setShowSuggestions(true)}
                        onBlur={() =>
                          setTimeout(() => setShowSuggestions(false), 150)
                        }
                        placeholder={t("models.modelIdPlaceholder")}
                      />
                      {showSuggestions && filteredSuggestions.length > 0 && (
                        <div className="absolute z-50 w-full mt-1 bg-popover border rounded-md shadow-md max-h-48 overflow-y-auto">
                          {filteredSuggestions.map((sug) => (
                            <div
                              key={sug.id}
                              className="px-3 py-2 text-sm cursor-pointer hover:bg-accent"
                              onMouseDown={() => {
                                setModelIdInput(sug.id);
                                setShowSuggestions(false);
                              }}
                            >
                              {sug.id}
                            </div>
                          ))}
                        </div>
                      )}
                      {showSuggestions &&
                        filteredSuggestions.length === 0 &&
                        modelIdInput && (
                          <div className="absolute z-50 w-full mt-1 bg-popover border rounded-md shadow-md px-3 py-2 text-sm text-muted-foreground">
                            {loadingDiscoveredModels
                              ? t("common.loading")
                              : t("models.modelDiscoveryUnavailableHint")}
                          </div>
                        )}
                    </div>
                  </div>
                  <div>
                    <label className="text-sm font-medium mb-1 block">
                      {t("models.modelNameLabel")}
                    </label>
                    <Input
                      value={modelNameInput}
                      onChange={(e) => setModelNameInput(e.target.value)}
                      placeholder={t("models.modelNamePlaceholder")}
                    />
                  </div>
                  <div className="flex gap-2 justify-end">
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={() => {
                        setAdding(false);
                        setModelIdInput("");
                        setModelNameInput("");
                      }}
                    >
                      {t("models.cancel")}
                    </Button>
                    <Button
                      size="sm"
                      disabled={!modelIdInput.trim() || saving}
                      onClick={handleAddModel}
                    >
                      {t("models.addModel")}
                    </Button>
                  </div>
                </div>
              </div>
            ) : (
              <div className={styles.modalActionRow}>
                {supportsAutoDiscover && (
                  <Button
                    variant="outline"
                    disabled={discoveringModels}
                    onClick={handleAutoDiscoverModels}
                    style={{ flex: 1 }}
                  >
                    <Search className="mr-2 h-4 w-4" />
                    {t("models.autoDiscoverModels")}
                  </Button>
                )}
                <Button
                  variant="outline"
                  onClick={() => setAdding(true)}
                  style={{ flex: 1 }}
                >
                  <Plus className="mr-2 h-4 w-4" />
                  {t("models.addModel")}
                </Button>
              </div>
            ))}
        </DialogContent>
      </Dialog>

      {/* Test failure confirm dialog */}
      <AlertDialog
        open={Boolean(testFailDialog?.open)}
        onOpenChange={(v) => {
          if (!v) setTestFailDialog(null);
        }}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>
              {t("models.testConnectionFailed")}
            </AlertDialogTitle>
            <AlertDialogDescription>
              {t("models.modelTestFailedConfirm", {
                message: testFailDialog?.message ?? "",
              })}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>{t("models.cancel")}</AlertDialogCancel>
            <AlertDialogAction
              onClick={async () => {
                if (!testFailDialog) return;
                const { id, name } = testFailDialog;
                setTestFailDialog(null);
                setSaving(true);
                try {
                  await doAddModel(id, name);
                } catch (error) {
                  const errMsg =
                    error instanceof Error
                      ? error.message
                      : t("models.modelAddFailed");
                  message.error(errMsg);
                } finally {
                  setSaving(false);
                }
              }}
            >
              {t("models.addModel")}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

      {/* Remove confirm dialog */}
      <AlertDialog
        open={Boolean(removeDialog?.open)}
        onOpenChange={(v) => {
          if (!v) setRemoveDialog(null);
        }}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>{t("models.removeModel")}</AlertDialogTitle>
            <AlertDialogDescription>
              {t("models.removeModelConfirm", {
                name: removeDialog?.name ?? "",
                provider: provider.name,
              })}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>{t("models.cancel")}</AlertDialogCancel>
            <AlertDialogAction
              className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
              onClick={confirmRemoveModel}
            >
              {t("common.delete")}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </>
  );
}
