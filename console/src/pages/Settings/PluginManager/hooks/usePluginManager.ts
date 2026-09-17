import { useState, useCallback } from "react";
import { useTranslation } from "react-i18next";
import { Modal } from "antd";
import { useRequest } from "ahooks";
import { useAppMessage } from "@/hooks/useAppMessage";
import {
  fetchPlugins,
  setPluginEnabled,
  uninstallPlugin,
  updatePluginAudience,
} from "@/api/modules/plugin";
import type { PluginInfo } from "@/api/modules/plugin";

export function usePluginManager() {
  const { t } = useTranslation();
  const { message } = useAppMessage();
  const [uninstallingId, setUninstallingId] = useState<string | null>(null);

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

  const handleEnabledChange = useCallback(
    async (plugin: PluginInfo, enabled: boolean) => {
      try {
        await setPluginEnabled(plugin.id, enabled);
        message.success(enabled ? "插件已启用" : "插件已停用");
        refresh();
      } catch (error) {
        message.error(
          error instanceof Error ? error.message : "插件状态更新失败",
        );
      }
    },
    [message, refresh],
  );

  const handleAudienceChange = useCallback(
    async (
      plugin: PluginInfo,
      mode: "all_members" | "selected_users",
      selectedUserIds: string[] = plugin.selected_user_ids ?? [],
    ) => {
      try {
        await updatePluginAudience(plugin.id, {
          mode,
          selected_user_ids: mode === "selected_users" ? selectedUserIds : [],
        });
        message.success("应用授权已更新");
        refresh();
      } catch (error) {
        message.error(
          error instanceof Error ? error.message : "应用授权更新失败",
        );
      }
    },
    [message, refresh],
  );

  return {
    plugins,
    loading,
    refresh,
    uninstallingId,
    handleUninstall,
    handleEnabledChange,
    handleAudienceChange,
  };
}
