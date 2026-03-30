import { useCallback, useEffect, useState } from "react";
import { message } from "@agentscope-ai/design";
import api from "../../../api";
import type {
  ACPConfig,
  ACPHarnessInfo,
  ACPHarnessConfig,
} from "../../../api/types";
import { useTranslation } from "react-i18next";

function getErrorMessage(error: unknown, fallback: string): string {
  return error instanceof Error && error.message ? error.message : fallback;
}

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
      } catch (error: unknown) {
        const errorMsg = getErrorMessage(error, t("acp.saveError"));
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
            keep_session_default: harness?.keep_session_default ?? false,
            permission_broker_verified:
              harness?.permission_broker_verified ?? false,
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
      const remainingHarnesses = { ...config.harnesses };
      delete remainingHarnesses[key];

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
            keep_session_default: harnessConfig.keep_session_default,
            permission_broker_verified:
              harnessConfig.permission_broker_verified,
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
    async (settings: {
      enabled?: boolean;
      require_approval?: boolean;
      show_tool_calls?: boolean;
      save_dir?: string;
    }) => {
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
