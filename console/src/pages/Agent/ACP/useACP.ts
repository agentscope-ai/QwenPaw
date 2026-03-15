import { useCallback, useEffect, useState } from "react";
import { message } from "@agentscope-ai/design";
import api from "../../../api";
import type { ACPConfig, ACPHarnessInfo, ACPHarnessConfig } from "../../../api/types";
import { useTranslation } from "react-i18next";

export function useACP() {
  const { t } = useTranslation();
  const [config, setConfig] = useState<ACPConfig | null>(null);
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);

  const loadConfig = useCallback(async () => {
    setLoading(true);
    try {
      const data = await api.getACPConfig();
      setConfig(data);
    } catch (error) {
      console.error("Failed to load ACP config:", error);
      message.error(t("acp.loadError"));
    } finally {
      setLoading(false);
    }
  }, [t]);

  useEffect(() => {
    loadConfig();
  }, [loadConfig]);

  const saveConfig = useCallback(
    async (newConfig: ACPConfig) => {
      setSaving(true);
      try {
        const updated = await api.updateACPConfig(newConfig);
        setConfig(updated);
        message.success(t("acp.saveSuccess"));
        return true;
      } catch (error: any) {
        const errorMsg = error?.message || t("acp.saveError");
        message.error(errorMsg);
        return false;
      } finally {
        setSaving(false);
      }
    },
    [t],
  );

  const toggleHarnessEnabled = useCallback(
    async (key: string) => {
      if (!config) return false;
      const harness = config.harnesses[key];
      if (!harness) return false;

      const newConfig = {
        ...config,
        harnesses: {
          ...config.harnesses,
          [key]: {
            ...harness,
            enabled: !harness.enabled,
          },
        },
      };

      const success = await saveConfig(newConfig);
      if (success) {
        message.success(
          harness.enabled ? t("acp.disableSuccess") : t("acp.enableSuccess"),
        );
      }
      return success;
    },
    [config, saveConfig, t],
  );

  const updateHarness = useCallback(
    async (key: string, updates: Partial<ACPHarnessInfo>) => {
      if (!config) return false;
      const harness = config.harnesses[key];

      const newConfig = {
        ...config,
        harnesses: {
          ...config.harnesses,
          [key]: {
            command: harness?.command ?? "",
            args: harness?.args ?? [],
            env: harness?.env ?? {},
            enabled: harness?.enabled ?? false,
            ...updates,
          },
        },
      };

      return await saveConfig(newConfig);
    },
    [config, saveConfig],
  );

  const deleteHarness = useCallback(
    async (key: string) => {
      if (!config) return false;
      const { [key]: _, ...remainingHarnesses } = config.harnesses;

      const newConfig = {
        ...config,
        harnesses: remainingHarnesses,
      };

      const success = await saveConfig(newConfig);
      if (success) {
        message.success(t("acp.deleteSuccess"));
      }
      return success;
    },
    [config, saveConfig, t],
  );

  const createHarness = useCallback(
    async (key: string, harnessConfig: ACPHarnessConfig) => {
      if (!config) return false;

      if (config.harnesses[key]) {
        message.error(t("acp.keyExists"));
        return false;
      }

      const newConfig = {
        ...config,
        harnesses: {
          ...config.harnesses,
          [key]: {
            command: harnessConfig.command,
            args: harnessConfig.args,
            env: harnessConfig.env,
            enabled: harnessConfig.enabled,
          },
        },
      };

      const success = await saveConfig(newConfig);
      if (success) {
        message.success(t("acp.createSuccess"));
      }
      return success;
    },
    [config, saveConfig, t],
  );

  const updateGlobalSettings = useCallback(
    async (settings: { enabled?: boolean; require_approval?: boolean; save_dir?: string }) => {
      if (!config) return false;

      const newConfig = {
        ...config,
        ...settings,
      };

      return await saveConfig(newConfig);
    },
    [config, saveConfig],
  );

  const harnesses: ACPHarnessInfo[] = config
    ? Object.entries(config.harnesses).map(([key, h]) => ({
        key,
        name: key,
        ...h,
      }))
    : [];

  return {
    config,
    harnesses,
    loading,
    saving,
    loadConfig,
    saveConfig,
    toggleHarnessEnabled,
    updateHarness,
    deleteHarness,
    createHarness,
    updateGlobalSettings,
  };
}
