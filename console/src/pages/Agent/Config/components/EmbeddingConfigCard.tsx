import { useState, useEffect, useCallback } from "react";
import {
  Form,
  Card,
  Switch,
  Select,
  Input,
  Button,
  Space,
  Alert,
  Spin,
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
    const modelId = form.getFieldValue(["local_embedding", "model_id"]);
    if (presetModels && modelId) {
      const allModels = [...presetModels.multimodal, ...presetModels.text];
      const model = allModels.find((m) => m.id === modelId);
      setSelectedModel(model || null);
    }
  }, [presetModels, form, enabled]);

  // Watch enabled state
  useEffect(() => {
    const value = form.getFieldValue(["local_embedding", "enabled"]);
    setEnabled(value === true);
  }, [form]);

  const loadPresetModels = async () => {
    setLoadingPresets(true);
    try {
      const data = await api.getPresetEmbeddingModels();
      setPresetModels(data);
    } catch (err) {
      console.error("Failed to load preset models:", err);
    } finally {
      setLoadingPresets(false);
    }
  };

  const handleEnabledChange = (checked: boolean) => {
    setEnabled(checked);
    // Initialize with default config if not exists
    if (checked && !form.getFieldValue("local_embedding")) {
      form.setFieldValue("local_embedding", DEFAULT_CONFIG);
    }
  };

  const handleTest = async () => {
    const values = form.getFieldValue("local_embedding") as LocalEmbeddingConfig;
    if (!values?.model_id) {
      message.warning(t("agentConfig.embedding.modelRequired"));
      return;
    }

    setTesting(true);
    setTestResult(null);
    try {
      const result = await api.testLocalEmbeddingConfig(values);
      if (result.success) {
        setTestResult({
          type: "success",
          message: `${result.message} (延迟: ${result.latency_ms?.toFixed(0)}ms)`,
        });
        message.success(t("agentConfig.embedding.testSuccess"));
      } else {
        setTestResult({
          type: "error",
          message: result.message,
        });
        message.error(t("agentConfig.embedding.testFailed"));
      }
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      setTestResult({ type: "error", message: msg });
      message.error(t("agentConfig.embedding.testFailed"));
    } finally {
      setTesting(false);
    }
  };

  const handleDownload = async () => {
    const values = form.getFieldValue("local_embedding") as LocalEmbeddingConfig;
    if (!values?.model_id) {
      message.warning(t("agentConfig.embedding.modelRequired"));
      return;
    }

    setDownloading(true);
    try {
      const result = await api.downloadLocalEmbeddingModel(values);
      if (result.status === "completed") {
        message.success(
          t("agentConfig.embedding.downloadSuccess", { path: result.local_path })
        );
      } else {
        message.error(result.message);
      }
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      message.error(msg);
    } finally {
      setDownloading(false);
    }
  };

  const renderModelOption = (model: EmbeddingModelInfo) => (
    <Option key={model.id} value={model.id}>
      <Space>
        <span>{model.id}</span>
        <Tag size="small" color={model.type === "multimodal" ? "blue" : "green"}>
          {model.type === "multimodal" ? "多模态" : "纯文本"}
        </Tag>
        <Tag size="small">{model.dimensions}维</Tag>
        {model.mrl_enabled && (
          <Tooltip title="支持动态维度裁剪 (MRL)">
            <Tag size="small" color="purple">
              MRL
            </Tag>
          </Tooltip>
        )}
      </Space>
    </Option>
  );

  return (
    <Card
      className={styles.formCard}
      title={
        <Space>
          <span>{t("agentConfig.embedding.title")}</span>
          <Tooltip title={t("agentConfig.embedding.helpTooltip")}>
            <span style={{ cursor: "help", color: "#999" }}>ⓘ</span>
          </Tooltip>
        </Space>
      }
      style={{ marginTop: 16 }}
    >
      <Form.Item
        label={t("agentConfig.embedding.enable")}
        name={["local_embedding", "enabled"]}
        valuePropName="checked"
        tooltip={t("agentConfig.embedding.enableTooltip")}
      >
        <Switch onChange={handleEnabledChange} />
      </Form.Item>

      {enabled && (
        <>
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
            label={t("agentConfig.embedding.model")}
            name={["local_embedding", "model_id"]}
            rules={[{ required: true, message: t("agentConfig.embedding.modelRequired") }]}
            tooltip={t("agentConfig.embedding.modelTooltip")}
          >
            <Select
              placeholder={t("agentConfig.embedding.modelPlaceholder")}
              loading={loadingPresets}
              showSearch
              optionFilterProp="children"
            >
              {presetModels?.multimodal.length > 0 && (
                <Select.OptGroup label="多模态模型">
                  {presetModels.multimodal.map(renderModelOption)}
                </Select.OptGroup>
              )}
              {presetModels?.text.length > 0 && (
                <Select.OptGroup label="纯文本模型">
                  {presetModels.text.map(renderModelOption)}
                </Select.OptGroup>
              )}
            </Select>
          </Form.Item>

          {selectedModel && (
            <Alert
              type="info"
              showIcon={false}
              message={
                <Space direction="vertical" size="small" style={{ width: "100%" }}>
                  <Space>
                    <span>类型:</span>
                    <Tag color={selectedModel.type === "multimodal" ? "blue" : "green"}>
                      {selectedModel.type === "multimodal" ? "多模态" : "纯文本"}
                    </Tag>
                  </Space>
                  <Space>
                    <span>维度:</span>
                    <Tag>{selectedModel.dimensions}</Tag>
                    {selectedModel.mrl_enabled && (
                      <span style={{ color: "#666", fontSize: 12 }}>
                        (支持 MRL 裁剪至 {selectedModel.mrl_min_dims}D)
                      </span>
                    )}
                  </Space>
                </Space>
              }
              style={{ marginBottom: 16 }}
            />
          )}

          <Form.Item
            label={t("agentConfig.embedding.downloadSource")}
            name={["local_embedding", "download_source"]}
            tooltip={t("agentConfig.embedding.downloadSourceTooltip")}
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
            label={t("agentConfig.embedding.device")}
            name={["local_embedding", "device"]}
            tooltip={t("agentConfig.embedding.deviceTooltip")}
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
            label={t("agentConfig.embedding.dtype")}
            name={["local_embedding", "dtype"]}
            tooltip={t("agentConfig.embedding.dtypeTooltip")}
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
            label={t("agentConfig.embedding.modelPath")}
            name={["local_embedding", "model_path"]}
            tooltip={t("agentConfig.embedding.modelPathTooltip")}
          >
            <Input
              placeholder={t("agentConfig.embedding.modelPathPlaceholder")}
              allowClear
            />
          </Form.Item>

          <Space style={{ marginTop: 8 }}>
            <Button
              onClick={handleTest}
              loading={testing}
              disabled={testing}
              type="default"
            >
              {testing ? <Spin size="small" /> : t("agentConfig.embedding.test")}
            </Button>
            <Button
              onClick={handleDownload}
              loading={downloading}
              disabled={downloading}
              type="primary"
            >
              {downloading
                ? t("agentConfig.embedding.downloading")
                : t("agentConfig.embedding.download")}
            </Button>
          </Space>

          <Alert
            type="info"
            showIcon
            message={t("agentConfig.embedding.noticeTitle")}
            description={
              <ul style={{ margin: "8px 0", paddingLeft: 16 }}>
                <li>{t("agentConfig.embedding.notice1")}</li>
                <li>{t("agentConfig.embedding.notice2")}</li>
                <li>{t("agentConfig.embedding.notice3")}</li>
              </ul>
            }
            style={{ marginTop: 16 }}
          />
        </>
      )}
    </Card>
  );
}
