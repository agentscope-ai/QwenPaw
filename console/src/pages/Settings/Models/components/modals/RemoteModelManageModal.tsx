import { useState, useEffect, useMemo, useDeferredValue, useRef } from "react";
import {
  Button,
  Form,
  Input,
  Modal,
  Tag,
  Tooltip,
} from "@agentscope-ai/design";
import { AutoComplete } from "antd";
import {
  ChevronDown,
  CloudCog,
  Database,
  FlaskConical,
  Gift,
  PlugZap,
  Plus,
  Search,
  Settings,
  Trash2,
  User,
} from "lucide-react";
import type {
  ProviderInfo,
  SeriesResponse,
  ExtendedModelInfo,
} from "../../../../../api/types";

import api from "../../../../../api";
import { useTranslation } from "react-i18next";
import { useTheme } from "../../../../../contexts/ThemeContext";
import { useAppMessage } from "../../../../../hooks/useAppMessage";
import { CapabilityTags, tagColors } from "./ModelCapabilityTags";
import { ModelConfigEditor } from "./ModelConfigEditor";
import {
  getLocalizedTestConnectionMessage,
  getTestConnectionFailureDetail,
} from "./testConnectionMessage";
import { OpenRouterFilterSection } from "./OpenRouterFilterSection";
import styles from "../../index.module.less";

interface RemoteModelManageModalProps {
  provider: ProviderInfo;
  open: boolean;
  onClose: () => void;
  onSaved: () => void | Promise<void>;
  onProviderUpdated?: (provider: ProviderInfo) => void;
}

export function RemoteModelManageModal({
  provider,
  open,
  onClose,
  onSaved,
  onProviderUpdated,
}: RemoteModelManageModalProps) {
  const { t } = useTranslation();
  const { isDark } = useTheme();
  const darkBtnStyle = isDark ? { color: "rgba(255,255,255,0.65)" } : undefined;
  const { message } = useAppMessage();
  const supportsAutoDiscover = provider.support_model_discovery;
  const [adding, setAdding] = useState(false);
  const [saving, setSaving] = useState(false);
  const [bulkAdding, setBulkAdding] = useState(false);
  const [discoveringModels, setDiscoveringModels] = useState(false);
  const [previewDiscovering, setPreviewDiscovering] = useState(false);
  const [testingModelId, setTestingModelId] = useState<string | null>(null);
  const [probingModelId, setProbingModelId] = useState<string | null>(null);
  const [configOpenModelId, setConfigOpenModelId] = useState<string | null>(
    null,
  );
  const [modelSearchQuery, setModelSearchQuery] = useState("");
  const [form] = Form.useForm();
  // OpenRouter filter state
  const isOpenRouter = provider.id === "openrouter";
  const [showFilters, setShowFilters] = useState(false);
  const [availableSeries, setAvailableSeries] = useState<string[]>([]);
  const [discoveredModels, setDiscoveredModels] = useState<ExtendedModelInfo[]>(
    () => (provider.discovered_models ?? []) as unknown as ExtendedModelInfo[],
  );
  const [selectedSeries, setSelectedSeries] = useState<string[]>([]);
  const [selectedInputModalities, setSelectedInputModalities] = useState<
    string[]
  >([]);
  const [showFreeOnly, setShowFreeOnly] = useState(false);
  const [loadingFilters, setLoadingFilters] = useState(false);

  const PAGE_SIZE = 30;
  const [visibleCount, setVisibleCount] = useState(PAGE_SIZE);
  const previewAttemptedProviderRef = useRef<string | null>(null);

  // For custom providers ALL models are deletable.
  // For built-in providers only extra_models are deletable.
  const extraModelIds = new Set((provider.extra_models || []).map((m) => m.id));

  const doAddModel = async (id: string, name: string) => {
    const candidate = discoveredModels.find((model) => model.id === id);
    await api.addModel(provider.id, {
      id,
      name,
      is_free: candidate?.is_free,
      supports_multimodal: candidate?.supports_multimodal,
      supports_image: candidate?.supports_image,
      supports_video: candidate?.supports_video,
      probe_source: candidate?.probe_source,
    });
    message.success(t("models.modelAdded", { name }));
    form.resetFields();
    setAdding(false);
    onSaved();
  };

  const handleAddModel = async () => {
    try {
      const values = await form.validateFields();
      const id = values.id.trim();
      const name = values.name?.trim() || id;
      const modelAlreadyExists = [
        ...(provider.models ?? []),
        ...(provider.extra_models ?? []),
      ].some((model) => model.id.trim() === id);

      if (modelAlreadyExists) {
        message.warning(t("models.modelAlreadyExists", { id }));
        return;
      }

      // Step 1: Test the model connection first
      setSaving(true);
      const testResult = await api.testModelConnection(provider.id, {
        model_id: id,
      });

      if (!testResult.success) {
        // Test failed – ask user whether to proceed anyway
        setSaving(false);
        const failureDetail =
          getTestConnectionFailureDetail(testResult.message) ||
          t("models.modelTestFailed");
        const cannotAddByStatus = [
          "permission_denied",
          "model_not_found",
          "incompatible_api",
        ].includes(testResult.status ?? "");
        const cannotAdd =
          cannotAddByStatus ||
          /product is not activated|product.*not enabled|model.*not found|unsupported model/i.test(
            failureDetail,
          );
        if (cannotAdd) {
          message.error(failureDetail);
          return;
        }
        Modal.confirm({
          title: t("models.testConnectionFailed"),
          content: t("models.modelTestFailedConfirm", {
            message: failureDetail,
          }),
          okText: t("models.addModel"),
          cancelText: t("models.cancel"),
          onOk: async () => {
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
          },
        });
        return;
      }

      // Step 2: If test passed, add the model
      await doAddModel(id, name);
    } catch (error) {
      if (error && typeof error === "object" && "errorFields" in error) return;
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
          t("models.probeSupported", {
            types: parts.join(", "),
          }),
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
    Modal.confirm({
      title: t("models.removeModel"),
      content: t("models.removeModelConfirm", {
        name: modelName,
        provider: provider.name,
      }),
      okText: t("common.delete"),
      okButtonProps: { danger: true },
      cancelText: t("models.cancel"),
      onOk: async () => {
        try {
          await api.removeModel(provider.id, modelId);
          message.success(t("models.modelRemoved", { name: modelName }));
          await onSaved();
        } catch (error) {
          const errMsg =
            error instanceof Error
              ? error.message
              : t("models.modelRemoveFailed");
          message.error(errMsg);
        }
      },
    });
  };

  const handleClose = () => {
    setAdding(false);
    setConfigOpenModelId(null);
    setModelSearchQuery("");
    setVisibleCount(PAGE_SIZE);
    form.resetFields();
    onClose();
  };

  const openAddModel = () => {
    setAdding(true);
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

  // Fetch models with current filters
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
      await onSaved();

      if (!result.success) {
        message.error(result.message || t("models.autoDiscoverModelsFailed"));
        return;
      }

      if (result.discovered_count > 0) {
        message.success(
          t("models.autoDiscoverModelsSuccess", {
            count: result.discovered_count,
          }),
        );
        return;
      }

      message.info(
        result.message ||
          t("models.autoDiscoverModelsNoNew", {
            count: result.models.length,
          }),
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
    setDiscoveredModels(
      (provider.discovered_models ?? []) as unknown as ExtendedModelInfo[],
    );
  }, [provider.discovered_models]);

  useEffect(() => {
    if (
      !adding ||
      isOpenRouter ||
      !supportsAutoDiscover ||
      discoveredModels.length > 0 ||
      previewAttemptedProviderRef.current === provider.id
    ) {
      return;
    }

    previewAttemptedProviderRef.current = provider.id;
    setPreviewDiscovering(true);
    api
      .discoverModels(provider.id, undefined, false)
      .then((result) => {
        if (result.success) {
          setDiscoveredModels(result.models as ExtendedModelInfo[]);
        }
      })
      .catch(() => {})
      .finally(() => setPreviewDiscovering(false));
  }, [
    adding,
    discoveredModels.length,
    isOpenRouter,
    provider.id,
    supportsAutoDiscover,
  ]);

  useEffect(() => {
    if (!isOpenRouter || !adding) return;
    setAdding(false);
    form.resetFields();
  }, [adding, form, isOpenRouter]);

  const deferredSearchQuery = useDeferredValue(modelSearchQuery);

  const configuredModelIds = useMemo(
    () =>
      new Set(
        [...(provider.models ?? []), ...(provider.extra_models ?? [])].map(
          (model) => model.id.trim(),
        ),
      ),
    [provider.models, provider.extra_models],
  );

  const addableDiscoveredModels = useMemo(() => {
    const hidden = new Set(provider.hidden_model_ids ?? []);
    return discoveredModels.filter(
      (model) =>
        !configuredModelIds.has(model.id.trim()) &&
        !hidden.has(model.id) &&
        !["permission_denied", "model_not_found", "incompatible_api"].includes(
          model.availability_status ?? "unverified",
        ),
    );
  }, [configuredModelIds, discoveredModels, provider.hidden_model_ids]);

  const handleAddAllDiscoveredModels = async () => {
    if (addableDiscoveredModels.length === 0) return;
    setBulkAdding(true);
    try {
      const results = await Promise.allSettled(
        addableDiscoveredModels.map((model) =>
          api.addModel(provider.id, {
            id: model.id,
            name: model.name,
            is_free: model.is_free,
            supports_multimodal: model.supports_multimodal,
            supports_image: model.supports_image,
            supports_video: model.supports_video,
            probe_source: model.probe_source,
          }),
        ),
      );
      const addedIds = new Set(
        addableDiscoveredModels
          .filter((_, index) => results[index].status === "fulfilled")
          .map((model) => model.id),
      );
      const failedCount = results.length - addedIds.size;
      setDiscoveredModels((current) =>
        current.filter((model) => !addedIds.has(model.id)),
      );
      if (addedIds.size > 0) {
        await onSaved();
        message.success(
          t("models.discoveredModelsAdded", {
            count: addedIds.size,
            defaultValue: "Added {{count}} discovered models",
          }),
        );
      }
      if (failedCount > 0) {
        message.error(
          t("models.discoveredModelsAddFailed", {
            count: failedCount,
            defaultValue: "Failed to add {{count}} models",
          }),
        );
      }
    } finally {
      setBulkAdding(false);
    }
  };

  const discoveredModelOptions = useMemo(
    () =>
      discoveredModels.map((model) => {
        const originLabels = {
          api: t("models.discoveryOriginApi", "API detected"),
          catalog: t("models.discoveryOriginCatalog", "Official catalog"),
          both: t("models.discoveryOriginBoth", "API + catalog"),
        };
        const statusLabels = {
          available: t("models.availabilityAvailable", "Available"),
          permission_denied: t(
            "models.availabilityPermissionDenied",
            "No permission",
          ),
          model_not_found: t("models.availabilityNotFound", "Not found"),
          incompatible_api: t(
            "models.availabilityIncompatible",
            "Not chat compatible",
          ),
          rate_limited: t("models.availabilityRateLimited", "Rate limited"),
          transient_error: t(
            "models.availabilityTransientError",
            "Temporarily unavailable",
          ),
          unverified: t("models.availabilityUnverified", "Unverified"),
        };
        const origin = model.discovery_origin
          ? originLabels[model.discovery_origin]
          : originLabels.api;
        const status = statusLabels[model.availability_status ?? "unverified"];
        const configured = configuredModelIds.has(model.id.trim());
        const configuredLabel = configured
          ? ` · ${t("models.modelAlreadyConfigured", "Configured")}`
          : "";
        return {
          value: model.id,
          label: `${model.id} · ${origin} · ${status}${configuredLabel}`,
          disabled: configured,
        };
      }),
    [configuredModelIds, discoveredModels, t],
  );

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

  return (
    <Modal
      title={t("models.manageModelsTitle", { provider: provider.name })}
      open={open}
      onCancel={handleClose}
      footer={null}
      width={800}
      className={styles.modelManageModal}
      destroyOnHidden
    >
      <Input
        placeholder={t("models.searchModelPlaceholder", "搜索模型...")}
        value={modelSearchQuery}
        onChange={(e) => setModelSearchQuery(e.target.value)}
        prefix={<Search size={16} />}
        allowClear
      />

      {supportsAutoDiscover && (
        <div style={{ marginTop: 8, color: "rgba(127,127,127,0.9)" }}>
          <CloudCog
            size={15}
            style={{ marginRight: 6, verticalAlign: "-3px" }}
          />
          {provider.models_syncing
            ? t("models.modelsSyncing", {
                defaultValue: "Discovering model candidates...",
              })
            : provider.models_last_synced_at
            ? t("models.modelsLastSynced", {
                time: new Date(provider.models_last_synced_at).toLocaleString(),
                defaultValue: "Last synced: {{time}}",
              })
            : t("models.modelsNeverSynced", {
                defaultValue: "Models have not been synced yet",
              })}
          {provider.models_last_sync_error && (
            <Tooltip title={provider.models_last_sync_error}>
              <Tag color="error" style={{ marginLeft: 8 }}>
                {t("models.modelsSyncFailed", {
                  defaultValue: "Last sync failed",
                })}
              </Tag>
            </Tooltip>
          )}
        </div>
      )}

      {/* Model list */}
      <div className={styles.modelList}>
        {filteredModels.length === 0 ? (
          <div className={styles.modelListEmpty}>
            <div>{t("models.noModels")}</div>
            {discoveredModels.length > 0 && !isOpenRouter && (
              <>
                <div style={{ marginTop: 8 }}>
                  {t("models.discoveredModelsReady", {
                    count: discoveredModels.length,
                  })}
                </div>
                <Button
                  size="small"
                  type="primary"
                  style={{ marginTop: 10 }}
                  loading={bulkAdding}
                  disabled={addableDiscoveredModels.length === 0}
                  onClick={handleAddAllDiscoveredModels}
                >
                  {t("models.addAllDiscoveredModels", {
                    count: addableDiscoveredModels.length,
                    defaultValue: "Add all available ({{count}})",
                  })}
                </Button>
              </>
            )}
          </div>
        ) : (
          <>
            {filteredModels.slice(0, visibleCount).map((m) => {
              const isDeletable = provider.is_custom || extraModelIds.has(m.id);
              const isConfigOpen = configOpenModelId === m.id;
              return (
                <div key={m.id}>
                  <div className={styles.modelListItem}>
                    <div className={styles.modelListItemInfo}>
                      <span className={styles.modelListItemName}>{m.name}</span>
                      <span className={styles.modelListItemId}>{m.id}</span>
                    </div>
                    <div className={styles.modelListItemActions}>
                      <CapabilityTags model={m} isDark={isDark} />
                      {m.is_free && (
                        <Tag
                          style={{
                            fontSize: 11,
                            marginRight: 4,
                            ...colors.free,
                          }}
                        >
                          <Gift
                            size={11}
                            style={{ marginRight: 3, verticalAlign: "-2px" }}
                          />
                          {t("models.free")}
                        </Tag>
                      )}
                      <Tag
                        style={{
                          fontSize: 11,
                          marginRight: 4,
                          ...(isDeletable ? colors.userAdded : colors.builtin),
                        }}
                      >
                        {isDeletable ? (
                          <User
                            size={11}
                            style={{ marginRight: 3, verticalAlign: "-2px" }}
                          />
                        ) : (
                          <Database
                            size={11}
                            style={{ marginRight: 3, verticalAlign: "-2px" }}
                          />
                        )}
                        {t(
                          isDeletable
                            ? "models.userAdded"
                            : m.source === "discovered"
                            ? "models.discovered"
                            : "models.builtin",
                        )}
                      </Tag>
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
                      <Tooltip
                        title={t("models.probeMultimodal", "测试多模态")}
                      >
                        <Button
                          type="text"
                          size="small"
                          icon={<FlaskConical size={16} />}
                          onClick={() => handleProbeMultimodal(m.id)}
                          loading={probingModelId === m.id}
                          style={darkBtnStyle}
                        />
                      </Tooltip>
                      <Tooltip title={t("models.testConnection")}>
                        <Button
                          type="text"
                          size="small"
                          icon={<PlugZap size={16} />}
                          onClick={() => handleTestModel(m.id)}
                          loading={testingModelId === m.id}
                          style={darkBtnStyle}
                        />
                      </Tooltip>
                      <Tooltip title={t("models.modelConfigLabel", "模型配置")}>
                        <Button
                          type="text"
                          size="small"
                          icon={
                            isConfigOpen ? (
                              <ChevronDown size={16} />
                            ) : (
                              <Settings size={16} />
                            )
                          }
                          onClick={() =>
                            setConfigOpenModelId(isConfigOpen ? null : m.id)
                          }
                          style={darkBtnStyle}
                        />
                      </Tooltip>
                      {isDeletable && (
                        <Button
                          type="text"
                          size="small"
                          danger
                          icon={<Trash2 size={16} />}
                          onClick={() => handleRemoveModel(m.id, m.name)}
                        />
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
                        onProviderUpdated={onProviderUpdated}
                        onClose={() => setConfigOpenModelId(null)}
                        isDark={isDark}
                        chatModel={provider.chat_model}
                        thinkingParamStyle={
                          extraModelIds.has(m.id)
                            ? undefined
                            : m.thinking_param_style ??
                              provider.thinking_param_style
                        }
                        reasoningEffortOptions={
                          m.reasoning_effort_options ??
                          provider.reasoning_effort_options
                        }
                        thinkingBudgetRange={
                          (m.thinking_budget_range ??
                            provider.thinking_budget_range) as
                            | [number, number]
                            | undefined
                        }
                      />
                    </div>
                  )}
                </div>
              );
            })}
            {filteredModels.length > visibleCount && (
              <div className={styles.modelListLoadMore}>
                <Button
                  type="link"
                  size="small"
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
            <Form form={form} layout="vertical" style={{ marginBottom: 0 }}>
              <Form.Item
                name="id"
                label={t("models.modelIdLabel")}
                rules={[{ required: true, message: t("models.modelIdLabel") }]}
                style={{ marginBottom: 12 }}
              >
                <AutoComplete
                  placeholder={t("models.modelIdPlaceholder")}
                  options={discoveredModelOptions}
                  filterOption={(
                    inputValue: string,
                    option?: { value?: string },
                  ) =>
                    option?.value
                      ?.toLowerCase()
                      .includes(inputValue.toLowerCase()) ?? false
                  }
                  notFoundContent={
                    previewDiscovering
                      ? t("common.loading")
                      : t("models.modelDiscoveryUnavailableHint")
                  }
                >
                  <Input />
                </AutoComplete>
              </Form.Item>
              <Form.Item
                name="name"
                label={t("models.modelNameLabel")}
                style={{ marginBottom: 12 }}
              >
                <Input placeholder={t("models.modelNamePlaceholder")} />
              </Form.Item>
              <div
                style={{ display: "flex", gap: 8, justifyContent: "flex-end" }}
              >
                <Button
                  size="small"
                  onClick={() => {
                    setAdding(false);
                    form.resetFields();
                  }}
                >
                  {t("models.cancel")}
                </Button>
                <Button
                  type="primary"
                  size="small"
                  loading={saving}
                  onClick={handleAddModel}
                >
                  {t("models.addModel")}
                </Button>
              </div>
            </Form>
          </div>
        ) : (
          <div className={styles.modalActionRow}>
            {supportsAutoDiscover && (
              <Button
                icon={<Search size={16} />}
                loading={discoveringModels}
                onClick={handleAutoDiscoverModels}
                style={{ flex: 1 }}
              >
                {t("models.autoDiscoverModels")}
              </Button>
            )}
            <Button
              type="dashed"
              icon={<Plus size={16} />}
              onClick={openAddModel}
              style={{ flex: 1 }}
            >
              {t("models.addModel")}
            </Button>
          </div>
        ))}
    </Modal>
  );
}
