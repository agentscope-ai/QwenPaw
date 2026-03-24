import { useState, useEffect, useCallback } from "react";
import { Form, Modal, message } from "@agentscope-ai/design";
import { useTranslation } from "react-i18next";
import api from "../../../api";
import type { AgentsRunningConfig, ProviderInfo } from "../../../api/types";

export function useAgentConfig() {
  const { t } = useTranslation();
  const [form] = Form.useForm();
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [language, setLanguage] = useState<string>("zh");
  const [savingLang, setSavingLang] = useState(false);
  const [timezone, setTimezone] = useState<string>("UTC");
  const [savingTimezone, setSavingTimezone] = useState(false);
  const [providers, setProviders] = useState<ProviderInfo[]>([]);

  const fetchConfig = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [config, langResp, tzResp, fallbackResp, providersResp] =
        await Promise.all([
          api.getAgentRunningConfig(),
          api.getAgentLanguage(),
          api.getUserTimezone(),
          api.getFallbackConfig(),
          api.listProviders(),
        ]);

      // Merge fallback config into form values
      const formValues = {
        ...config,
        fallback_config: fallbackResp || {
          fallbacks: [],
          cooldown_enabled: true,
          max_fallbacks: 3,
        },
      };

      form.setFieldsValue(formValues);
      setLanguage(langResp.language);
      setTimezone(tzResp.timezone || "UTC");
      setProviders(providersResp);
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
      setSaving(true);

      // Save running config (without fallback_config)
      const { fallback_config, ...runningConfig } = values;

      try {
        await api.updateAgentRunningConfig(
          runningConfig as AgentsRunningConfig,
        );
      } catch (err) {
        message.error(t("agentConfig.saveFailed"));
        throw err;
      }

      // Save fallback config separately (non-critical)
      if (fallback_config) {
        try {
          await api.setFallbackConfig(fallback_config);
        } catch (err) {
          message.warning(t("agentConfig.fallbackSaveFailed"));
          console.error("Failed to save fallback config:", err);
          // Don't throw - fallback config is optional
        }
      }

      message.success(t("agentConfig.saveSuccess"));
    } catch (err) {
      if (err instanceof Error && "errorFields" in err) return;
      // Error already handled above
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

  const handleTimezoneChange = useCallback(
    async (value: string) => {
      if (value === timezone) return;
      setSavingTimezone(true);
      try {
        await api.updateUserTimezone(value);
        setTimezone(value);
        message.success(t("agentConfig.timezoneSaveSuccess"));
      } catch (err) {
        const errMsg =
          err instanceof Error
            ? err.message
            : t("agentConfig.timezoneSaveFailed");
        message.error(errMsg);
      } finally {
        setSavingTimezone(false);
      }
    },
    [timezone, t],
  );

  return {
    form,
    loading,
    saving,
    error,
    language,
    savingLang,
    timezone,
    savingTimezone,
    providers,
    fetchConfig,
    handleSave,
    handleLanguageChange,
    handleTimezoneChange,
  };
}
