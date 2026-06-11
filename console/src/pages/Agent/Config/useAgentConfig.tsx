import { useState, useEffect, useCallback, useRef } from "react";
import { useForm } from "react-hook-form";
import { useTranslation } from "react-i18next";
import api from "../../../api";
import type { AgentsRunningConfig } from "../../../api/types";
import { useAppMessage } from "../../../hooks/useAppMessage";
import { useAgentStore } from "../../../stores/agentStore";
import {
  CONTEXT_MANAGER_BACKEND_MAPPINGS,
  MEMORY_MANAGER_BACKEND_MAPPINGS,
} from "../../../constants/backendMappings";
import type { ToolExecutionLevel } from "./components/ToolExecutionLevelCard";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";

export type AgentConfigFormValues = Record<string, unknown>;

export function useAgentConfig() {
  const { t } = useTranslation();
  const { message } = useAppMessage();
  const { selectedAgent } = useAgentStore();
  const form = useForm<AgentConfigFormValues>({ defaultValues: {} });
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [language, setLanguage] = useState<string>("zh");
  const [savingLang, setSavingLang] = useState(false);
  const [timezone, setTimezone] = useState<string>("UTC");
  const [savingTimezone, setSavingTimezone] = useState(false);
  const [approvalLevel, setApprovalLevel] =
    useState<ToolExecutionLevel>("AUTO");
  const originalConfigRef = useRef<AgentsRunningConfig | null>(null);

  // Language confirm dialog state
  const [langConfirmOpen, setLangConfirmOpen] = useState(false);
  const [pendingLang, setPendingLang] = useState<string | null>(null);

  const fetchConfig = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [config, langResp, tzResp] = await Promise.all([
        api.getAgentRunningConfig(),
        api.getAgentLanguage(),
        api.getUserTimezone(),
      ]);
      const loadedLevel = (
        config.approval_level || "AUTO"
      ).toUpperCase() as ToolExecutionLevel;
      setApprovalLevel(loadedLevel);
      const contextBackend =
        config.context_manager_backend in CONTEXT_MANAGER_BACKEND_MAPPINGS
          ? config.context_manager_backend
          : "light";
      const memoryBackend =
        config.memory_manager_backend in MEMORY_MANAGER_BACKEND_MAPPINGS
          ? config.memory_manager_backend
          : "remelight";
      form.reset({
        max_iters: config.max_iters,
        auto_continue_on_text_only: config.auto_continue_on_text_only ?? false,
        shell_command_timeout: config.shell_command_timeout ?? 60.0,
        shell_command_executable: config.shell_command_executable ?? "",
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
      originalConfigRef.current = config;
      setLanguage(langResp.language);
      setTimezone(tzResp.timezone || "UTC");
    } catch (err) {
      const errMsg =
        err instanceof Error ? err.message : t("agentConfig.loadFailed");
      setError(errMsg);
    } finally {
      setLoading(false);
    }
  }, [form, t, selectedAgent]);

  useEffect(() => {
    fetchConfig();
  }, [fetchConfig]);

  const handleSave = useCallback(async () => {
    const isValid = await form.trigger();
    if (!isValid) return;
    const values = form.getValues();
    setSaving(true);
    try {
      const configToSave: AgentsRunningConfig = {
        ...originalConfigRef.current!,
        ...(values as unknown as AgentsRunningConfig),
        approval_level: approvalLevel,
      };
      await api.updateAgentRunningConfig(configToSave);
      originalConfigRef.current = configToSave;
      message.success(t("agentConfig.saveSuccess"));
    } catch (err) {
      const errMsg =
        err instanceof Error ? err.message : t("agentConfig.saveFailed");
      message.error(errMsg);
    } finally {
      setSaving(false);
    }
  }, [form, t, approvalLevel]);

  const handleLanguageChange = useCallback(
    (value: string): void => {
      if (value === language) return;
      setPendingLang(value);
      setLangConfirmOpen(true);
    },
    [language],
  );

  const confirmLanguageChange = useCallback(async () => {
    if (!pendingLang) return;
    setSavingLang(true);
    try {
      const resp = await api.updateAgentLanguage(pendingLang);
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
      setPendingLang(null);
    }
  }, [pendingLang, t]);

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

  const languageConfirmDialog = (
    <AlertDialog open={langConfirmOpen} onOpenChange={setLangConfirmOpen}>
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle>
            {t("agentConfig.languageConfirmTitle")}
          </AlertDialogTitle>
          <AlertDialogDescription style={{ whiteSpace: "pre-line" }}>
            {t("agentConfig.languageConfirmContent")}
          </AlertDialogDescription>
        </AlertDialogHeader>
        <AlertDialogFooter>
          <AlertDialogCancel onClick={() => setPendingLang(null)}>
            {t("common.cancel")}
          </AlertDialogCancel>
          <AlertDialogAction onClick={confirmLanguageChange}>
            {t("agentConfig.languageConfirmOk")}
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
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
    fetchConfig,
    handleSave,
    handleLanguageChange,
    handleTimezoneChange,
    languageConfirmDialog,
  };
}
