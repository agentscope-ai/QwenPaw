import { useState, useEffect } from "react";
import {
  Form,
  Card,
  Select,
  Input,
  Button,
  Alert,
  Tag,
  Tooltip,
  message,
} from "@agentscope-ai/design";
import { Switch } from "antd";
import { useTranslation } from "react-i18next";
import api from "../../../../api";
import type {
  LocalEmbeddingConfig,
  EmbeddingConfigShape,
  EmbeddingPresetModels,
  EmbeddingModelInfo,
  EmbeddingResourceHint,
} from "../../../../api/types";
import styles from "../index.module.less";

const { Option } = Select;

interface EmbeddingConfigCardProps {
  form: ReturnType<typeof Form.useForm>[0];
}

const DEFAULT_EMBEDDING_CONFIG: Partial<EmbeddingConfigShape> = {
  enabled: false,
  backend_type: "transformers",
  model_id: "qwen/Qwen3-VL-Embedding-2B",
  model_path: null,
  device: "auto",
  dtype: "fp16",
  download_source: "modelscope",
};

const DEVICE_OPTIONS = [
  { value: "auto", label: "自动检测" },
  { value: "cuda", label: "CUDA (GPU)" },
  { value: "cpu", label: "CPU" },
];

const DTYPE_OPTIONS = [
  { value: "fp16", label: "FP16 (推荐)" },
  { value: "bf16", label: "BF16" },
  { value: "fp32", label: "FP32" },
];

const DOWNLOAD_SOURCE_OPTIONS = [
  { value: "modelscope", label: "ModelScope (国内)" },
  { value: "huggingface", label: "HuggingFace" },
];

const REMOTE_BACKEND_OPTIONS: Array<{
  value: Extract<EmbeddingConfigShape["backend_type"], "openai" | "ollama">;
  label: string;
}> = [
  { value: "openai", label: "OpenAI 兼容 API" },
  { value: "ollama", label: "Ollama 本地服务" },
];

// Hardcoded preset models as fallback when API fails
const FALLBACK_PRESET_MODELS: EmbeddingPresetModels = {
  multimodal: [
    {
      id: "qwen/Qwen3-VL-Embedding-2B",
      type: "multimodal",
      dimensions: 2048,
      pooling: "last_token",
      mrl_enabled: true,
      mrl_min_dims: 64,
    },
  ],
  text: [
    {
      id: "BAAI/bge-small-zh",
      type: "text",
      dimensions: 512,
      pooling: "cls",
    },
    {
      id: "BAAI/bge-large-zh-v1.5",
      type: "text",
      dimensions: 1024,
      pooling: "cls",
    },
    {
      id: "BAAI/bge-m3",
      type: "text",
      dimensions: 1024,
      pooling: "cls",
    },
  ],
};

export function EmbeddingConfigCard({ form }: EmbeddingConfigCardProps) {
  const { t } = useTranslation();
  const embeddingConfig = Form.useWatch("embedding_config", form) as
    | EmbeddingConfigShape
    | undefined;
  const embeddingBackendType = Form.useWatch(
    ["embedding_config", "backend_type"],
    form,
  ) as EmbeddingConfigShape["backend_type"] | undefined;
  const embeddingEnabled = Form.useWatch(
    ["embedding_config", "enabled"],
    form,
  ) as boolean | undefined;
  /** 本地 transformers：须 backend_type + enabled；勿仅用 enabled（默认常与 openai 同时为 true） */
  const localActive =
    embeddingBackendType === "transformers" && embeddingEnabled === true;
  const [presetModels, setPresetModels] =
    useState<EmbeddingPresetModels | null>(null);
  const [loadingPresets, setLoadingPresets] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [testing, setTesting] = useState(false);
  const [downloading, setDownloading] = useState(false);
  const [testResult, setTestResult] = useState<{
    type: "success" | "error";
    message: string;
  } | null>(null);
  const [selectedModel, setSelectedModel] = useState<EmbeddingModelInfo | null>(
    null,
  );
  const [resourceHint, setResourceHint] =
    useState<EmbeddingResourceHint | null>(null);
  const [localSwitchChecked, setLocalSwitchChecked] = useState(false);
  const [remoteBackendChoice, setRemoteBackendChoice] = useState<
    "openai" | "ollama"
  >("openai");
  // UI interactivity follows the switch state to avoid a "switch on but still disabled" mismatch.
  const localUiActive = localSwitchChecked || localActive;

  // Load preset models on mount
  useEffect(() => {
    loadPresetModels();
  }, []);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const hint = await api.getEmbeddingResourceHint();
        if (!cancelled && hint) {
          setResourceHint(hint);
        }
      } catch {
        /* optional hint */
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  // Update selected model info when model_id changes
  useEffect(() => {
    try {
      const modelId = embeddingConfig?.model_id;
      if (
        presetModels &&
        modelId &&
        Array.isArray(presetModels.multimodal) &&
        Array.isArray(presetModels.text)
      ) {
        const allModels = [...presetModels.multimodal, ...presetModels.text];
        const model = allModels.find((m) => m?.id === modelId);
        setSelectedModel(model || null);
      }
    } catch (e) {
      console.error("Error updating selected model:", e);
    }
  }, [presetModels, embeddingConfig?.model_id]);

  useEffect(() => {
    setLocalSwitchChecked(localActive);
  }, [localActive]);

  useEffect(() => {
    if (embeddingBackendType === "openai" || embeddingBackendType === "ollama") {
      setRemoteBackendChoice(embeddingBackendType);
    }
  }, [embeddingBackendType]);

  const loadPresetModels = async () => {
    setLoadingPresets(true);
    setLoadError(null);
    try {
      const data = await api.getPresetEmbeddingModels();
      // Validate data structure - API returns {multimodal: [...], text: [...]}
      if (data) {
        const multimodal = Array.isArray(data.multimodal)
          ? data.multimodal
          : [];
        const text = Array.isArray(data.text) ? data.text : [];
        setPresetModels({ multimodal, text });
      } else {
        console.warn("Empty preset models data, using fallback");
        setPresetModels(FALLBACK_PRESET_MODELS);
      }
    } catch (err) {
      console.error(
        "Failed to load preset models from API, using fallback:",
        err,
      );
      // Use fallback data when API fails (e.g., backend not updated)
      setPresetModels(FALLBACK_PRESET_MODELS);
      setLoadError(
        "后端 API 尚未更新，使用内置模型列表（建议重启服务到 feature 分支）",
      );
    } finally {
      setLoadingPresets(false);
    }
  };

  const handleLocalEmbeddingSwitch = (checked: boolean) => {
    setLocalSwitchChecked(checked);
    if (!form) {
      return;
    }
    try {
      const current = (form.getFieldValue("embedding_config") ||
        {}) as Partial<EmbeddingConfigShape>;
      if (checked) {
        const next = {
          ...DEFAULT_EMBEDDING_CONFIG,
          ...current,
          backend_type: "transformers" as const,
          enabled: true,
        };
        form.setFieldsValue({ embedding_config: next });
      } else {
        const nextRemoteBackend = remoteBackendChoice;
        form.setFieldsValue({
          embedding_config: {
            ...current,
            backend_type: nextRemoteBackend,
            enabled: true,
            ...(nextRemoteBackend === "ollama"
              ? {
                  base_url:
                    current.base_url && current.base_url.trim().length > 0
                      ? current.base_url
                      : "http://127.0.0.1:11434",
                  model_name:
                    current.model_name && current.model_name.trim().length > 0
                      ? current.model_name
                      : "mxbai-embed-large",
                }
              : {}),
          },
        });
      }
    } catch (e) {
      console.error("Error updating local embedding switch:", e);
    }
  };

  const handleRemoteBackendChange = (value: "openai" | "ollama") => {
    setRemoteBackendChoice(value);
    if (!form) {
      return;
    }
    try {
      const current = (form.getFieldValue("embedding_config") ||
        {}) as Partial<EmbeddingConfigShape>;
      form.setFieldsValue({
        embedding_config: {
          ...current,
          backend_type: value,
          enabled: true,
          ...(value === "ollama"
            ? {
                base_url:
                  current.base_url && current.base_url.trim().length > 0
                    ? current.base_url
                    : "http://127.0.0.1:11434",
                model_name:
                  current.model_name && current.model_name.trim().length > 0
                    ? current.model_name
                    : "mxbai-embed-large",
              }
            : {}),
        },
      });
    } catch (e) {
      console.error("Error updating remote embedding backend:", e);
    }
  };

  const handleTest = async () => {
    try {
      const ec = form?.getFieldValue?.("embedding_config") as
        | EmbeddingConfigShape
        | undefined;
      if (!ec?.model_id) {
        message.warning(
          t("agentConfig.embedding.modelRequired") || "请选择模型",
        );
        return;
      }

      const values: LocalEmbeddingConfig = {
        enabled: true,
        model_id: ec.model_id,
        model_path: ec.model_path,
        device: ec.device,
        dtype: ec.dtype,
        download_source: ec.download_source,
      };

      setTesting(true);
      setTestResult(null);
      try {
        const result = await api.testLocalEmbeddingConfig(values);
        if (result?.success) {
          setTestResult({
            type: "success",
            message: `${result.message} (延迟: ${
              result.latency_ms?.toFixed?.(0) || "?"
            }ms)`,
          });
          message.success(t("agentConfig.embedding.testSuccess") || "测试成功");
        } else {
          setTestResult({
            type: "error",
            message: result?.message || "未知错误",
          });
          message.error(t("agentConfig.embedding.testFailed") || "测试失败");
        }
      } catch (err) {
        const msg = err instanceof Error ? err.message : String(err);
        setTestResult({ type: "error", message: msg });
        message.error(t("agentConfig.embedding.testFailed") || "测试失败");
      } finally {
        setTesting(false);
      }
    } catch (e) {
      console.error("Error in handleTest:", e);
    }
  };

  const handleDownload = async () => {
    try {
      const ec = form?.getFieldValue?.("embedding_config") as
        | EmbeddingConfigShape
        | undefined;
      if (!ec?.model_id) {
        message.warning(
          t("agentConfig.embedding.modelRequired") || "请选择模型",
        );
        return;
      }

      const values: LocalEmbeddingConfig = {
        enabled: true,
        model_id: ec.model_id,
        model_path: ec.model_path,
        device: ec.device,
        dtype: ec.dtype,
        download_source: ec.download_source,
      };

      setDownloading(true);
      try {
        const result = await api.downloadLocalEmbeddingModel(values);
        if (result?.status === "completed") {
          message.success(
            (
              t("agentConfig.embedding.downloadSuccess") || "下载完成: {path}"
            ).replace("{path}", result.local_path || ""),
          );
        } else {
          message.error(result?.message || "下载失败");
        }
      } catch (err) {
        const msg = err instanceof Error ? err.message : String(err);
        message.error(msg);
      } finally {
        setDownloading(false);
      }
    } catch (e) {
      console.error("Error in handleDownload:", e);
    }
  };

  const renderModelOption = (model: EmbeddingModelInfo) => {
    if (!model || !model.id) return null;
    return (
      <Option key={model.id} value={model.id}>
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <span>{model.id}</span>
          <Tag color={model.type === "multimodal" ? "blue" : "green"}>
            {model.type === "multimodal" ? "多模态" : "纯文本"}
          </Tag>
          <Tag>{model.dimensions}维</Tag>
          {model.mrl_enabled && (
            <Tooltip title="支持动态维度裁剪 (MRL)">
              <Tag color="purple">MRL</Tag>
            </Tooltip>
          )}
        </div>
      </Option>
    );
  };

  const titleContent = (
    <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
      <span>{t("agentConfig.embedding.title") || "本地 Embedding 模型"}</span>
      <Tooltip
        title={
          t("agentConfig.embedding.helpTooltip") ||
          "配置本地 Embedding 模型用于向量记忆检索"
        }
      >
        <span style={{ cursor: "help", color: "#999" }}>ⓘ</span>
      </Tooltip>
    </div>
  );

  // Safe access to preset models
  const multimodalModels = presetModels?.multimodal || [];
  const textModels = presetModels?.text || [];

  return (
    <Card
      className={styles.formCard}
      title={titleContent}
      style={{ marginTop: 16 }}
    >
      {/* 无 name：不向子节点注入 value/onChange。单 child（div）内含 Switch，避免多子节点 Form.Item 误绑 Switch */}
      <Form.Item
        style={{ marginBottom: 16 }}
        label={
          <span
            style={{
              display: "inline-flex",
              alignItems: "center",
              gap: 6,
            }}
          >
            <span style={{ fontWeight: 500 }}>
              {t("agentConfig.embedding.enable") || "启用本地 Embedding"}
            </span>
            <Tooltip
              title={
                t("agentConfig.embedding.enableTooltip") ||
                "开启后将使用本地 transformers 模型；关闭则使用远程/OpenAI 兼容 API"
              }
            >
              <span style={{ cursor: "help", color: "#999" }}>ⓘ</span>
            </Tooltip>
          </span>
        }
      >
        <div
          style={{
            display: "flex",
            alignItems: "center",
            flexWrap: "wrap",
            gap: 8,
          }}
        >
          <Switch
            id="embedding-local-backend-switch"
            checked={localSwitchChecked}
            onChange={handleLocalEmbeddingSwitch}
            aria-label={
              t("agentConfig.embedding.enable") || "启用本地 Embedding"
            }
          />
          <span style={{ fontSize: 12, color: "#888" }}>
            {localUiActive
              ? "已选本地模型后端"
              : "当前为远程 API 后端；打开后可测试/下载本地模型"}
          </span>
        </div>
      </Form.Item>

      <Form.Item
        label="远程后端"
        tooltip="本地开关关闭时生效，可在 OpenAI 兼容 API 与 Ollama 之间切换"
        style={{ marginBottom: 16 }}
      >
        <Select
          value={remoteBackendChoice}
          onChange={handleRemoteBackendChange}
          disabled={localUiActive}
        >
          {REMOTE_BACKEND_OPTIONS.map((opt) => (
            <Option key={opt.value} value={opt.value}>
              {opt.label}
            </Option>
          ))}
        </Select>
      </Form.Item>

      {loadError && (
        <Alert
          type="error"
          message="加载模型列表失败"
          description={loadError}
          style={{ marginBottom: 16 }}
          closable
          onClose={() => setLoadError(null)}
        />
      )}

      {resourceHint && (
        <Alert
          type="info"
          showIcon
          message="本机资源与模型建议（未加载权重）"
          description={
            <div style={{ fontSize: 13, lineHeight: 1.6 }}>
              <div>
                <strong>系统</strong> {resourceHint.platform} ·{" "}
                <strong>CPU 逻辑核心</strong> {resourceHint.cpu_count ?? "?"}
                {resourceHint.ram_total_gb != null && (
                  <>
                    {" "}
                    · <strong>内存</strong> 总计约 {resourceHint.ram_total_gb}{" "}
                    GB
                    {resourceHint.ram_available_gb != null && (
                      <>（可用约 {resourceHint.ram_available_gb} GB）</>
                    )}
                  </>
                )}
              </div>
              {Array.isArray(resourceHint.gpus) &&
              resourceHint.gpus.length > 0 ? (
                <div style={{ marginTop: 8 }}>
                  <strong>NVIDIA GPU</strong>
                  <ul style={{ margin: "4px 0 0 16px", padding: 0 }}>
                    {resourceHint.gpus.map((g) => (
                      <li key={g.index}>
                        {g.name}
                        {g.total_memory_mb != null && (
                          <>
                            {" "}
                            — 显存约 {Math.round(g.total_memory_mb / 1024)} GB
                          </>
                        )}
                        {g.source && (
                          <span style={{ color: "#888" }}> ({g.source})</span>
                        )}
                      </li>
                    ))}
                  </ul>
                </div>
              ) : Array.isArray(resourceHint.gpus) ? (
                <div style={{ marginTop: 8, color: "#666" }}>
                  未检测到可用 NVIDIA
                  GPU（或未安装驱动）；多模态大模型将主要依赖 CPU 与内存。
                </div>
              ) : null}
              {resourceHint.recommendation ? (
                <div style={{ marginTop: 10 }}>
                  <strong>选型建议</strong>
                  <p style={{ margin: "6px 0 0 0" }}>
                    {resourceHint.recommendation}
                  </p>
                  {resourceHint.model_tiers && (
                    <ul style={{ margin: "6px 0 0 16px", padding: 0 }}>
                      <li>{resourceHint.model_tiers.text_small}</li>
                      <li>{resourceHint.model_tiers.text_mid}</li>
                      <li>{resourceHint.model_tiers.multimodal_2b}</li>
                    </ul>
                  )}
                </div>
              ) : null}
              {resourceHint.note ? (
                <p style={{ margin: "8px 0 0 0", color: "#888", fontSize: 12 }}>
                  {resourceHint.note}
                </p>
              ) : null}
            </div>
          }
          style={{ marginBottom: 16 }}
          closable
          onClose={() => setResourceHint(null)}
        />
      )}

      <div
        style={{
          opacity: localUiActive ? 1 : 0.5,
          pointerEvents: localUiActive ? "auto" : "none",
        }}
      >
        {testResult && (
          <Alert
            type={testResult.type}
            message={testResult.message}
            style={{ marginBottom: 16 }}
            closable
            onClose={() => setTestResult(null)}
          />
        )}

        <Form.Item
          label={t("agentConfig.embedding.model") || "模型"}
          name={["embedding_config", "model_id"]}
          rules={[
            {
              required: true,
              message: t("agentConfig.embedding.modelRequired") || "请选择模型",
            },
          ]}
          tooltip={
            t("agentConfig.embedding.modelTooltip") ||
            "支持的模型包括多模态和纯文本两种类型"
          }
        >
          <Select
            placeholder={
              t("agentConfig.embedding.modelPlaceholder") ||
              "选择 Embedding 模型"
            }
            loading={loadingPresets}
            showSearch
            optionFilterProp="children"
            notFoundContent={loadingPresets ? "加载中..." : "暂无数据"}
          >
            {multimodalModels.length > 0 && (
              <Select.OptGroup label="多模态模型">
                {multimodalModels.map(renderModelOption)}
              </Select.OptGroup>
            )}
            {textModels.length > 0 && (
              <Select.OptGroup label="纯文本模型">
                {textModels.map(renderModelOption)}
              </Select.OptGroup>
            )}
          </Select>
        </Form.Item>

        {selectedModel && (
          <Alert
            type="info"
            showIcon={false}
            message={
              <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
                <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                  <span>类型:</span>
                  <Tag
                    color={
                      selectedModel.type === "multimodal" ? "blue" : "green"
                    }
                  >
                    {selectedModel.type === "multimodal" ? "多模态" : "纯文本"}
                  </Tag>
                </div>
                <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                  <span>维度:</span>
                  <Tag>{selectedModel.dimensions}</Tag>
                  {selectedModel.mrl_enabled && (
                    <span style={{ color: "#666", fontSize: 12 }}>
                      (支持 MRL 裁剪至 {selectedModel.mrl_min_dims}D)
                    </span>
                  )}
                </div>
              </div>
            }
            style={{ marginBottom: 16 }}
          />
        )}

        <Form.Item
          label={t("agentConfig.embedding.downloadSource") || "下载源"}
          name={["embedding_config", "download_source"]}
          tooltip={
            t("agentConfig.embedding.downloadSourceTooltip") ||
            "ModelScope 适合中国大陆访问"
          }
        >
          <Select>
            {DOWNLOAD_SOURCE_OPTIONS.map((opt) => (
              <Option key={opt.value} value={opt.value}>
                {opt.label}
              </Option>
            ))}
          </Select>
        </Form.Item>

        <Form.Item
          label={t("agentConfig.embedding.device") || "运行设备"}
          name={["embedding_config", "device"]}
          tooltip={
            t("agentConfig.embedding.deviceTooltip") || "auto 自动检测 GPU"
          }
        >
          <Select>
            {DEVICE_OPTIONS.map((opt) => (
              <Option key={opt.value} value={opt.value}>
                {opt.label}
              </Option>
            ))}
          </Select>
        </Form.Item>

        <Form.Item
          label={t("agentConfig.embedding.dtype") || "数据精度"}
          name={["embedding_config", "dtype"]}
          tooltip={
            t("agentConfig.embedding.dtypeTooltip") || "FP16 速度快且省显存"
          }
        >
          <Select>
            {DTYPE_OPTIONS.map((opt) => (
              <Option key={opt.value} value={opt.value}>
                {opt.label}
              </Option>
            ))}
          </Select>
        </Form.Item>

        <Form.Item
          label={t("agentConfig.embedding.modelPath") || "本地模型路径（可选）"}
          name={["embedding_config", "model_path"]}
          tooltip={
            t("agentConfig.embedding.modelPathTooltip") ||
            "留空自动下载到缓存目录"
          }
        >
          <Input
            placeholder={
              t("agentConfig.embedding.modelPathPlaceholder") ||
              "留空自动下载到缓存目录"
            }
            allowClear
          />
        </Form.Item>

        <div style={{ display: "flex", gap: 8, marginTop: 8 }}>
          <Button
            onClick={handleTest}
            loading={testing}
            disabled={testing || !localUiActive}
            type="default"
          >
            {testing
              ? "测试中..."
              : t("agentConfig.embedding.test") || "测试连接"}
          </Button>
          <Button
            onClick={handleDownload}
            loading={downloading}
            disabled={downloading || !localUiActive}
            type="primary"
          >
            {downloading
              ? t("agentConfig.embedding.downloading") || "下载中..."
              : t("agentConfig.embedding.download") || "下载模型"}
          </Button>
        </div>

        <Alert
          type="info"
          showIcon
          message={t("agentConfig.embedding.noticeTitle") || "使用提示"}
          description={
            <ul style={{ margin: "8px 0", paddingLeft: 16 }}>
              <li>
                {t("agentConfig.embedding.notice1") ||
                  "启用后需要重启应用才能生效"}
              </li>
              <li>
                {t("agentConfig.embedding.notice2") ||
                  "首次使用会自动下载模型（约 1-2GB）"}
              </li>
              <li>
                {t("agentConfig.embedding.notice3") ||
                  "Qwen3-VL-Embedding 支持图文混合检索"}
              </li>
            </ul>
          }
          style={{ marginTop: 16 }}
        />
      </div>
    </Card>
  );
}
