import { useState, useEffect } from "react";
import {
  Button,
  Form,
  Input,
  Modal,
  Tag,
  message,
  Checkbox,
  Collapse,
} from "@agentscope-ai/design";
import {
  DeleteOutlined,
  PlusOutlined,
  ApiOutlined,
  SyncOutlined,
  FilterOutlined,
  ClearOutlined,
} from "@ant-design/icons";
import {
  SparkTextLine,
  SparkImageuploadLine,
  SparkAudiouploadLine,
  SparkVideouploadLine,
  SparkFilePdfLine,
  SparkTextImageLine,
} from "@agentscope-ai/icons";
import type { ProviderInfo, SeriesResponse } from "../../../../../api/types";
import api from "../../../../../api";
import { useTranslation } from "react-i18next";
import styles from "../../index.module.less";

interface RemoteModelManageModalProps {
  provider: ProviderInfo;
  open: boolean;
  onClose: () => void;
  onSaved: () => void | Promise<void>;
}

export function RemoteModelManageModal({
  provider,
  open,
  onClose,
  onSaved,
}: RemoteModelManageModalProps) {
  const { t } = useTranslation();
  const [adding, setAdding] = useState(false);
  const [saving, setSaving] = useState(false);
  const [discovering, setDiscovering] = useState(false);
  const [testingModelId, setTestingModelId] = useState<string | null>(null);
  const [form] = Form.useForm();

  // OpenRouter filter state
  const isOpenRouter = provider.id === "openrouter";
  const [showFilters, setShowFilters] = useState(false);
  const [availableSeries, setAvailableSeries] = useState<string[]>([]);
  const [discoveredModels, setDiscoveredModels] = useState<any[]>([]);
  const [selectedSeries, setSelectedSeries] = useState<string[]>([]);
  const [selectedInputModality, setSelectedInputModality] = useState<string | null>(null);
  const [loadingFilters, setLoadingFilters] = useState(false);

  // Enable discover for providers that support it
  // For local providers (ollama, llama.cpp, mlx) - check base_url
  // For built-in providers with frozen URL - check api_key
  const canDiscover = provider.is_local
    ? !!provider.base_url
    : !!provider.api_key;

  // Load available series for OpenRouter
  useEffect(() => {
    if (isOpenRouter && canDiscover) {
      api
        .getOpenRouterSeries()
        .then((res: SeriesResponse) => {
          setAvailableSeries(res.series || []);
        })
        .catch(() => {
          setAvailableSeries([]);
        });
    }
  }, [isOpenRouter, canDiscover]);

  // Fetch models with current filters
  const handleFetchModels = async () => {
    if (!isOpenRouter) return;

    setLoadingFilters(true);
    try {
      const filterBody: Record<string, any> = {};
      if (selectedSeries.length > 0) {
        filterBody.providers = selectedSeries;
      }
      if (selectedInputModality) {
        filterBody.input_modalities = [selectedInputModality];
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

  const handleAddFilteredModel = async (model: any) => {
    setSaving(true);
    try {
      await api.addModel(provider.id, { id: model.id, name: model.name });
      message.success(t("models.modelAdded", { name: model.name }));
      await onSaved();
      // Remove from discovered list
      setDiscoveredModels((prev) => prev.filter((m) => m.id !== model.id));
    } catch {
      message.error(t("models.modelAddFailed"));
    } finally {
      setSaving(false);
    }
  };

  // For custom providers ALL models are deletable.
  // For built-in providers only extra_models are deletable.
  const extraModelIds = new Set((provider.extra_models || []).map((m) => m.id));

  const doAddModel = async (id: string, name: string) => {
    await api.addModel(provider.id, { id, name });
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

      // Step 1: Test the model connection first
      setSaving(true);
      const testResult = await api.testModelConnection(provider.id, {
        model_id: id,
      });

      if (!testResult.success) {
        // Test failed – ask user whether to proceed anyway
        setSaving(false);
        Modal.confirm({
          title: t("models.testConnectionFailed"),
          content: t("models.modelTestFailedConfirm", {
            message: testResult.message || t("models.modelTestFailed"),
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
        message.success(result.message || t("models.testConnectionSuccess"));
      } else {
        message.warning(result.message || t("models.testConnectionFailed"));
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

  const handleClearAllModels = () => {
    const extraModels = provider.extra_models || [];
    if (extraModels.length === 0) return;

    Modal.confirm({
      title: t("models.clearAllModels"),
      content: t("models.clearAllModelsConfirm", {
        count: extraModels.length,
      }),
      okText: t("common.delete"),
      okButtonProps: { danger: true },
      cancelText: t("models.cancel"),
      onOk: async () => {
        setSaving(true);
        try {
          for (const model of extraModels) {
            await api.removeModel(provider.id, model.id);
          }
          message.success(t("models.allModelsCleared", { count: extraModels.length }));
          await onSaved();
        } catch (error) {
          const errMsg =
            error instanceof Error
              ? error.message
              : t("models.modelRemoveFailed");
          message.error(errMsg);
        } finally {
          setSaving(false);
        }
      },
    });
  };

  const handleClose = () => {
    setAdding(false);
    form.resetFields();
    onClose();
  };

  const handleDiscoverModels = async () => {
    setDiscovering(true);
    try {
      const result = await api.discoverModels(provider.id);
      if (!result.success) {
        message.warning(result.message || t("models.discoverModelsFailed"));
        return;
      }

      if (result.added_count > 0) {
        message.success(
          t("models.autoDiscoveredAndAdded", {
            count: result.models.length,
            added: result.added_count,
          }),
        );
        await onSaved();
      } else if (result.models.length > 0) {
        message.info(
          t("models.autoDiscoveredNoNew", { count: result.models.length }),
        );
        await onSaved();
      } else {
        message.info(result.message || t("models.noModels"));
      }
    } catch (error) {
      const errMsg =
        error instanceof Error
          ? error.message
          : t("models.discoverModelsFailed");
      message.error(errMsg);
    } finally {
      setDiscovering(false);
    }
  };

  useEffect(() => {
    // Do not auto-discover models when modal opens, as it may take some time and we don't want to block the UI.
    // Instead, users can click the "Discover Models" button to trigger discovery when needed.
  }, [open, canDiscover, provider.id, provider.models.length]);

  const all_models = [
    ...(provider.models ?? []),
    ...(provider.extra_models ?? []),
  ];

  return (
    <Modal
      title={t("models.manageModelsTitle", { provider: provider.name })}
      open={open}
      onCancel={handleClose}
      footer={
        <div className={styles.modalFooter}>
          <div className={styles.modalFooterRight}>
            <Button onClick={handleClose}>{t("models.cancel")}</Button>
          </div>
        </div>
      }
      width={560}
      destroyOnHidden
    >
      {/* Model list - collapsible */}
      <Collapse
        defaultActiveKey={[]}
        ghost
        items={[
          {
            key: "models",
            label: (
              <span style={{ fontWeight: 500 }}>
                {t("models.modelList")} ({all_models.length})
              </span>
            ),
            extra: (provider.extra_models?.length ?? 0) > 0 ? (
              <Button
                type="text"
                size="small"
                danger
                icon={<ClearOutlined />}
                onClick={(e) => {
                  e.stopPropagation();
                  handleClearAllModels();
                }}
                loading={saving}
              >
                {t("models.clearAll")}
              </Button>
            ) : null,
            children: (
              <>
                {all_models.length === 0 ? (
                  <div className={styles.modelListEmpty}>{t("models.noModels")}</div>
                ) : (
                  all_models.map((m) => {
                    const isDeletable = extraModelIds.has(m.id);
                    // Check if it's an extended model (has input_modalities)
                    const hasExtendedInfo = (m as any).input_modalities;
                    return (
                      <div key={m.id} className={styles.modelListItem}>
                        <div className={styles.modelListItemInfo}>
                          <span className={styles.modelListItemName}>{m.name}</span>
                          <span className={styles.modelListItemId}>
                            {m.id}
                            {/* Show modalities and price for extended models */}
                            {hasExtendedInfo && (
                              <span style={{ marginLeft: 8, fontSize: 11, color: "#666", display: "flex", alignItems: "center", gap: 2 }}>
                                {(m as any).input_modalities?.includes("text") && <SparkTextLine style={{ fontSize: 12 }} />}
                                {(m as any).input_modalities?.includes("image") && <SparkImageuploadLine style={{ fontSize: 12 }} />}
                                {(m as any).input_modalities?.includes("audio") && <SparkAudiouploadLine style={{ fontSize: 12 }} />}
                                {(m as any).input_modalities?.includes("video") && <SparkVideouploadLine style={{ fontSize: 12 }} />}
                                {(m as any).input_modalities?.includes("file") && <SparkFilePdfLine style={{ fontSize: 12 }} />}
                                {(m as any).output_modalities?.includes("image") && <SparkTextImageLine style={{ fontSize: 12, color: "purple" }} />}
                                {((m as any).pricing?.prompt) && (
                                  <span style={{ color: "green", marginLeft: 4 }}>
                                    ${((m as any).pricing.prompt * 1_000_000).toFixed(2)}/1M in
                                    {((m as any).pricing.completion) && (
                                      <span> · ${((m as any).pricing.completion * 1_000_000).toFixed(2)}/1M out</span>
                                    )}
                                  </span>
                                )}
                              </span>
                            )}
                          </span>
                        </div>
                        <div className={styles.modelListItemActions}>
                          {isDeletable ? (
                            <>
                              <Tag
                                color="blue"
                                style={{ fontSize: 11, marginRight: 4 }}
                              >
                                {t("models.userAdded")}
                              </Tag>
                              <Button
                                type="text"
                                size="small"
                                icon={<ApiOutlined />}
                                onClick={() => handleTestModel(m.id)}
                                loading={testingModelId === m.id}
                                style={{ marginRight: 4 }}
                              >
                                {t("models.testConnection")}
                              </Button>
                              <Button
                                type="text"
                                size="small"
                                danger
                                icon={<DeleteOutlined />}
                                onClick={() => handleRemoveModel(m.id, m.name)}
                              />
                            </>
                          ) : (
                            <>
                              <Tag
                                color="green"
                                style={{ fontSize: 11, marginRight: 4 }}
                              >
                                {t("models.builtin")}
                              </Tag>
                              <Button
                                type="text"
                                size="small"
                                icon={<ApiOutlined />}
                                onClick={() => handleTestModel(m.id)}
                                loading={testingModelId === m.id}
                              >
                                {t("models.testConnection")}
                              </Button>
                            </>
                          )}
                        </div>
                      </div>
                    );
                  })
                )}
              </>
            ),
          },
        ]}
      />

      {/* OpenRouter Filter Section */}
      {isOpenRouter && (
        <div style={{ marginTop: 16, marginBottom: 16 }}>
          <Button
            type={showFilters ? "primary" : "default"}
            icon={<FilterOutlined />}
            onClick={() => setShowFilters(!showFilters)}
            style={{ width: "100%", marginBottom: showFilters ? 8 : 0 }}
          >
            {t("models.filterModels") || "Filter Models"}
          </Button>

          {showFilters && (
            <div
              style={{
                padding: 12,
                background: "#f5f5f5",
                borderRadius: 8,
              }}
            >
              {/* Provider/Series Filter */}
              <div style={{ marginBottom: 12 }}>
                <div style={{ marginBottom: 4, fontWeight: 500 }}>
                  {t("models.filterByProvider") || "Provider:"}
                </div>
                <Checkbox.Group
                  options={availableSeries.map((s) => ({ label: s, value: s }))}
                  value={selectedSeries}
                  onChange={(vals) => setSelectedSeries(vals as string[])}
                  style={{ display: "flex", flexWrap: "wrap", gap: 8 }}
                />
              </div>

              {/* Input Modality Filter */}
              <div style={{ marginBottom: 12 }}>
                <div style={{ marginBottom: 4, fontWeight: 500 }}>
                  {t("models.filterByModality") || "Input Modality:"}
                </div>
                <Checkbox.Group
                  options={[
                    { label: <><SparkImageuploadLine /> Vision (image)</>, value: "image" },
                    { label: <><SparkAudiouploadLine /> Audio</>, value: "audio" },
                    { label: <><SparkVideouploadLine /> Video</>, value: "video" },
                    { label: <><SparkFilePdfLine /> File</>, value: "file" },
                    { label: <><SparkTextLine /> Text only</>, value: "text" },
                  ]}
                  value={selectedInputModality ? [selectedInputModality] : []}
                  onChange={(vals) =>
                    setSelectedInputModality(
                      vals.length > 0 ? (vals[0] as string) : null,
                    )
                  }
                  style={{ display: "flex", flexWrap: "wrap", gap: 8 }}
                />
              </div>

              {/* Fetch Button */}
              <Button
                type="primary"
                onClick={handleFetchModels}
                loading={loadingFilters}
                disabled={!canDiscover}
                style={{ width: "100%" }}
              >
                {t("models.getModels") || "Get Models"}
              </Button>

              {/* Discovered Models List */}
              {discoveredModels.length > 0 && (
                <div style={{ marginTop: 12, maxHeight: 200, overflowY: "auto" }}>
                  <div style={{ fontWeight: 500, marginBottom: 4 }}>
                    {t("models.discovered") || "Available Models:"}
                  </div>
                  {discoveredModels.map((model: any) => (
                    <div
                      key={model.id}
                      style={{
                        display: "flex",
                        justifyContent: "space-between",
                        alignItems: "center",
                        padding: "4px 8px",
                        background: "white",
                        marginBottom: 4,
                        borderRadius: 4,
                      }}
                    >
                      <div>
                        <div style={{ fontWeight: 500 }}>{model.name}</div>
                        <div style={{ fontSize: 11, color: "#666", display: "flex", alignItems: "center", gap: 4 }}>
                          <span>{model.provider}</span>
                          {/* Input modalities icons */}
                          {model.input_modalities?.includes("text") && (
                            <SparkTextLine style={{ fontSize: 12 }} />
                          )}
                          {model.input_modalities?.includes("image") && (
                            <SparkImageuploadLine style={{ fontSize: 12 }} />
                          )}
                          {model.input_modalities?.includes("audio") && (
                            <SparkAudiouploadLine style={{ fontSize: 12 }} />
                          )}
                          {model.input_modalities?.includes("video") && (
                            <SparkVideouploadLine style={{ fontSize: 12 }} />
                          )}
                          {model.input_modalities?.includes("file") && (
                            <SparkFilePdfLine style={{ fontSize: 12 }} />
                          )}
                          {model.output_modalities?.includes("image") && (
                            <SparkTextImageLine style={{ fontSize: 12, color: "purple" }} />
                          )}
                          {/* Price */}
                          {model.pricing?.prompt && (
                            <span style={{ color: "green", marginLeft: 4 }}>
                              ${(parseFloat(model.pricing.prompt) * 1_000_000).toFixed(2)}/1M in
                              {model.pricing?.completion && (
                                <span> · ${(parseFloat(model.pricing.completion) * 1_000_000).toFixed(2)}/1M out</span>
                              )}
                            </span>
                          )}
                        </div>
                      </div>
                      <Button
                        size="small"
                        type="primary"
                        onClick={() => handleAddFilteredModel(model)}
                        disabled={saving}
                      >
                        {t("models.add") || "Add"}
                      </Button>
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}
        </div>
      )}

      {/* Add model section */}
      {adding ? (
        <div className={styles.modelAddForm}>
          <Form form={form} layout="vertical" style={{ marginBottom: 0 }}>
            <Form.Item
              name="id"
              label={t("models.modelIdLabel")}
              rules={[{ required: true, message: t("models.modelIdLabel") }]}
              style={{ marginBottom: 12 }}
            >
              <Input placeholder={t("models.modelIdPlaceholder")} />
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
        <div style={{ display: "flex", gap: 8, marginTop: 12 }}>
          <Button
            icon={<SyncOutlined />}
            onClick={handleDiscoverModels}
            loading={discovering}
            disabled={!canDiscover}
            style={{ flex: 1 }}
          >
            {t("models.discoverModels")}
          </Button>
          <Button
            type="dashed"
            icon={<PlusOutlined />}
            onClick={() => setAdding(true)}
            style={{ flex: 1 }}
          >
            {t("models.addModel")}
          </Button>
        </div>
      )}
    </Modal>
  );
}
