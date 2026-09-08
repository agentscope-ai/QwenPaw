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
const MARKET_MAX_PAGES = 20;

function addMarketUpdate(
  updates: Map<string, PluginUpdateInfo>,
  plugin: PluginInfo,
  entry: MarketPluginEntry,
) {
  if (!marketPluginMatches(plugin, entry)) return;
  if (compareVersions(entry.version, plugin.version) <= 0) return;
  const currentUpdate = updates.get(plugin.id);
  if (
    currentUpdate &&
    compareVersions(currentUpdate.version, entry.version) >= 0
  ) {
    return;
  }
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
  const marketEntriesRef = useRef<MarketPluginEntry[] | null>(null);

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
        const currentUpdate = nextUpdates.get(plugin.id);
        if (
          currentUpdate &&
          compareVersions(currentUpdate.version, entry.version) >= 0
        ) {
          continue;
        }
        nextUpdates.set(plugin.id, {
          version: entry.version,
          source: entry.install_url,
          name: entry.name,
        });
      }

      let marketEntries = marketEntriesRef.current;
      if (marketEntries === null) {
        marketEntries = [];
        const seenEntryIds = new Set<string>();
        let page = 1;
        let total = Number.POSITIVE_INFINITY;
        try {
          while (
            !controller.signal.aborted &&
            page <= MARKET_MAX_PAGES &&
            marketEntries.length < total
          ) {
            const result = await fetchMarketPlugins(
              {
                page_number: page,
                page_size: MARKET_PAGE_SIZE,
                sort_by: "updated_time",
              },
              { signal: controller.signal },
            );
            total = result.total;
            if (result.plugins.length === 0) break;

            const previousSize = seenEntryIds.size;
            for (const entry of result.plugins) {
              if (seenEntryIds.has(entry.id)) continue;
              seenEntryIds.add(entry.id);
              marketEntries.push(entry);
            }
            if (seenEntryIds.size === previousSize) break;
            page += 1;
          }
          marketEntriesRef.current = marketEntries;
        } catch (err) {
          if (controller.signal.aborted) return;
          console.warn("Failed to check community plugin updates", err);
        }
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

  const refreshUpdates = useCallback(() => {
    marketEntriesRef.current = null;
    return refresh();
  }, [refresh]);

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
    const failedPluginNames: string[] = [];
    try {
      for (const plugin of plugins ?? []) {
        const update = updates.get(plugin.id);
        if (!update) continue;
        setUpdatingId(plugin.id);
        try {
          await installPlugin(update.source, { force: true });
          await reloadInstalledPluginRuntime(plugin);
          completedIds.add(plugin.id);
          setUpdates((current) => {
            const next = new Map(current);
            next.delete(plugin.id);
            return next;
          });
        } catch {
          failedPluginNames.push(plugin.name);
        }
      }
      if (failedPluginNames.length === 0) {
        message.success(t("pluginManager.updateAllSuccess"));
      } else {
        message.error(
          t("pluginManager.updateAllResult", {
            succeeded: completedIds.size,
            failed: failedPluginNames.length,
            names: failedPluginNames.join(", "),
          }),
        );
      }
    } finally {
      if (completedIds.size > 0) {
        setUpdates((current) => {
          const next = new Map(current);
          for (const id of completedIds) next.delete(id);
          return next;
        });
      }
      try {
        await refresh();
      } finally {
        setUpdatingId(null);
        setUpdatingAll(false);
      }
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
    refreshUpdates,
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
