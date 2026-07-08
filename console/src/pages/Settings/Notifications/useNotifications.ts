import { useCallback, useEffect, useState } from "react";
import {
  notificationsApi,
  type NotificationConfig,
  type NotificationSourceToggles,
} from "../../../api/modules/notifications";

export function useNotifications() {
  const [config, setConfig] = useState<NotificationConfig | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [testing, setTesting] = useState(false);
  const [testResult, setTestResult] = useState<{
    success: boolean;
    message: string;
  } | null>(null);
  const [error, setError] = useState<string | null>(null);

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
      if (!config) return;
      const updated = { ...config, ...patch };
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
    [config],
  );

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
      if (!config) return;
      void updateConfig({
        sources: { ...config.sources, [key]: value },
      });
    },
    [config, updateConfig],
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
