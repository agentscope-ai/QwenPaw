import { MobileAlert } from "@/components/MobileAlert";
import { router } from "expo-router";
import {
  AppWindow,
  Blocks,
  Download,
  Package,
  Search,
} from "lucide-react-native";
import { useCallback, useEffect, useState } from "react";
import {
  Pressable,
  StyleSheet,
  Text,
  TextInput,
  View,
} from "react-native";

import { QwenPawClient } from "../../api/client";
import type { Connection } from "../../api/types";
import { IosGroup, IosRow } from "../../components/IosList";
import { colors, radius, spacing } from "../../theme/tokens";
import { DynamicConfigSheet } from "./DynamicConfigSheet";
import { ModuleEmpty, ModuleError, ModuleFooter, ModuleLoading } from "./ModuleState";

interface PluginInfo {
  id: string;
  name: string;
  version: string;
  description?: string;
  enabled: boolean;
  loaded: boolean;
  plugin_type: string;
}

interface PawAppInfo {
  id: string;
  name: string;
  version: string;
  description?: string;
  status?: string;
}

interface MarketResult {
  source: string;
  slug: string;
  name: string;
  description?: string;
  source_url: string;
  version?: string;
  author?: string;
}

interface MarketSearchResponse {
  results?: MarketResult[];
  errors?: { provider: string; message: string }[];
}

type Sheet = "url" | null;

export function ExtensionsSettings({ connection }: { connection: Connection }) {
  const [plugins, setPlugins] = useState<PluginInfo[] | null>(null);
  const [apps, setApps] = useState<PawAppInfo[] | null>(null);
  const [results, setResults] = useState<MarketResult[]>([]);
  const [query, setQuery] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [searching, setSearching] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);
  const [sheet, setSheet] = useState<Sheet>(null);

  const load = useCallback(async () => {
    try {
      const client = new QwenPawClient(connection);
      const [pluginValue, appValue] = await Promise.all([
        client.inspectModule("/plugins"),
        client.inspectModule("/pawapps"),
      ]);
      setPlugins(Array.isArray(pluginValue) ? pluginValue as PluginInfo[] : []);
      const appList = appValue as { apps?: PawAppInfo[] };
      setApps(Array.isArray(appList?.apps) ? appList.apps : []);
      setError(null);
    } catch (reason) {
      setError(errorMessage(reason));
    }
  }, [connection]);

  useEffect(() => {
    const task = setTimeout(() => void load(), 0);
    return () => clearTimeout(task);
  }, [load]);

  const run = useCallback(async (
    key: string,
    action: () => Promise<unknown>,
    success: string,
  ) => {
    if (busy) return;
    setBusy(key);
    try {
      await action();
      await load();
      MobileAlert.alert(success);
    } catch (reason) {
      MobileAlert.alert("操作失败", errorMessage(reason));
    } finally {
      setBusy(null);
    }
  }, [busy, load]);

  const search = useCallback(async () => {
    const normalized = query.trim();
    if (!normalized || searching) return;
    setSearching(true);
    try {
      const value = await new QwenPawClient(connection).mutateModule<MarketSearchResponse>(
        "/market/search",
        "POST",
        {
          query: normalized,
          provider_pages: {},
          limit: 20,
          lang: "zh-CN",
        },
      );
      setResults(Array.isArray(value.results) ? value.results : []);
      if (!value.results?.length && value.errors?.length) {
        MobileAlert.alert("搜索未完成", value.errors.map((item) => item.message).join("\n"));
      }
    } catch (reason) {
      MobileAlert.alert("搜索失败", errorMessage(reason));
    } finally {
      setSearching(false);
    }
  }, [connection, query, searching]);

  const installSkill = useCallback((item: MarketResult) => {
    MobileAlert.alert("安装到当前 Agent？", item.description || item.name, [
      { text: "取消", style: "cancel" },
      {
        text: "安装",
        onPress: () => void run(item.slug, async () => {
          const task = await new QwenPawClient(connection).mutateModule<{
            task_id?: string;
            status?: string;
          }>("/skills/hub/install/start", "POST", {
            bundle_url: item.source_url,
            version: item.version,
            enable: true,
          });
          if (task.task_id) await waitForInstall(connection, task.task_id);
        }, "Skill 已安装"),
      },
    ]);
  }, [connection, run]);

  const openApp = useCallback((app: PawAppInfo) => {
    router.push({ pathname: "/pawapp/[id]", params: { id: app.id } });
  }, []);

  const removePlugin = useCallback((plugin: PluginInfo) => {
    MobileAlert.alert("卸载扩展？", `${plugin.name} · ${plugin.version}`, [
      { text: "取消", style: "cancel" },
      {
        text: "卸载",
        style: "destructive",
        onPress: () => void run(plugin.id, () => new QwenPawClient(connection)
          .mutateModule(`/plugins/${encodeURIComponent(plugin.id)}`, "DELETE"),
        "扩展已卸载"),
      },
    ]);
  }, [connection, run]);

  if (error) return <ModuleError message={error} onRetry={() => void load()} />;
  if (!plugins || !apps) return <ModuleLoading />;

  return (
    <>
      <IosGroup title="Skill Marketplace">
        <View style={styles.searchRow}>
          <Search color={colors.faint} size={17} />
          <TextInput
            onChangeText={setQuery}
            onSubmitEditing={() => void search()}
            placeholder="搜索 Skill"
            placeholderTextColor={colors.faint}
            returnKeyType="search"
            style={styles.searchInput}
            value={query}
          />
          <Pressable disabled={!query.trim() || searching} onPress={() => void search()}>
            <Text style={styles.searchAction}>{searching ? "搜索中" : "搜索"}</Text>
          </Pressable>
        </View>
        {results.map((item) => (
          <IosRow
            icon={Download}
            key={`${item.source}:${item.slug}`}
            label={item.name}
            onPress={() => installSkill(item)}
            subtitle={item.description || `${item.source} · ${item.author ?? "未知作者"}`}
            trailing="安装"
          />
        ))}
      </IosGroup>

      <IosGroup title={`App Center · ${apps.length}`}>
        {apps.map((app) => (
          <IosRow
            icon={AppWindow}
            key={app.id}
            label={app.name}
            onPress={busy ? undefined : () => void openApp(app)}
            subtitle={app.description || `${app.version} · ${app.status ?? "已安装"}`}
            trailing="打开"
          />
        ))}
      </IosGroup>
      {!apps.length ? (
        <ModuleEmpty icon={AppWindow} title="还没有 PawApp" subtitle="安装 App 类型扩展后会出现在这里。" />
      ) : null}

      <IosGroup title={`已安装扩展 · ${plugins.length}`}>
        <IosRow
          icon={Package}
          label="通过 URL 安装"
          onPress={() => setSheet("url")}
          subtitle="支持本地 QwenPaw 可访问的 HTTPS ZIP"
        />
        {plugins.map((plugin) => (
          <IosRow
            icon={plugin.plugin_type === "app" ? AppWindow : Blocks}
            iconTone="ink"
            key={plugin.id}
            label={plugin.name}
            onPress={busy ? undefined : () => removePlugin(plugin)}
            subtitle={`${plugin.plugin_type} · ${plugin.version}`}
            trailing={plugin.loaded ? "运行中" : "未加载"}
          />
        ))}
      </IosGroup>
      <ModuleFooter>
        搜索、安装和卸载均由当前 QwenPaw 执行；未知第三方 App 使用受控页面容器打开。
      </ModuleFooter>
      {sheet === "url" ? (
        <DynamicConfigSheet
          fields={[{
            name: "source",
            label: "扩展 ZIP URL",
            type: "text",
            required: true,
            placeholder: "https://…/archive.zip",
          }]}
          onClose={() => setSheet(null)}
          onSave={async (values) => {
            await new QwenPawClient(connection).mutateModule(
              "/plugins/install",
              "POST",
              { source: String(values.source || "").trim(), force: false },
            );
            await load();
          }}
          title="安装扩展"
          values={{}}
        />
      ) : null}
    </>
  );
}

async function waitForInstall(connection: Connection, taskId: string): Promise<void> {
  const client = new QwenPawClient(connection);
  for (let attempt = 0; attempt < 120; attempt += 1) {
    const value = await client.inspectModule(
      `/skills/hub/install/status/${encodeURIComponent(taskId)}`,
    ) as { status?: string; error?: string; message?: string };
    if (value.status === "completed" || value.status === "success") return;
    if (["failed", "cancelled"].includes(value.status ?? "")) {
      throw new Error(value.error || value.message || "Skill 安装失败");
    }
    await delay(500);
  }
  throw new Error("Skill 安装超时，请稍后刷新 Skills 查看结果。");
}

function delay(milliseconds: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, milliseconds));
}

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : "扩展操作失败";
}

const styles = StyleSheet.create({
  searchRow: {
    minHeight: 52,
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.sm,
    paddingHorizontal: spacing.md,
    backgroundColor: colors.surface,
  },
  searchInput: {
    flex: 1,
    minHeight: 38,
    paddingHorizontal: 10,
    borderRadius: radius.sm,
    color: colors.ink,
    backgroundColor: colors.searchBackground,
    fontSize: 15,
  },
  searchAction: { color: colors.accentDark, fontSize: 14, fontWeight: "600" },
});
