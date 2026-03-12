import { useState, useEffect } from "react";
import {
  Form,
  InputNumber,
  Select,
  Button,
  Card,
  Modal,
  message,
  Slider,
  Switch,
  Input,
} from "@agentscope-ai/design";
import { useTranslation } from "react-i18next";
import api from "../../../api";
import styles from "./index.module.less";
import type { AgentsRunningConfig } from "../../../api/types";

// Slider with value display component
function SliderWithValue({
  value,
  min,
  max,
  step,
  marks,
  onChange,
}: {
  value?: number;
  min?: number;
  max?: number;
  step?: number;
  marks?: Record<number, string>;
  onChange?: (value: number) => void;
}) {
  const formatValue = (v: number) => {
    if (v >= 1) return v.toString();
    return v.toFixed(2);
  };

  return (
    <div style={{ display: "flex", alignItems: "center", gap: 16 }}>
      <div style={{ flex: 1 }}>
        <Slider
          value={value}
          min={min}
          max={max}
          step={step}
          marks={marks}
          onChange={onChange}
        />
      </div>
      <div style={{ minWidth: 50, textAlign: "right", lineHeight: "32px" }}>
        <span style={{ fontWeight: 500, color: "#1890ff" }}>
          {value !== undefined ? formatValue(value) : "-"}
        </span>
      </div>
    </div>
  );
}
const LANGUAGE_OPTIONS = [
  { value: "zh", label: "中文" },
  { value: "en", label: "English" },
  { value: "ru", label: "Русский" },
];

function AgentConfigPage() {
  const { t } = useTranslation();
  const [form] = Form.useForm();
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [language, setLanguage] = useState<string>("zh");
  const [savingLang, setSavingLang] = useState(false);

  useEffect(() => {
    fetchConfig();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const fetchConfig = async () => {
    setLoading(true);
    setError(null);
    try {
      const [config, langResp] = await Promise.all([
        api.getAgentRunningConfig(),
        api.getAgentLanguage(),
      ]);
      form.setFieldsValue(config);
      setLanguage(langResp.language);
    } catch (err) {
      const errMsg =
        err instanceof Error ? err.message : t("agentConfig.loadFailed");
      setError(errMsg);
    } finally {
      setLoading(false);
    }
  };

  const handleSave = async () => {
    try {
      const values = await form.validateFields();
      setSaving(true);
      await api.updateAgentRunningConfig(values as AgentsRunningConfig);
      message.success(t("agentConfig.saveSuccess"));
    } catch (err) {
      if (err instanceof Error && "errorFields" in err) {
        return;
      }
      const errMsg =
        err instanceof Error ? err.message : t("agentConfig.saveFailed");
      message.error(errMsg);
    } finally {
      setSaving(false);
    }
  };

  const handleLanguageChange = (value: string) => {
    if (value === language) return;
    Modal.confirm({
      title: t("agentConfig.languageConfirmTitle"),
      content: (
        <span style={{ whiteSpace: "pre-line" }}>
          {t("agentConfig.languageConfirmContent")}
        </span>
      ),
      okText: t("agentConfig.languageConfirmOk"),
      cancelText: t("common.cancel"),
      onOk: async () => {
        setSavingLang(true);
        try {
          const resp = await api.updateAgentLanguage(value);
          setLanguage(resp.language);
          if (resp.copied_files && resp.copied_files.length > 0) {
            message.success(
              t("agentConfig.languageSaveSuccessWithFiles", {
                count: resp.copied_files.length,
              }),
            );
          } else {
            message.success(t("agentConfig.languageSaveSuccess"));
          }
        } catch (err) {
          const errMsg =
            err instanceof Error
              ? err.message
              : t("agentConfig.languageSaveFailed");
          message.error(errMsg);
        } finally {
          setSavingLang(false);
        }
      },
    });
  };

  const handleReset = () => {
    fetchConfig();
  };

  // Calculate derived values from form
  const getCalculatedValues = () => {
    const values = form.getFieldsValue([
      "max_input_length",
      "memory_compact_ratio",
      "memory_reserve_ratio",
    ]);
    const maxInputLength = values.max_input_length ?? 0;
    const memoryCompactRatio = values.memory_compact_ratio ?? 0;
    const memoryReserveRatio = values.memory_reserve_ratio ?? 0;

    return {
      contextCompactReserveThreshold: Math.floor(
        maxInputLength * memoryReserveRatio,
      ),
      contextCompactThreshold: Math.floor(maxInputLength * memoryCompactRatio),
    };
  };

  // Force re-render when form values change
  const [, forceUpdate] = useState({});

  const handleValuesChange = () => {
    forceUpdate({});
  };

  const { contextCompactReserveThreshold, contextCompactThreshold } =
    getCalculatedValues();

  return (
    <div className={styles.page}>
      {loading && (
        <div className={styles.centerState}>
          <span className={styles.stateText}>{t("common.loading")}</span>
        </div>
      )}

      {error && !loading && (
        <div className={styles.centerState}>
          <span className={styles.stateTextError}>{error}</span>
          <Button size="small" onClick={fetchConfig} style={{ marginTop: 12 }}>
            {t("environments.retry")}
          </Button>
        </div>
      )}

      <div style={{ display: loading || error ? "none" : "block" }}>
        <div className={styles.header}>
          <div>
            <h1 className={styles.title}>{t("agentConfig.title")}</h1>
            <p className={styles.description}>{t("agentConfig.description")}</p>
          </div>
        </div>

        <Form
          form={form}
          layout="vertical"
          className={styles.form}
          onValuesChange={handleValuesChange}
        >
          {/* ReAct Agent Section */}
          <Card
            className={styles.formCard}
            title={t("agentConfig.reactAgentTitle")}
          >
            <Form.Item
              label={t("agentConfig.language")}
              tooltip={t("agentConfig.languageTooltip")}
            >
              <Select
                value={language}
                options={LANGUAGE_OPTIONS}
                onChange={handleLanguageChange}
                loading={savingLang}
                disabled={savingLang}
                style={{ width: "100%" }}
              />
            </Form.Item>

            <Form.Item
              label={t("agentConfig.maxIters")}
              name="max_iters"
              rules={[
                { required: true, message: t("agentConfig.maxItersRequired") },
                {
                  type: "number",
                  min: 1,
                  message: t("agentConfig.maxItersMin"),
                },
              ]}
              tooltip={t("agentConfig.maxItersTooltip")}
            >
              <InputNumber
                style={{ width: "100%" }}
                min={1}
                placeholder={t("agentConfig.maxItersPlaceholder")}
              />
            </Form.Item>
          </Card>

          {/* Context Management Section */}
          <Card
            className={styles.formCard}
            title={t("agentConfig.contextManagementTitle")}
            style={{ marginTop: 16 }}
          >
            <Form.Item
              label={t("agentConfig.maxInputLength")}
              name="max_input_length"
              rules={[
                {
                  required: true,
                  message: t("agentConfig.maxInputLengthRequired"),
                },
                {
                  type: "number",
                  min: 1000,
                  message: t("agentConfig.maxInputLengthMin"),
                },
              ]}
              tooltip={t("agentConfig.maxInputLengthTooltip")}
            >
              <InputNumber
                style={{ width: "100%" }}
                min={1000}
                step={1024}
                placeholder={t("agentConfig.maxInputLengthPlaceholder")}
              />
            </Form.Item>

            <Form.Item
              label={t("agentConfig.contextCompactRatio")}
              name="memory_compact_ratio"
              rules={[
                {
                  required: true,
                  message: t("agentConfig.contextCompactRatioRequired"),
                },
              ]}
              tooltip={t("agentConfig.contextCompactRatioTooltip")}
            >
              <SliderWithValue
                min={0.3}
                max={0.9}
                step={0.01}
                marks={{ 0.3: "0.3", 0.6: "0.6", 0.9: "0.9" }}
              />
            </Form.Item>

            <Form.Item
              label={t("agentConfig.contextCompactThreshold")}
              tooltip={t("agentConfig.contextCompactThresholdTooltip")}
            >
              <Input
                disabled
                value={
                  contextCompactThreshold > 0
                    ? contextCompactThreshold.toLocaleString()
                    : ""
                }
                placeholder={t(
                  "agentConfig.contextCompactThresholdPlaceholder",
                )}
              />
            </Form.Item>

            <Form.Item
              label={t("agentConfig.contextCompactReserveRatio")}
              name="memory_reserve_ratio"
              rules={[
                {
                  required: true,
                  message: t("agentConfig.contextCompactReserveRatioRequired"),
                },
              ]}
              tooltip={t("agentConfig.contextCompactReserveRatioTooltip")}
            >
              <SliderWithValue
                min={0.05}
                max={0.3}
                step={0.01}
                marks={{ 0.05: "0.05", 0.15: "0.15", 0.3: "0.3" }}
              />
            </Form.Item>

            <Form.Item
              label={t("agentConfig.contextCompactReserveThreshold")}
              tooltip={t("agentConfig.contextCompactReserveThresholdTooltip")}
            >
              <Input
                disabled
                value={
                  contextCompactReserveThreshold > 0
                    ? contextCompactReserveThreshold.toLocaleString()
                    : ""
                }
                placeholder={t(
                  "agentConfig.contextCompactReserveThresholdPlaceholder",
                )}
              />
            </Form.Item>

            <Form.Item
              label={t("agentConfig.enableToolResultCompact")}
              name="enable_tool_result_compact"
              valuePropName="checked"
              tooltip={t("agentConfig.enableToolResultCompactTooltip")}
            >
              <Switch />
            </Form.Item>

            <Form.Item
              label={t("agentConfig.toolResultCompactKeepN")}
              name="tool_result_compact_keep_n"
              rules={[
                {
                  required: true,
                  message: t("agentConfig.toolResultCompactKeepNRequired"),
                },
              ]}
              tooltip={t("agentConfig.toolResultCompactKeepNTooltip")}
            >
              <SliderWithValue
                min={1}
                max={10}
                step={1}
                marks={{ 1: "1", 5: "5", 10: "10" }}
              />
            </Form.Item>
          </Card>

          <Form.Item className={styles.buttonGroup}>
            <Button
              onClick={handleReset}
              disabled={saving}
              style={{ marginRight: 8 }}
            >
              {t("common.reset")}
            </Button>
            <Button type="primary" onClick={handleSave} loading={saving}>
              {t("common.save")}
            </Button>
          </Form.Item>
        </Form>
      </div>
    </div>
  );
}

export default AgentConfigPage;
