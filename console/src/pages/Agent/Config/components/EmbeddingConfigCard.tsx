import { useState, useEffect } from "react";
import {
  Form,
  Card,
  Switch,
  Select,
  Input,
  Button,
  Alert,
  Tag,
  Tooltip,
  message,
} from "@agentscope-ai/design";
import { useTranslation } from "react-i18next";
import api from "../../../../api";
import type {
  LocalEmbeddingConfig,
  EmbeddingPresetModels,
  EmbeddingModelInfo,
} from "../../../../api/types";
import styles from "../index.module.less";

const { Option } = Select;

interface EmbeddingConfigCardProps {
  form: ReturnType<typeof Form.useForm>[0];
}

const DEFAULT_CONFIG: LocalEmbeddingConfig = {
  enabled: false,
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

export function EmbeddingConfigCard({ form }: EmbeddingConfigCardProps) {
  const { t } = useTranslation();
  const [enabled, setEnabled] = useState(false);
  const [presetModels, setPresetModels] = useState<EmbeddingPresetModels | null>(null);
  const [loadingPresets, setLoadingPresets] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [testing, setTesting] = useState(false);
  const [downloading, setDownloading] = useState(false);
  const [testResult, setTestResult] = useState<{
    type: "success" | "error";
    message: string;
  } | null>(null);
  const [selectedModel, setSelectedModel] = useState<EmbeddingModelInfo | null>(null);

  // Load preset models on mount
  useEffect(() => {
    loadPresetModels();
  }, []);

  // Update selected model info when model_id changes
  useEffect(() => {
    try {
      const modelId = form?.getFieldValue?.(["local_embedding", "model_id"]);
      if (presetModels && modelId && Array.isArray(presetModels.multimodal) && Array.isArray(presetModels.text)) {
        const allModels = [...presetModels.multimodal, ...presetModels.text];
        const model = allModels.find((m) => m?.id === modelId);
        setSelectedModel(model || null);
      }
    } catch (e) {
      console.error("Error updating selected model:", e);
    }
  }, [presetModels, form, enabled]);

  // Watch enabled state
  useEffect(() => {
    try {
      const value = form?.getFieldValue?.(["local_embedding", "enabled"]);
      setEnabled(value === true);
    } catch (e) {
      console.error("Error watching enabled state:", e);
    }
  }, [form]);

  const loadPresetModels = async () => {
    setLoadingPresets(true);
    setLoadError(null);
    try {
      const data = await api.getPresetEmbeddingModels();
      // Validate data structure
      if (data && Array.isArray(data.multimodal) && Array.isArray(data.text)) {
        setPresetModels(data);
      } else {
        console.error("Invalid preset models data:", data);
        setLoadError("Invalid data structure from API");
        // Set default empty structure
        setPresetModels({ multimodal: [], text: [] });
      }
    } catch (err) {
      console.error("Failed to load preset models:", err);
      setLoadError(err instanceof Error ? err.message : String(err));
      message.error("加载模型列表失败");
      // Set default empty structure to prevent crashes
      setPresetModels({ multimodal: [], text: [] });
    } finally {
      setLoadingPresets(false);
    }
  };

  const handleEnabledChange = (checked: boolean) => {
    setEnabled(checked);
    // Initialize with default config if not exists
    try {
      const currentConfig = form?.getFieldValue?.("local_embedding");
      if (!currentConfig) {
        form?.setFieldValue?.("local_embedding", DEFAULT_CONFIG);
      }
    } catch (e) {
      console.error("Error initializing config:", e);
    }
  };

  const handleTest = async () => {
    try {
      const values = form?.getFieldValue?.("local_embedding") as LocalEmbeddingConfig;
      if (!values?.model_id) {
        message.warning(t("agentConfig.embedding.modelRequired") || "请选择模型");
        return;
      }

      setTesting(true);
      setTestResult(null);
      try {
        const result = await api.testLocalEmbeddingConfig(values);
        if (result?.success) {
          setTestResult({
            type: "success",
            message: `${result.message} (延迟: ${result.latency_ms?.toFixed?.(0) || "?"}ms)`,
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
      const values = form?.getFieldValue?.("local_embedding") as LocalEmbeddingConfig;
      if (!values?.model_id) {
        message.warning(t("agentConfig.embedding.modelRequired") || "请选择模型");
        return;
      }

      setDownloading(true);
      try {
        const result = await api.downloadLocalEmbeddingModel(values);
        if (result?.status === "completed") {
          message.success(
            (t("agentConfig.embedding.downloadSuccess") || "下载完成: {path}")
              .replace("{path}", result.local_path || "")
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
      <Tooltip title={t("agentConfig.embedding.helpTooltip") || "配置本地 Embedding 模型用于向量记忆检索"}>
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
      <Form.Item
        label={t("agentConfig.embedding.enable") || "启用本地 Embedding"}
        name={["local_embedding", "enabled"]}
        valuePropName="checked"
        tooltip={t("agentConfig.embedding.enableTooltip") || "开启后将使用本地模型生成文本向量"}
      >
        <Switch onChange={handleEnabledChange} />
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

      <div style={{ opacity: enabled ? 1 : 0.5, pointerEvents: enabled ? "auto" : "none" }}>
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
          name={["local_embedding", "model_id"]}
          rules={[{ required: true, message: t("agentConfig.embedding.modelRequired") || "请选择模型" }]}
          tooltip={t("agentConfig.embedding.modelTooltip") || "支持的模型包括多模态和纯文本两种类型"}
        >
          <Select
            placeholder={t("agentConfig.embedding.modelPlaceholder") || "选择 Embedding 模型"}
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
                  <Tag color={selectedModel.type === "multimodal" ? "blue" : "green"}>
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
          name={["local_embedding", "download_source"]}
          tooltip={t("agentConfig.embedding.downloadSourceTooltip") || "ModelScope 适合中国大陆访问"}
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
          name={["local_embedding", "device"]}
          tooltip={t("agentConfig.embedding.deviceTooltip") || "auto 自动检测 GPU"}
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
          name={["local_embedding", "dtype"]}
          tooltip={t("agentConfig.embedding.dtypeTooltip") || "FP16 速度快且省显存"}
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
          name={["local_embedding", "model_path"]}
          tooltip={t("agentConfig.embedding.modelPathTooltip") || "留空自动下载到缓存目录"}
        >
          <Input
            placeholder={t("agentConfig.embedding.modelPathPlaceholder") || "留空自动下载到缓存目录"}
            allowClear
          />
        </Form.Item>

        <div style={{ display: "flex", gap: 8, marginTop: 8 }}>
          <Button
            onClick={handleTest}
            loading={testing}
            disabled={testing || !enabled}
            type="default"
          >
            {testing ? "测试中..." : (t("agentConfig.embedding.test") || "测试连接")}
          </Button>
          <Button
            onClick={handleDownload}
            loading={downloading}
            disabled={downloading || !enabled}
            type="primary"
          >
            {downloading
              ? (t("agentConfig.embedding.downloading") || "下载中...")
              : (t("agentConfig.embedding.download") || "下载模型")}
          </Button>
        </div>

        <Alert
          type="info"
          showIcon
          message={t("agentConfig.embedding.noticeTitle") || "使用提示"}
          description={
            <ul style={{ margin: "8px 0", paddingLeft: 16 }}>
              <li>{t("agentConfig.embedding.notice1") || "启用后需要重启应用才能生效"}</li>
              <li>{t("agentConfig.embedding.notice2") || "首次使用会自动下载模型（约 1-2GB）"}</li>
              <li>{t("agentConfig.embedding.notice3") || "Qwen3-VL-Embedding 支持图文混合检索"}</li>
            </ul>
          }
          style={{ marginTop: 16 }}
        />
      </div>
    </Card>
  );
}
