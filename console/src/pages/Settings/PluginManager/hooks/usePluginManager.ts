import { useCallback, useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { Modal } from "antd";
import { useRequest } from "ahooks";
import { useAppMessage } from "@/hooks/useAppMessage";
import {
  fetchPluginCatalog,
  fetchPlugins,
  installPlugin,
  type PluginInfo,
  type PluginUpdateInfo,
  uninstallPlugin,
} from "@/api/modules/plugin";
import {
  buildMarketDownloadUrl,
  fetchMarketPlugins,
  type MarketPluginEntry,
} from "@/api/modules/pluginMarket";
import { compareVersions } from "@/layouts/constants";
import { marketPluginMatches } from "@/utils/marketPluginIdentity";
import { reloadFrontendPlugin, reloadPawApp } from "@/plugins/usePluginLoader";
import { removePluginRuntime } from "@/plugins/pluginRuntimeCleanup";
import { removePluginAppState } from "@/os/osCleanup";

const MARKET_PAGE_SIZE = 50;

function addMarketUpdate(
  updates: Map<string, PluginUpdateInfo>,
  plugin: PluginInfo,
  entry: MarketPluginEntry,
) {
  if (!marketPluginMatches(plugin, entry)) return;
  if (compareVersions(entry.version, plugin.version) <= 0) return;
  updates.set(plugin.id, {
    version: entry.version,
    source: buildMarketDownloadUrl(entry),
    name: entry.display_name,
  });
}

async function reloadInstalledPluginRuntime(plugin: PluginInfo): Promise<void> {
  if (!plugin.frontend_entry) return;
  if (plugin.plugin_type === "app") {
    await reloadPawApp(plugin.id);
    return;
  }
  await reloadFrontendPlugin(plugin.id);
}

export function usePluginManager() {
  const { t } = useTranslation();
  const { message } = useAppMessage();
  const [uninstallingId, setUninstallingId] = useState<string | null>(null);
  const [updates, setUpdates] = useState<Map<string, PluginUpdateInfo>>(
    new Map(),
  );
  const [updatesLoading, setUpdatesLoading] = useState(false);
  const [updatingId, setUpdatingId] = useState<string | null>(null);
  const [updatingAll, setUpdatingAll] = useState(false);
  const updateRequestRef = useRef<AbortController | null>(null);

  const {
    data: plugins,
    loading,
    refresh,
  } = useRequest(fetchPlugins, {
    onError: () => message.error(t("pluginManager.loadFailed")),
  });

  const loadUpdates = useCallback(async (installed: PluginInfo[]) => {
    updateRequestRef.current?.abort();
    if (installed.length === 0) {
      setUpdates(new Map());
      return;
    }

    const controller = new AbortController();
    updateRequestRef.current = controller;
    setUpdatesLoading(true);
    try {
      const nextUpdates = new Map<string, PluginUpdateInfo>();
      const catalog = await fetchPluginCatalog().catch(() => null);
      if (controller.signal.aborted) return;

      for (const entry of catalog?.plugins ?? []) {
        const plugin = installed.find((item) => item.id === entry.plugin_id);
        if (!plugin || !entry.upgrade_available) continue;
        nextUpdates.set(plugin.id, {
          version: entry.version,
          source: entry.install_url,
          name: entry.name,
        });
      }

      const marketEntries: MarketPluginEntry[] = [];
      let page = 1;
      let total = 0;
      try {
        do {
          const result = await fetchMarketPlugins(
            {
              page_number: page,
              page_size: MARKET_PAGE_SIZE,
              sort_by: "updated_time",
            },
            { signal: controller.signal },
          );
          marketEntries.push(...result.plugins);
          total = result.total;
          page += 1;
        } while (!controller.signal.aborted && marketEntries.length < total);
      } catch (err) {
        if (controller.signal.aborted) return;
        console.warn("Failed to check community plugin updates", err);
      }

      if (controller.signal.aborted) return;
      for (const plugin of installed) {
        for (const entry of marketEntries) {
          addMarketUpdate(nextUpdates, plugin, entry);
        }
      }
      setUpdates(nextUpdates);
    } finally {
      if (updateRequestRef.current === controller) {
        updateRequestRef.current = null;
        setUpdatesLoading(false);
      }
    }
  }, []);

  useEffect(() => {
    void loadUpdates(plugins ?? []);
    return () => updateRequestRef.current?.abort();
  }, [loadUpdates, plugins]);

  const updateOne = useCallback(
    async (plugin: PluginInfo) => {
      const update = updates.get(plugin.id);
      if (!update || updatingId !== null || updatingAll) return;
      setUpdatingId(plugin.id);
      try {
        await installPlugin(update.source, { force: true });
        await reloadInstalledPluginRuntime(plugin);
        message.success(t("pluginManager.updateSuccess"));
      } catch (err) {
        message.error(
          err instanceof Error ? err.message : t("pluginManager.updateFailed"),
        );
      } finally {
        await refresh();
        setUpdatingId(null);
      }
    },
    [message, refresh, t, updates, updatingAll, updatingId],
  );

  const updateAll = useCallback(async () => {
    if (updatingAll || updatingId !== null || updates.size === 0) return;
    setUpdatingAll(true);
    const completedIds = new Set<string>();
    try {
      for (const plugin of plugins ?? []) {
        const update = updates.get(plugin.id);
        if (!update) continue;
        setUpdatingId(plugin.id);
        await installPlugin(update.source, { force: true });
        await reloadInstalledPluginRuntime(plugin);
        completedIds.add(plugin.id);
        setUpdates((current) => {
          const next = new Map(current);
          next.delete(plugin.id);
          return next;
        });
      }
      message.success(t("pluginManager.updateAllSuccess"));
    } catch (err) {
      message.error(
        err instanceof Error ? err.message : t("pluginManager.updateFailed"),
      );
    } finally {
      if (completedIds.size > 0) {
        setUpdates((current) => {
          const next = new Map(current);
          for (const id of completedIds) next.delete(id);
          return next;
        });
      }
      await refresh();
      setUpdatingId(null);
      setUpdatingAll(false);
    }
  }, [message, plugins, refresh, t, updatingAll, updatingId, updates]);

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
            if (plugin.plugin_type === "app") {
              removePluginAppState(plugin.id);
            } else {
              removePluginRuntime(plugin.id);
            }
            message.success(t("pluginManager.uninstallSuccess"));
            await refresh();
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

  return {
    plugins,
    loading,
    refresh,
    uninstallingId,
    handleUninstall,
    updates,
    updatesLoading,
    updatingId,
    updatingAll,
    updateOne,
    updateAll,
  };
}
