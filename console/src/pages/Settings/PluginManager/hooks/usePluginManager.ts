import { useState, useCallback } from "react";
import { useTranslation } from "react-i18next";
import { Modal } from "antd";
import { useRequest } from "ahooks";
import { useAppMessage } from "@/hooks/useAppMessage";
import {
  fetchPlugins,
  uninstallPlugin,
  exportPlugin,
} from "@/api/modules/plugin";
import type { PluginInfo } from "@/api/modules/plugin";

export function usePluginManager() {
  const { t } = useTranslation();
  const { message } = useAppMessage();
  const [uninstallingId, setUninstallingId] = useState<string | null>(null);
  const [exportingId, setExportingId] = useState<string | null>(null);

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

  const handleExport = useCallback(
    (plugin: PluginInfo) => {
      setExportingId(plugin.id);
      exportPlugin(plugin.id)
        .then(() => {
          message.success(t("pluginManager.exportSuccess"));
        })
        .catch((err) => {
          const msg =
            err instanceof Error
              ? err.message
              : t("pluginManager.exportFailed");
          message.error(msg);
        })
        .finally(() => setExportingId(null));
    },
    [message, t],
  );

  return {
    plugins,
    loading,
    refresh,
    uninstallingId,
    handleUninstall,
    exportingId,
    handleExport,
  };
}
