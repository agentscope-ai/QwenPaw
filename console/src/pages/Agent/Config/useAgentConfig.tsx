import { useState, useEffect, useCallback } from "react";
import { Form, Modal, message } from "@agentscope-ai/design";
import { useTranslation } from "react-i18next";
import api from "../../../api";
import type {
  AgentsRunningConfig,
  OrchestrationConfig,
} from "../../../api/types";

interface AgentInfo {
  id: string;
  name: string;
}

export function useAgentConfig() {
  const { t } = useTranslation();
  const [form] = Form.useForm();
  const [orchestrationForm] = Form.useForm();
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [savingOrchestration, setSavingOrchestration] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [language, setLanguage] = useState<string>("zh");
  const [savingLang, setSavingLang] = useState(false);
  const [timezone, setTimezone] = useState<string>("UTC");
  const [savingTimezone, setSavingTimezone] = useState(false);
  const [agentsList, setAgentsList] = useState<
    { value: string; label: string }[]
  >([]);

  const fetchConfig = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [config, orchestrationConfig, langResp, tzResp, agentsResp] =
        await Promise.all([
          api.getAgentRunningConfig(),
          api.getOrchestrationConfig(),
          api.getAgentLanguage(),
          api.getUserTimezone(),
          api.listAgents(),
        ]);
      form.setFieldsValue(config);
      orchestrationForm.setFieldsValue({
        can_spawn_agents: orchestrationConfig.can_spawn_agents,
        allowed_agents: orchestrationConfig.allowed_agents,
        max_spawn_depth: orchestrationConfig.max_spawn_depth,
      });
      setLanguage(langResp.language);
      setTimezone(tzResp.timezone || "UTC");
      // Build agents list for select
      const agents = (agentsResp.agents || []).map((agent: AgentInfo) => ({
        value: agent.id,
        label: agent.name || agent.id,
      }));
      setAgentsList(agents);
    } catch (err) {
      const errMsg =
        err instanceof Error ? err.message : t("agentConfig.loadFailed");
      setError(errMsg);
    } finally {
      setLoading(false);
    }
  }, [form, orchestrationForm, t]);

  useEffect(() => {
    fetchConfig();
  }, [fetchConfig]);

  const handleSave = useCallback(async () => {
    try {
      const values = await form.validateFields();
      setSaving(true);
      await api.updateAgentRunningConfig(values as AgentsRunningConfig);
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

  const handleSaveOrchestration = useCallback(async () => {
    try {
      const values = await orchestrationForm.validateFields();
      setSavingOrchestration(true);
      await api.updateOrchestrationConfig(values as OrchestrationConfig);
      message.success(t("agentConfig.orchestrationSaveSuccess"));
    } catch (err) {
      if (err instanceof Error && "errorFields" in err) return;
      const errMsg =
        err instanceof Error
          ? err.message
          : t("agentConfig.orchestrationSaveFailed");
      message.error(errMsg);
    } finally {
      setSavingOrchestration(false);
    }
  }, [orchestrationForm, t]);

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
    orchestrationForm,
    loading,
    saving,
    savingOrchestration,
    error,
    language,
    savingLang,
    timezone,
    savingTimezone,
    agentsList,
    fetchConfig,
    handleSave,
    handleSaveOrchestration,
    handleLanguageChange,
    handleTimezoneChange,
  };
}
