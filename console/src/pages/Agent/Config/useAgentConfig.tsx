import { useState, useEffect, useCallback, useRef } from "react";
import { Form, Modal } from "@agentscope-ai/design";
import { useTranslation } from "react-i18next";
import api from "../../../api";
import type {
  AgentModelRoutingDraft,
  AgentRunningConfigUpdate,
  AgentsRunningConfig,
} from "../../../api/types";
import { useAppMessage } from "../../../hooks/useAppMessage";
import { useAgentStore } from "../../../stores/agentStore";
import {
  CONTEXT_MANAGER_BACKEND_MAPPINGS,
  MEMORY_MANAGER_BACKEND_MAPPINGS,
  MEMORY_MANAGER_BACKEND_OPTIONS,
} from "../../../constants/backendMappings";
import type { ToolExecutionLevel } from "./components/ToolExecutionLevelCard";

export function useAgentConfig(
  onConfigLoaded?: (config: AgentsRunningConfig) => void,
) {
  const { t } = useTranslation();
  const { message } = useAppMessage();
  const { selectedAgent } = useAgentStore();
  const [form] = Form.useForm();
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [language, setLanguage] = useState<string>("zh");
  const [savingLang, setSavingLang] = useState(false);
  const [timezone, setTimezone] = useState<string>("UTC");
  const [savingTimezone, setSavingTimezone] = useState(false);
  const [approvalLevel, setApprovalLevel] =
    useState<ToolExecutionLevel>("AUTO");
  const [modelRouting, setModelRouting] = useState<AgentModelRoutingDraft>({
    active_model: null,
    fallback_models: [],
    fallback_policy: { enabled: true, target_scope: "configured" },
    subagent_model: null,
  });
  const [modelRoutingResetToken, setModelRoutingResetToken] = useState(0);
  const originalConfigRef = useRef<AgentsRunningConfig | null>(null);
  const latestConfigRequestRef = useRef(0);

  const fetchConfig = useCallback(async () => {
    const requestId = ++latestConfigRequestRef.current;
    const requestedAgent = selectedAgent || "default";
    const isCurrentRequest = () =>
      requestId === latestConfigRequestRef.current &&
      (useAgentStore.getState().selectedAgent || "default") === requestedAgent;

    setLoading(true);
    setError(null);
    try {
      const [config, langResp, tzResp] = await Promise.all([
        api.getAgentRunningConfig(),
        api.getAgentLanguage(),
        api.getUserTimezone(),
      ]);
      if (!isCurrentRequest()) return;

      const loadedLevel = (
        config.approval_level || "AUTO"
      ).toUpperCase() as ToolExecutionLevel;
      setApprovalLevel(loadedLevel);
      const contextBackend =
        config.context_manager_backend in CONTEXT_MANAGER_BACKEND_MAPPINGS
          ? config.context_manager_backend
          : "light";
      const memoryBackend =
        config.memory_manager_backend in MEMORY_MANAGER_BACKEND_MAPPINGS ||
        MEMORY_MANAGER_BACKEND_OPTIONS.some(
          (o) => o.value === config.memory_manager_backend,
        )
          ? config.memory_manager_backend
          : "remelight";
      form.setFieldsValue({
        shell_command_timeout: config.shell_command_timeout ?? 60.0,
        shell_command_executable: config.shell_command_executable ?? "",
        loop: {
          ...config.loop,
          iteration: {
            ...config.loop?.iteration,
            max_iterations:
              config.loop?.iteration?.max_iterations ?? config.max_iters ?? 100,
          },
        },
        llm_retry_enabled: config.llm_retry_enabled,
        llm_max_retries: config.llm_max_retries,
        llm_backoff_base: config.llm_backoff_base,
        llm_backoff_cap: config.llm_backoff_cap,
        llm_max_concurrent: config.llm_max_concurrent,
        llm_max_qpm: config.llm_max_qpm,
        llm_rate_limit_pause: config.llm_rate_limit_pause,
        llm_rate_limit_jitter: config.llm_rate_limit_jitter,
        llm_acquire_timeout: config.llm_acquire_timeout,
        history_max_length: config.history_max_length,
        context_manager_backend: contextBackend,
        light_context_config: config.light_context_config,
        memory_manager_backend: memoryBackend,
        reme_light_memory_config: config.reme_light_memory_config,
        adbpg_memory_config: config.adbpg_memory_config,
        auto_title_config: config.auto_title_config ?? {
          enabled: true,
          timeout_seconds: 30.0,
        },
      });

      // Store original config for complete save
      originalConfigRef.current = config;
      setModelRouting({
        active_model: config.active_model ?? null,
        fallback_models: config.fallback_models ?? [],
        fallback_policy: config.fallback_policy ?? {
          enabled: true,
          target_scope: "configured",
        },
        subagent_model: config.subagent_model ?? null,
      });
      setModelRoutingResetToken((token) => token + 1);
      onConfigLoaded?.(config);

      setLanguage(langResp.language);
      setTimezone(tzResp.timezone || "UTC");
    } catch (err) {
      if (!isCurrentRequest()) return;

      const errMsg =
        err instanceof Error ? err.message : t("agentConfig.loadFailed");
      setError(errMsg);
    } finally {
      if (isCurrentRequest()) setLoading(false);
    }
  }, [form, t, selectedAgent, onConfigLoaded]);

  useEffect(() => {
    fetchConfig();
  }, [fetchConfig]);

  const handleSave = useCallback(async () => {
    try {
      await form.validateFields();
      setSaving(true);

      // Include values written programmatically and fields inside collapsed
      // editors. validateFields() only returns currently registered fields,
      // which can omit custom loop gate identity and parameters.
      const values = form.getFieldsValue(true);

      // Deep-merge nested config objects so that collapsed (unrendered)
      // Collapse panels don't lose their saved values.  Shallow spread
      // would overwrite the entire nested object with only the rendered
      // fields, dropping anything inside a collapsed panel.
      const original = originalConfigRef.current!;
      const formValues = values as AgentsRunningConfig;

      const deepMergeConfig = <T,>(
        base: T | undefined | null,
        override: T | undefined | null,
      ): T | undefined => {
        if (!base) return override ?? undefined;
        if (!override) return base;
        const baseRecord = base as Record<string, unknown>;
        const overrideRecord = override as Record<string, unknown>;
        const result: Record<string, unknown> = { ...baseRecord };
        for (const key of Object.keys(overrideRecord)) {
          const overrideVal = overrideRecord[key];
          const baseVal = baseRecord[key];
          if (
            overrideVal != null &&
            typeof overrideVal === "object" &&
            !Array.isArray(overrideVal) &&
            baseVal != null &&
            typeof baseVal === "object" &&
            !Array.isArray(baseVal)
          ) {
            result[key] = deepMergeConfig(baseVal, overrideVal);
          } else {
            result[key] = overrideVal;
          }
        }
        return result as T;
      };

      const configToSave: AgentsRunningConfig = {
        ...original,
        ...formValues,
        // Deep-merge nested config sections to preserve collapsed fields
        reme_light_memory_config: deepMergeConfig(
          original.reme_light_memory_config,
          formValues.reme_light_memory_config,
        ) as typeof original.reme_light_memory_config,
        light_context_config: deepMergeConfig(
          original.light_context_config,
          formValues.light_context_config,
        ) as typeof original.light_context_config,
        adbpg_memory_config: deepMergeConfig(
          original.adbpg_memory_config,
          formValues.adbpg_memory_config,
        ) as typeof original.adbpg_memory_config,
        auto_title_config: deepMergeConfig(
          original.auto_title_config,
          formValues.auto_title_config,
        ) as typeof original.auto_title_config,
        approval_level: approvalLevel,
        // Keep legacy max_iters aligned with the UI-bound iteration limit.
        max_iters:
          formValues.loop?.iteration?.max_iterations ?? original.max_iters,
      };

      const submittedConfig: AgentRunningConfigUpdate = {
        ...configToSave,
        ...modelRouting,
      };
      const savedConfig = await api.updateAgentRunningConfig(submittedConfig);

      // Update original config after successful save
      originalConfigRef.current = savedConfig;
      setModelRouting({
        active_model:
          "active_model" in savedConfig
            ? savedConfig.active_model ?? null
            : modelRouting.active_model,
        fallback_models:
          "fallback_models" in savedConfig
            ? savedConfig.fallback_models ?? []
            : modelRouting.fallback_models,
        fallback_policy:
          "fallback_policy" in savedConfig && savedConfig.fallback_policy
            ? savedConfig.fallback_policy
            : modelRouting.fallback_policy,
        subagent_model:
          "subagent_model" in savedConfig
            ? savedConfig.subagent_model ?? null
            : modelRouting.subagent_model,
      });
      setModelRoutingResetToken((token) => token + 1);
      onConfigLoaded?.(savedConfig);
      message.success(t("agentConfig.saveSuccess"));
    } catch (err) {
      if (err instanceof Error && "errorFields" in err) return;
      const errMsg =
        err instanceof Error ? err.message : t("agentConfig.saveFailed");
      message.error(errMsg);
    } finally {
      setSaving(false);
    }
  }, [form, t, approvalLevel, onConfigLoaded, modelRouting, message]);

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
    [language, t, message],
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
    [timezone, t, message],
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
    approvalLevel,
    setApprovalLevel,
    modelRouting,
    setModelRouting,
    modelRoutingResetToken,
    fetchConfig,
    handleSave,
    handleLanguageChange,
    handleTimezoneChange,
  };
}
