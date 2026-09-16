import { useState, useEffect, useCallback, useRef } from "react";
import { Form, Modal } from "@agentscope-ai/design";
import { useTranslation } from "react-i18next";
import api from "../../../api";
import type { AgentsRunningConfig } from "../../../api/types";
import type {
  AgentRunningConfigAccess,
  AgentRunningConfigSummary,
  RunningConfigRequestContext,
} from "../../../api/modules/agent";
import { useAppMessage } from "../../../hooks/useAppMessage";
import { useAgentStore } from "../../../stores/agentStore";
import {
  CONTEXT_MANAGER_BACKEND_MAPPINGS,
  MEMORY_MANAGER_BACKEND_MAPPINGS,
  MEMORY_MANAGER_BACKEND_OPTIONS,
} from "../../../constants/backendMappings";
import type { ToolExecutionLevel } from "./components/ToolExecutionLevelCard";
import { mergeRunningConfig } from "./configMerge";

export function useAgentConfig(
  onConfigLoaded?: (config: AgentsRunningConfig) => void,
  governanceAgentId?: string,
) {
  const { t } = useTranslation();
  const { message } = useAppMessage();
  const { selectedAgent } = useAgentStore();
  const [form] = Form.useForm();
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [runtimeState, setRuntimeState] = useState<
    "applied" | "pending_reload"
  >("applied");
  const [retryReloading, setRetryReloading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [language, setLanguage] = useState<string>("zh");
  const [savingLang, setSavingLang] = useState(false);
  const [timezone, setTimezone] = useState<string>("UTC");
  const [savingTimezone, setSavingTimezone] = useState(false);
  const [access, setAccess] = useState<AgentRunningConfigAccess | null>(null);
  const [readOnlySummary, setReadOnlySummary] =
    useState<AgentRunningConfigSummary | null>(null);
  const [approvalLevel, setApprovalLevel] =
    useState<ToolExecutionLevel>("AUTO");
  const originalConfigRef = useRef<AgentsRunningConfig | null>(null);
  const configVersionRef = useRef<number | null>(null);

  const fetchConfig = useCallback(async () => {
    setLoading(true);
    setError(null);
    const requestContext: RunningConfigRequestContext | undefined =
      governanceAgentId
        ? { agentId: governanceAgentId, governance: true }
        : undefined;
    try {
      const accessResp = await api.getAgentRunningConfigAccess(requestContext);
      setAccess(accessResp);
      if (!accessResp.can_edit) {
        const summary = await api.getAgentRunningConfigSummary(requestContext);
        setReadOnlySummary(summary);
        setLanguage(summary.language);
        setTimezone(summary.timezone || "UTC");
        return;
      }
      setReadOnlySummary(null);
      const [config, versionResp, langResp, tzResp, runtimeStatus] =
        await Promise.all([
          api.getAgentRunningConfig(requestContext),
          api.getAgentRunningConfigVersion(requestContext),
          api.getAgentLanguage(requestContext),
          api.getUserTimezone(),
          api.getAgentRunningConfigRuntimeStatus(requestContext),
        ]);
      setRuntimeState(runtimeStatus.state);
      configVersionRef.current = versionResp.version;
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
      onConfigLoaded?.(config);

      setLanguage(langResp.language);
      setTimezone(tzResp.timezone || "UTC");
    } catch (err) {
      const errMsg =
        err instanceof Error ? err.message : t("agentConfig.loadFailed");
      setError(errMsg);
    } finally {
      setLoading(false);
    }
  }, [form, t, selectedAgent, onConfigLoaded, governanceAgentId]);

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

      // Independent cards (language/project/coding/plan) persist immediately.
      // Rebase the main form on the latest server document so a form that has
      // been open for a while cannot write stale independent settings back.
      const requestContext = governanceAgentId
        ? { agentId: governanceAgentId, governance: true }
        : undefined;
      const latestConfig = await api.getAgentRunningConfig(requestContext);
      const formValues = values as AgentsRunningConfig;
      const configToSave = mergeRunningConfig(
        latestConfig,
        formValues,
        approvalLevel,
      );

      const savedConfig = governanceAgentId
        ? await api.updateAgentRunningConfig(
            configToSave,
            configVersionRef.current ?? undefined,
            { agentId: governanceAgentId, governance: true },
          )
        : await api.updateAgentRunningConfig(
            configToSave,
            configVersionRef.current ?? undefined,
          );
      const nextVersion = await api.getAgentRunningConfigVersion(
        requestContext,
      );
      configVersionRef.current = nextVersion.version;
      const runtimeStatus = await api.getAgentRunningConfigRuntimeStatus(
        requestContext,
      );
      setRuntimeState(runtimeStatus.state);

      // Update original config after successful save
      originalConfigRef.current = savedConfig;
      onConfigLoaded?.(savedConfig);
      if (runtimeStatus.state === "pending_reload") {
        message.warning(t("agentConfig.savedPendingReload"));
      } else {
        message.success(t("agentConfig.saveSuccess"));
      }
    } catch (err) {
      if (err instanceof Error && "errorFields" in err) return;
      const errorText = err instanceof Error ? err.message : String(err);
      if (/403|forbidden/i.test(errorText)) {
        // Membership or an administrator governance grant can be revoked
        // while this page is open. Re-read access instead of leaving stale
        // editing controls active after the server rejects the write.
        await fetchConfig();
        return;
      }
      if (
        err instanceof Error &&
        err.message.includes("config_version_conflict")
      ) {
        Modal.confirm({
          title: t("agentConfig.versionConflictTitle"),
          content: t("agentConfig.versionConflictContent"),
          okText: t("agentConfig.versionConflictReload"),
          cancelText: t("common.cancel"),
          onOk: fetchConfig,
        });
        return;
      }
      const errMsg =
        err instanceof Error ? err.message : t("agentConfig.saveFailed");
      message.error(errMsg);
    } finally {
      setSaving(false);
    }
  }, [
    form,
    t,
    selectedAgent,
    approvalLevel,
    onConfigLoaded,
    fetchConfig,
    governanceAgentId,
  ]);

  const handleRetryReload = useCallback(async () => {
    setRetryReloading(true);
    try {
      const runtimeStatus = await api.retryAgentRunningConfigReload(
        governanceAgentId
          ? { agentId: governanceAgentId, governance: true }
          : undefined,
      );
      setRuntimeState(runtimeStatus.state);
      if (runtimeStatus.state === "applied") {
        message.success(t("agentConfig.reloadSuccess"));
      } else {
        message.warning(t("agentConfig.reloadPending"));
      }
    } catch (err) {
      message.error(
        err instanceof Error ? err.message : t("agentConfig.reloadFailed"),
      );
    } finally {
      setRetryReloading(false);
    }
  }, [message, t, governanceAgentId]);

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
            const resp = await api.updateAgentLanguage(
              value,
              governanceAgentId
                ? { agentId: governanceAgentId, governance: true }
                : undefined,
            );
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
    [language, t, governanceAgentId],
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
    runtimeState,
    retryReloading,
    error,
    language,
    savingLang,
    timezone,
    savingTimezone,
    access,
    readOnlySummary,
    isReadOnly: access?.can_edit === false,
    approvalLevel,
    setApprovalLevel,
    fetchConfig,
    handleSave,
    handleRetryReload,
    handleLanguageChange,
    handleTimezoneChange,
  };
}
