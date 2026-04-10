import { useState, useEffect, useMemo, useCallback } from "react";
import {
  Button,
  Form,
  Input,
  Modal,
  Tag,
  Checkbox,
  Tooltip,
} from "@agentscope-ai/design";
import { AutoComplete } from "antd";
import {
  DeleteOutlined,
  PlusOutlined,
  ApiOutlined,
  EyeOutlined,
  FilterOutlined,
  SettingOutlined,
  DownOutlined,
  SearchOutlined,
  ExperimentOutlined,
  AppstoreOutlined,
  VideoCameraOutlined,
  FileTextOutlined,
  QuestionCircleOutlined,
  DatabaseOutlined,
  UserOutlined,
} from "@ant-design/icons";
import {
  SparkTextLine,
  SparkImageuploadLine,
  SparkAudiouploadLine,
  SparkVideouploadLine,
  SparkFilePdfLine,
  SparkTextImageLine,
} from "@agentscope-ai/icons";
import type {
  ProviderInfo,
  SeriesResponse,
  ModelInfo,
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
import styles from "../../index.module.less";

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
    setDirty(false);
  }, [initialText]);

  const handleChange = useCallback(
    (val: string) => {
      setText(val);
      setDirty(val !== initialText);
    },
    [initialText],
  );

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

  return (
    <div style={{ padding: "8px 0 4px" }}>
      <div
        style={{
          fontSize: 12,
          color: isDark ? "rgba(255,255,255,0.45)" : "#888",
          marginBottom: 4,
        }}
      >
        {t("models.modelGenerateConfigHint")}
      </div>
      <JsonConfigEditor
        value={text}
        onChange={handleChange}
        placeholder={`Example:\n{\n  "extra_body": {\n    "enable_thinking": false\n  },\n  "max_tokens": 2048\n}`}
      />
      <div
        style={{
          display: "flex",
          justifyContent: "flex-end",
          marginTop: 8,
          gap: 8,
        }}
      >
        <Button
          type="primary"
          size="small"
          loading={saving}
          disabled={!dirty}
          onClick={handleSave}
        >
          {t("models.save")}
        </Button>
      </div>
    </div>
  );
}

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
      <Tag style={{ fontSize: 11, marginRight: 4, ...c.multimodal }}>
        <AppstoreOutlined style={{ fontSize: 10, marginRight: 3 }} />
        {t("models.tagMultimodal", "多模态")}
      </Tag>
    );
  }
  if (model.supports_image) {
    return (
      <Tag style={{ fontSize: 11, marginRight: 4, ...c.vision }}>
        <EyeOutlined style={{ fontSize: 10, marginRight: 3 }} />
        {t("models.tagVision", "视觉")}
      </Tag>
    );
  }
  if (model.supports_video) {
    return (
      <Tag style={{ fontSize: 11, marginRight: 4, ...c.video }}>
        <VideoCameraOutlined style={{ fontSize: 10, marginRight: 3 }} />
        {t("models.tagVideo", "视频")}
      </Tag>
    );
  }
  if (model.supports_multimodal === false) {
    return (
      <Tag style={{ fontSize: 11, marginRight: 4, ...c.text }}>
        <FileTextOutlined style={{ fontSize: 10, marginRight: 3 }} />
        {t("models.tagText", "文本")}
      </Tag>
    );
  }
  return (
    <Tag style={{ fontSize: 11, marginRight: 4, ...c.notProbed }}>
      <QuestionCircleOutlined style={{ fontSize: 10, marginRight: 3 }} />
      {t("models.tagNotProbed", "未检测")}
    </Tag>
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
  const darkBtnStyle = isDark ? { color: "rgba(255,255,255,0.65)" } : undefined;
  const { message } = useAppMessage();
  const [adding, setAdding] = useState(false);
  const [saving, setSaving] = useState(false);
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
  const [discoveredModels, setDiscoveredModels] = useState<any[]>([]);
  const [selectedSeries, setSelectedSeries] = useState<string[]>([]);
  const [selectedInputModality, setSelectedInputModality] = useState<
    string | null
  >(null);
  const [loadingFilters, setLoadingFilters] = useState(false);

  const [loadingDiscoveredModels, setLoadingDiscoveredModels] = useState(false);

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
        const failureDetail =
          getTestConnectionFailureDetail(testResult.message) ||
          t("models.modelTestFailed");
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
            defaultValue: t("models.probeSupported", {
              types: parts.join(", "),
            }),
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
    form.resetFields();
    onClose();
  };

  // Load available series for OpenRouter
  useEffect(() => {
    if (isOpenRouter) {
      api
        .getOpenRouterSeries()
        .then((res: SeriesResponse) => {
          setAvailableSeries(res.series || []);
        })
        .catch(() => {
          setAvailableSeries([]);
        });
    }
  }, [isOpenRouter]);

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
      setDiscoveredModels((prev) => prev.filter((m) => m.id !== model.id));
    } catch {
      message.error(t("models.modelAddFailed"));
    } finally {
      setSaving(false);
    }
  };

  const all_models = [
    ...(provider.models ?? []),
    ...(provider.extra_models ?? []),
  ];

  const filteredModels = useMemo(() => {
    const q = modelSearchQuery.trim().toLowerCase();
    if (!q) return all_models;
    return all_models.filter(
      (m) => m.name.toLowerCase().includes(q) || m.id.toLowerCase().includes(q),
    );
  }, [all_models, modelSearchQuery]);

  return (
    <Modal
      title={t("models.manageModelsTitle", { provider: provider.name })}
      open={open}
      onCancel={handleClose}
      footer={null}
      width={720}
      destroyOnHidden
    >
      <Input
        placeholder={t("models.searchModelPlaceholder", "搜索模型...")}
        value={modelSearchQuery}
        onChange={(e) => setModelSearchQuery(e.target.value)}
        prefix={<SearchOutlined />}
        allowClear
      />

      {/* Model list */}
      <div className={styles.modelList}>
        {filteredModels.length === 0 ? (
          <div className={styles.modelListEmpty}>{t("models.noModels")}</div>
        ) : (
          filteredModels.map((m) => {
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
                    <Tag
                      style={{
                        fontSize: 11,
                        marginRight: 4,
                        ...(isDeletable
                          ? tagColors(isDark).userAdded
                          : tagColors(isDark).builtin),
                      }}
                    >
                      {isDeletable ? (
                        <UserOutlined
                          style={{ fontSize: 10, marginRight: 3 }}
                        />
                      ) : (
                        <DatabaseOutlined
                          style={{ fontSize: 10, marginRight: 3 }}
                        />
                      )}
                      {t(isDeletable ? "models.userAdded" : "models.builtin")}
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
                    <Tooltip title={t("models.probeMultimodal", "测试多模态")}>
                      <Button
                        type="text"
                        size="small"
                        icon={<ExperimentOutlined />}
                        onClick={() => handleProbeMultimodal(m.id)}
                        loading={probingModelId === m.id}
                        style={darkBtnStyle}
                      />
                    </Tooltip>
                    <Tooltip title={t("models.testConnection")}>
                      <Button
                        type="text"
                        size="small"
                        icon={<ApiOutlined />}
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
                          isConfigOpen ? <DownOutlined /> : <SettingOutlined />
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
                        icon={<DeleteOutlined />}
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
                      onClose={() => setConfigOpenModelId(null)}
                      isDark={isDark}
                    />
                  </div>
                )}
              </div>
            );
          })
        )}
      </div>

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
                  options={availableSeries.map((s) => ({
                    label: s,
                    value: s,
                  }))}
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
                    {
                      label: (
                        <>
                          <SparkImageuploadLine /> {t("models.modalityVision")}
                        </>
                      ),
                      value: "image",
                    },
                    {
                      label: (
                        <>
                          <SparkAudiouploadLine /> {t("models.modalityAudio")}
                        </>
                      ),
                      value: "audio",
                    },
                    {
                      label: (
                        <>
                          <SparkVideouploadLine /> {t("models.modalityVideo")}
                        </>
                      ),
                      value: "video",
                    },
                    {
                      label: (
                        <>
                          <SparkFilePdfLine /> {t("models.modalityFile")}
                        </>
                      ),
                      value: "file",
                    },
                    {
                      label: (
                        <>
                          <SparkTextLine /> {t("models.modalityText")}
                        </>
                      ),
                      value: "text",
                    },
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
                style={{ width: "100%" }}
              >
                {t("models.getModels") || "Get Models"}
              </Button>

              {/* Discovered Models List */}
              {discoveredModels.length > 0 && (
                <div
                  style={{
                    marginTop: 12,
                    maxHeight: 200,
                    overflowY: "auto",
                  }}
                >
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
                        <div
                          style={{
                            fontSize: 11,
                            color: "#666",
                            display: "flex",
                            alignItems: "center",
                            gap: 4,
                          }}
                        >
                          <span>{model.provider}</span>
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
                            <SparkTextImageLine
                              style={{ fontSize: 12, color: "purple" }}
                            />
                          )}
                          {model.pricing?.prompt && (
                            <span style={{ color: "green", marginLeft: 4 }}>
                              $
                              {(
                                parseFloat(model.pricing.prompt) * 1_000_000
                              ).toFixed(2)}
                              {t("models.perMillionIn")}
                              {model.pricing?.completion && (
                                <span>
                                  {" "}
                                  · $
                                  {(
                                    parseFloat(model.pricing.completion) *
                                    1_000_000
                                  ).toFixed(2)}
                                  {t("models.perMillionOut")}
                                </span>
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
                  options={discoveredModels.map((model) => ({
                    value: model.id,
                    label: model.id,
                  }))}
                  filterOption={(
                    inputValue: string,
                    option?: { value?: string },
                  ) =>
                    option?.value
                      ?.toLowerCase()
                      .includes(inputValue.toLowerCase()) ?? false
                  }
                  notFoundContent={
                    loadingDiscoveredModels
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
          <div style={{ display: "flex", gap: 8, marginTop: 12 }}>
            <Button
              type="dashed"
              icon={<PlusOutlined />}
              onClick={() => setAdding(true)}
              style={{ flex: 1 }}
            >
              {t("models.addModel")}
            </Button>
          </div>
        ))}
    </Modal>
  );
}
