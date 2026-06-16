import { useState, useCallback } from "react";
import { useTranslation } from "react-i18next";
import { Modal } from "antd";
import { useRequest } from "ahooks";
import { useAppMessage } from "@/hooks/useAppMessage";
import {
  fetchPlugins,
  repairPlugin,
  uninstallPlugin,
} from "@/api/modules/plugin";
import type { PluginInfo } from "@/api/modules/plugin";

export function usePluginManager() {
  const { t } = useTranslation();
  const { message } = useAppMessage();
  const [uninstallingId, setUninstallingId] = useState<string | null>(null);
  const [repairingId, setRepairingId] = useState<string | null>(null);

  const {
    data: plugins,
    loading,
    refresh,
  } = useRequest(fetchPlugins, {
    onError: () => message.error(t("pluginManager.loadFailed")),
  });

  const handleUninstall = useCallback(
    (plugin: PluginInfo) => {
      Modal.confirm({
        title: t("pluginManager.confirmTitle"),
        content: t("pluginManager.uninstallConfirm", { name: plugin.name }),
        okType: "danger",
        okText: t("pluginManager.uninstall"),
        cancelText: t("common.cancel"),
        onOk: async () => {
          setUninstallingId(plugin.id);
          try {
            await uninstallPlugin(plugin.id);
            message.success(t("pluginManager.uninstallSuccess"));
            refresh();
            setTimeout(() => window.location.reload(), 800);
          } catch (err) {
            const msg =
              err instanceof Error
                ? err.message
                : t("pluginManager.uninstallFailed");
            message.error(msg);
          } finally {
            setUninstallingId(null);
          }
        },
      });
    },
    [message, t, refresh],
  );

  const handleRepair = useCallback(
    async (plugin: PluginInfo) => {
      setRepairingId(plugin.id);
      try {
        const result = await repairPlugin(plugin.id);
        message.success(
          `${t("pluginManager.repairSuccess")}: ${result.name}`,
        );
        refresh();
        setTimeout(() => window.location.reload(), 800);
      } catch (err) {
        const msg =
          err instanceof Error ? err.message : t("pluginManager.repairFailed");
        message.error(msg);
      } finally {
        setRepairingId(null);
      }
    },
    [message, t, refresh],
  );

  return {
    plugins,
    loading,
    refresh,
    uninstallingId,
    repairingId,
    handleUninstall,
    handleRepair,
  };
}
