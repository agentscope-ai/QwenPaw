import { useCallback, useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import {
  notificationsApi,
  type NotificationConfig,
  type NotificationSourceToggles,
} from "../../../api/modules/notifications";

export function useNotifications() {
  const { i18n } = useTranslation();
  const [config, setConfig] = useState<NotificationConfig | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [testing, setTesting] = useState(false);
  const [testResult, setTestResult] = useState<{
    success: boolean;
    message: string;
  } | null>(null);
  const [error, setError] = useState<string | null>(null);

  const configRef = useRef(config);
  configRef.current = config;

  const fetchConfig = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await notificationsApi.getConfig();
      setConfig(data);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void fetchConfig();
  }, [fetchConfig]);

  const updateConfig = useCallback(
    async (patch: Partial<NotificationConfig>) => {
      const current = configRef.current;
      if (!current) return;
      const updated = { ...current, ...patch };
      setSaving(true);
      try {
        const result = await notificationsApi.updateConfig(updated);
        setConfig(result);
      } catch (err: unknown) {
        setError(err instanceof Error ? err.message : String(err));
      } finally {
        setSaving(false);
      }
    },
    [],
  );

  // Auto-sync console language to notification config
  useEffect(() => {
    if (!config || loading || saving) return;
    const consoleLang = (i18n.resolvedLanguage ?? i18n.language ?? "en").split(
      "-",
    )[0];
    const configLang = (config.language || "en").split("-")[0];
    if (consoleLang !== configLang) {
      void updateConfig({ language: consoleLang });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [config?.language, i18n.language, loading]);

  const toggleEnabled = useCallback(
    (enabled: boolean) => updateConfig({ enabled }),
    [updateConfig],
  );

  const toggleSound = useCallback(
    (sound: boolean) => updateConfig({ sound }),
    [updateConfig],
  );

  const updateMinInterval = useCallback(
    (min_interval_seconds: number) => updateConfig({ min_interval_seconds }),
    [updateConfig],
  );

  const toggleSource = useCallback(
    (key: keyof NotificationSourceToggles, value: boolean) => {
      const current = configRef.current;
      if (!current) return;
      void updateConfig({
        sources: { ...current.sources, [key]: value },
      });
    },
    [updateConfig],
  );

  const updateAgentIds = useCallback(
    (agent_ids: string[] | null) => updateConfig({ agent_ids }),
    [updateConfig],
  );

  const sendTest = useCallback(async () => {
    setTesting(true);
    setTestResult(null);
    try {
      const result = await notificationsApi.sendTest();
      setTestResult(result);
    } catch (err: unknown) {
      setTestResult({
        success: false,
        message: err instanceof Error ? err.message : String(err),
      });
    } finally {
      setTesting(false);
    }
  }, []);

  return {
    config,
    loading,
    saving,
    testing,
    testResult,
    error,
    fetchConfig,
    toggleEnabled,
    toggleSound,
    updateMinInterval,
    toggleSource,
    updateAgentIds,
    sendTest,
  };
}
