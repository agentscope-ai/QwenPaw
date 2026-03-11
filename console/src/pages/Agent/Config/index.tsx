import { useState, useEffect } from "react";
import {
  Form,
  InputNumber,
  Select,
  Button,
  Card,
  Modal,
  message,
} from "@agentscope-ai/design";
import { useTranslation } from "react-i18next";
import api from "../../../api";
import styles from "./index.module.less";
import type { AgentsRunningConfig } from "../../../api/types";

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

        <Card className={styles.formCard}>
          <Form form={form} layout="vertical" className={styles.form}>
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
        </Card>
      </div>
    </div>
  );
}

export default AgentConfigPage;
