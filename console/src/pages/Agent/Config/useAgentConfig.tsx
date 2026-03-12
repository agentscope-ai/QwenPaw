import { useState, useEffect, useCallback } from "react";
import { Form, Modal, message } from "@agentscope-ai/design";
import { useTranslation } from "react-i18next";
import api from "../../../api";
import type { AgentsRunningConfig } from "../../../api/types";

export function useAgentConfig() {
  const { t } = useTranslation();
  const [form] = Form.useForm();
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [language, setLanguage] = useState<string>("zh");
  const [savingLang, setSavingLang] = useState(false);
  const [hasFivemanageApiKey, setHasFivemanageApiKey] = useState(false);

  const fetchConfig = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [config, langResp] = await Promise.all([
        api.getAgentRunningConfig(),
        api.getAgentLanguage(),
      ]);
      setHasFivemanageApiKey(config.has_fivemanage_api_key);
      form.setFieldsValue({
        ...config,
        fivemanage_api_key: undefined,
      });
      setLanguage(langResp.language);
    } catch (err) {
      const errMsg =
        err instanceof Error ? err.message : t("agentConfig.loadFailed");
      setError(errMsg);
    } finally {
      setLoading(false);
    }
  }, [form, t]);

  useEffect(() => {
    fetchConfig();
  }, [fetchConfig]);

  const handleSave = useCallback(async () => {
    try {
      const values = await form.validateFields();
      const apiKey = values.fivemanage_api_key?.trim();
      const payload: AgentsRunningConfig = {
        ...values,
      };
      if (apiKey) {
        payload.fivemanage_api_key = apiKey;
      } else {
        delete payload.fivemanage_api_key;
      }

      setSaving(true);
      const updatedConfig = await api.updateAgentRunningConfig(payload);
      setHasFivemanageApiKey(updatedConfig.has_fivemanage_api_key);
      form.setFieldValue("fivemanage_api_key", undefined);
      message.success(t("agentConfig.saveSuccess"));
    } catch (err) {
      if (err instanceof Error && "errorFields" in err) return;
      const errMsg =
        err instanceof Error ? err.message : t("agentConfig.saveFailed");
      message.error(errMsg);
    } finally {
      setSaving(false);
    }
  }, [form, t]);

  const handleLanguageChange = useCallback(
    (value: string): void => {
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
    },
    [language, t],
  );

  return {
    form,
    loading,
    saving,
    error,
    language,
    savingLang,
    hasFivemanageApiKey,
    fetchConfig,
    handleSave,
    handleLanguageChange,
  };
}
