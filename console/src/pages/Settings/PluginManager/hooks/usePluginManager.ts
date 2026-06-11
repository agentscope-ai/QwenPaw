import { useState, useCallback } from "react";
import { useTranslation } from "react-i18next";
import { useRequest } from "ahooks";
import { useAppMessage } from "@/hooks/useAppMessage";
import { fetchPlugins, uninstallPlugin } from "@/api/modules/plugin";
import type { PluginInfo } from "@/api/modules/plugin";

export function usePluginManager() {
  const { t } = useTranslation();
  const { message } = useAppMessage();
  const [uninstallingId, setUninstallingId] = useState<string | null>(null);
  const [confirmPlugin, setConfirmPlugin] = useState<PluginInfo | null>(null);

  const {
    data: plugins,
    loading,
    refresh,
  } = useRequest(fetchPlugins, {
    onError: () => message.error(t("pluginManager.loadFailed")),
  });

  const handleUninstall = useCallback((plugin: PluginInfo) => {
    setConfirmPlugin(plugin);
  }, []);

  const confirmUninstall = useCallback(async () => {
    if (!confirmPlugin) return;
    const plugin = confirmPlugin;
    setConfirmPlugin(null);
    setUninstallingId(plugin.id);
    try {
      await uninstallPlugin(plugin.id);
      message.success(t("pluginManager.uninstallSuccess"));
      refresh();
      setTimeout(() => window.location.reload(), 800);
    } catch (err) {
      const msg =
        err instanceof Error ? err.message : t("pluginManager.uninstallFailed");
      message.error(msg);
    } finally {
      setUninstallingId(null);
    }
  }, [confirmPlugin, message, t, refresh]);

  return {
    plugins,
    loading,
    refresh,
    uninstallingId,
    handleUninstall,
    confirmPlugin,
    setConfirmPlugin,
    confirmUninstall,
  };
}
