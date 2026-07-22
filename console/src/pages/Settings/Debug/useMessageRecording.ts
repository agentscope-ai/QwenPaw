import { useCallback, useEffect, useRef, useState } from "react";
import { App } from "antd";
import { useTranslation } from "react-i18next";
import { agentApi } from "@/api/modules/agent";
import type { AgentsRunningConfig } from "@/api/types/agent";

export function useMessageRecording() {
  const { t } = useTranslation();
  const { message: messageApi } = App.useApp();

  const [config, setConfig] = useState<AgentsRunningConfig | null>(null);
  const [loading, setLoading] = useState(false);

  // Local draft state for InputNumber fields (saved on blur)
  const [draftMaxLen, setDraftMaxLen] = useState<number | null>(null);
  const [draftRetention, setDraftRetention] = useState<number>(3);
  const configRef = useRef(config);
  configRef.current = config;

  const enabled = config?.message_recording?.enabled ?? false;
  const maxContentLength =
    config?.message_recording?.max_content_length ?? null;
  const retentionDays = config?.message_recording?.retention_days ?? 3;
  const storagePath = config?.message_recording?.storage_dir ?? "";

  const loadConfig = useCallback(async () => {
    try {
      const data = await agentApi.getAgentRunningConfig();
      setConfig(data);
      setDraftMaxLen(data?.message_recording?.max_content_length ?? null);
      setDraftRetention(data?.message_recording?.retention_days ?? 3);
    } catch {
      // Silently ignore
    }
  }, []);

  useEffect(() => {
    void loadConfig();
  }, [loadConfig]);

  // Sync drafts when config changes externally
  useEffect(() => {
    setDraftMaxLen(maxContentLength);
    setDraftRetention(retentionDays);
  }, [maxContentLength, retentionDays]);

  const updateConfig = useCallback(
    async (
      patch: Partial<NonNullable<AgentsRunningConfig["message_recording"]>>,
    ) => {
      const cfg = configRef.current;
      if (!cfg) return;
      setLoading(true);
      try {
        const current = cfg.message_recording ?? {
          enabled: false,
          max_content_length: null,
          retention_days: 3,
          storage_dir: "",
        };
        const updated: AgentsRunningConfig = {
          ...cfg,
          message_recording: { ...current, ...patch },
        };
        const result = await agentApi.updateAgentRunningConfig(updated);
        setConfig(result);
        void messageApi.success(t("common.saved", "Saved"));
      } catch {
        void messageApi.error(t("common.saveFailed", "Save failed"));
      } finally {
        setLoading(false);
      }
    },
    [messageApi, t],
  );

  const toggleEnabled = useCallback(
    (checked: boolean) => {
      void updateConfig({ enabled: checked });
    },
    [updateConfig],
  );

  const commitMaxContentLength = useCallback(() => {
    const normalized =
      draftMaxLen != null && draftMaxLen >= 1 ? draftMaxLen : null;
    if (normalized !== maxContentLength) {
      void updateConfig({ max_content_length: normalized });
    }
  }, [draftMaxLen, maxContentLength, updateConfig]);

  const commitRetentionDays = useCallback(() => {
    const value = draftRetention;
    if (value >= 1 && value !== retentionDays) {
      void updateConfig({ retention_days: value });
    }
  }, [draftRetention, retentionDays, updateConfig]);

  return {
    enabled,
    storagePath,
    loading,
    toggleEnabled,
    draftMaxLen,
    setDraftMaxLen,
    commitMaxContentLength,
    draftRetention,
    setDraftRetention,
    commitRetentionDays,
  };
}
