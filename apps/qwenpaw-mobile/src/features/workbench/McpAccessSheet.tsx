import { MobileAlert } from "@/components/MobileAlert";
import { Check, LockKeyhole, Wrench, X } from "lucide-react-native";
import { useCallback, useEffect, useState } from "react";
import {
  Modal,
  Pressable,
  ScrollView,
  StyleSheet,
  Switch,
  Text,
  View,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";

import { QwenPawClient } from "../../api/client";
import type { Connection } from "../../api/types";
import { IosGroup, IosRow } from "../../components/IosList";
import { colors, spacing } from "../../theme/tokens";
import { ModuleEmpty, ModuleLoading } from "./ModuleState";

type AccessEffect = "allow" | "ask" | "deny";

interface McpClient {
  key: string;
  name: string;
  tools?: string[] | null;
}

interface McpTool {
  name: string;
  description?: string;
  enabled: boolean;
}

interface McpPolicy {
  default_effect: AccessEffect;
  client_overrides: unknown[];
  tool_defaults: { tool_name: string; effect: AccessEffect }[];
  tool_overrides: unknown[];
  unmanaged_rules_count: number;
}

export function McpAccessSheet({
  client,
  connection,
  onChanged,
  onClose,
}: {
  client: McpClient;
  connection: Connection;
  onChanged: () => Promise<void>;
  onClose: () => void;
}) {
  const [policy, setPolicy] = useState<McpPolicy | null>(null);
  const [tools, setTools] = useState<McpTool[] | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    const api = new QwenPawClient(connection);
    const [policyResult, toolsResult] = await Promise.allSettled([
      api.inspectModule(`/mcp/policy/${encodeURIComponent(client.key)}`),
      api.inspectModule(`/mcp/tools/${encodeURIComponent(client.key)}`),
    ]);
    if (policyResult.status === "fulfilled") {
      setPolicy(policyResult.value as McpPolicy);
    }
    setTools(toolsResult.status === "fulfilled" && Array.isArray(toolsResult.value)
      ? toolsResult.value as McpTool[]
      : []);
  }, [client.key, connection]);

  useEffect(() => {
    const task = setTimeout(() => void load(), 0);
    return () => clearTimeout(task);
  }, [load]);

  const savePolicy = async (next: McpPolicy) => {
    if (busy) return;
    setBusy(true);
    try {
      const saved = await new QwenPawClient(connection).mutateModule<McpPolicy>(
        `/mcp/policy/${encodeURIComponent(client.key)}`,
        "PUT",
        next,
      );
      setPolicy(saved);
      await onChanged();
    } catch (reason) {
      MobileAlert.alert("权限保存失败", errorMessage(reason));
    } finally {
      setBusy(false);
    }
  };

  const chooseDefault = () => {
    if (!policy) return;
    chooseEffect("服务默认权限", policy.default_effect, (effect) => {
      void savePolicy({ ...policy, default_effect: effect });
    });
  };

  const chooseToolEffect = (tool: McpTool) => {
    if (!policy) return;
    const current = policy.tool_defaults.find((item) => item.tool_name === tool.name)?.effect;
    MobileAlert.alert(tool.name, "选择该工具的默认执行权限", [
      {
        text: "跟随服务默认",
        onPress: () => void savePolicy({
          ...policy,
          tool_defaults: policy.tool_defaults.filter((item) => item.tool_name !== tool.name),
        }),
      },
      ...effectActions(current, (effect) => void savePolicy({
        ...policy,
        tool_defaults: [
          ...policy.tool_defaults.filter((item) => item.tool_name !== tool.name),
          { tool_name: tool.name, effect },
        ],
      })),
      { text: "取消", style: "cancel" },
    ]);
  };

  const toggleTool = async (tool: McpTool) => {
    if (!tools || busy) return;
    const next = tools.map((item) => item.name === tool.name
      ? { ...item, enabled: !item.enabled }
      : item);
    setTools(next);
    setBusy(true);
    try {
      const enabledNames = next.filter((item) => item.enabled).map((item) => item.name);
      const saved = await new QwenPawClient(connection).mutateModule<McpTool[]>(
        `/mcp/tools/${encodeURIComponent(client.key)}`,
        "PUT",
        { tools: enabledNames.length === next.length ? null : enabledNames },
      );
      setTools(saved);
      await onChanged();
    } catch (reason) {
      setTools(tools);
      MobileAlert.alert("工具开关保存失败", errorMessage(reason));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Modal animationType="slide" presentationStyle="pageSheet">
      <SafeAreaView style={styles.root}>
        <View style={styles.header}>
          <Pressable accessibilityLabel="关闭" onPress={onClose} style={styles.action}>
            <X color={colors.ink} size={22} />
          </Pressable>
          <View style={styles.titleBlock}>
            <Text numberOfLines={1} style={styles.title}>{client.name}</Text>
            <Text style={styles.subtitle}>工具与执行权限</Text>
          </View>
          <View style={styles.action} />
        </View>
        <ScrollView contentContainerStyle={styles.content}>
          {!policy || !tools ? <ModuleLoading /> : (
            <>
              <IosGroup title="访问控制">
                <IosRow
                  icon={LockKeyhole}
                  label="服务默认权限"
                  onPress={chooseDefault}
                  subtitle="没有更具体规则时采用"
                  trailing={effectLabel(policy.default_effect)}
                />
                {(policy.client_overrides.length || policy.tool_overrides.length ||
                  policy.unmanaged_rules_count) ? (
                  <IosRow
                    icon={Check}
                    iconTone="ink"
                    label="精细规则"
                    subtitle="已保存的来源、用户和外部规则继续生效"
                    trailing={String(
                      policy.client_overrides.length + policy.tool_overrides.length +
                      policy.unmanaged_rules_count,
                    )}
                  />
                ) : null}
              </IosGroup>
              {tools.length ? (
                <IosGroup title={`可用工具 · ${tools.length}`}>
                  {tools.map((tool) => {
                    const effect = policy.tool_defaults.find(
                      (item) => item.tool_name === tool.name,
                    )?.effect;
                    return (
                      <IosRow
                        accessory={(
                          <Switch
                            disabled={busy}
                            onValueChange={() => void toggleTool(tool)}
                            trackColor={{ false: colors.hairline, true: colors.accent }}
                            value={tool.enabled}
                          />
                        )}
                        icon={Wrench}
                        iconTone="ink"
                        key={tool.name}
                        label={tool.name}
                        onPress={() => chooseToolEffect(tool)}
                        subtitle={`${effect ? effectLabel(effect) : "跟随服务默认"}${tool.description ? ` · ${tool.description}` : ""}`}
                      />
                    );
                  })}
                </IosGroup>
              ) : (
                <ModuleEmpty
                  icon={Wrench}
                  title="暂时无法读取工具"
                  subtitle="服务离线时仍可编辑默认权限；连接后工具会自动出现。"
                />
              )}
            </>
          )}
        </ScrollView>
      </SafeAreaView>
    </Modal>
  );
}

function chooseEffect(
  title: string,
  current: AccessEffect,
  onChoose: (effect: AccessEffect) => void,
) {
  MobileAlert.alert(title, undefined, [
    ...effectActions(current, onChoose),
    { text: "取消", style: "cancel" },
  ]);
}

function effectActions(
  current: AccessEffect | undefined,
  onChoose: (effect: AccessEffect) => void,
) {
  return (["allow", "ask", "deny"] as AccessEffect[]).map((effect) => ({
    text: `${current === effect ? "✓ " : ""}${effectLabel(effect)}`,
    onPress: () => onChoose(effect),
  }));
}

function effectLabel(effect: AccessEffect): string {
  if (effect === "allow") return "允许";
  if (effect === "deny") return "拒绝";
  return "每次询问";
}

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : "操作失败";
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.groupedBackground },
  header: {
    minHeight: 58,
    flexDirection: "row",
    alignItems: "center",
    borderBottomWidth: StyleSheet.hairlineWidth,
    borderBottomColor: colors.hairline,
    backgroundColor: colors.tabBar,
  },
  action: { width: 54, height: 54, alignItems: "center", justifyContent: "center" },
  titleBlock: { flex: 1, alignItems: "center", gap: 2 },
  title: { color: colors.ink, fontSize: 17, fontWeight: "600" },
  subtitle: { color: colors.muted, fontSize: 11 },
  content: { gap: spacing.lg, padding: spacing.md, paddingBottom: spacing.xxl },
});
