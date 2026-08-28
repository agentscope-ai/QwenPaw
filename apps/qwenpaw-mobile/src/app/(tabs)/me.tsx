import { MobileAlert } from "@/components/MobileAlert";
import Constants from "expo-constants";
import { router, useFocusEffect } from "expo-router";
import {
  Bot,
  Bell,
  Cloud,
  Info,
  LogOut,
  LogIn,
  MoreHorizontal,
  Plus,
  RefreshCw,
  Server,
  ShieldCheck,
  SunMoon,
  Trash2,
} from "lucide-react-native";
import { useCallback, useState } from "react";
import { Pressable, ScrollView, StyleSheet, Text, View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";

import { IosHeader } from "../../components/IosHeader";
import { IosGroup, IosRow } from "../../components/IosList";
import { AgentAvatar } from "../../features/agents/AgentAvatar";
import { workspaceName } from "../../features/workspaces/WorkspaceSwitcher";
import { resolveAgentAppearance } from "../../storage/agentAppearance";
import { connectionKey } from "../../storage/connection";
import {
  loadPlatformSession,
  type PlatformSession,
} from "../../storage/platformSession";
import { useAppStore } from "../../store/app";
import {
  AppearanceSheet,
  themePreferenceLabel,
} from "../../theme/AppearanceSheet";
import { useAppTheme } from "../../theme/ThemeProvider";
import { colors, radius, spacing } from "../../theme/tokens";

export default function MeScreen() {
  const connection = useAppStore((state) => state.connection);
  const connections = useAppStore((state) => state.connections);
  const agents = useAppStore((state) => state.agents);
  const connect = useAppStore((state) => state.connect);
  const switchConnection = useAppStore((state) => state.switchConnection);
  const removeConnection = useAppStore((state) => state.removeConnection);
  const logoutPlatform = useAppStore((state) => state.logoutPlatform);
  const appearances = useAppStore((state) => state.agentAppearances);
  const { preference } = useAppTheme();
  const [platformSession, setPlatformSession] =
    useState<PlatformSession | null>(null);
  const [appearanceOpen, setAppearanceOpen] = useState(false);
  const activeAgent = agents.find((agent) => agent.id === connection?.agentId);
  const activeAppearance = resolveAgentAppearance(
    appearances,
    connection,
    activeAgent,
  );

  useFocusEffect(
    useCallback(() => {
      void loadPlatformSession().then(setPlatformSession);
    }, []),
  );

  const confirmDisconnect = (target = connection) => {
    if (!target) return;
    const active = connection
      ? connectionKey(target) === connectionKey(connection)
      : false;
    MobileAlert.alert(
      `取消配对${workspaceName(target)}？`,
      connections.length === 1
        ? "这是最后一只 QwenPaw，取消配对后需要重新扫码或登录。"
        : active
          ? "取消后会自动切换到另一只已配对的 QwenPaw。"
          : "只会移除这只 QwenPaw，当前连接不受影响。",
      [
        { text: "取消", style: "cancel" },
        {
          text: "移除",
          style: "destructive",
          onPress: () => void removePairedConnection(target),
        },
      ],
    );
  };

  const removePairedConnection = async (target: typeof connection) => {
    if (!target) return;
    await removeConnection(connectionKey(target));
    const state = useAppStore.getState();
    router.replace(
      state.connection && state.status === "ready" ? "/chats" : "/",
    );
  };

  const reconnect = () => {
    if (!connection) return;
    void connect(connection).catch((error) => {
      MobileAlert.alert(
        "重新连接失败",
        error instanceof Error ? error.message : "请检查服务器状态。",
      );
    });
  };

  const confirmPlatformLogout = () => {
    MobileAlert.alert(
      "退出 Platform？",
      "将退出账号并取消所有 Platform 云端 QwenPaw 配对；本机和私人部署不受影响。",
      [
        { text: "取消", style: "cancel" },
        {
          text: "退出 Platform",
          style: "destructive",
          onPress: () => void logoutPlatformAccount(),
        },
      ],
    );
  };

  const logoutPlatformAccount = async () => {
    const wasPlatformActive = connection?.source === "platform";
    try {
      await logoutPlatform();
      setPlatformSession(null);
      if (!wasPlatformActive) return;
      const state = useAppStore.getState();
      router.replace(
        state.connection && state.status === "ready" ? "/chats" : "/",
      );
    } catch (error) {
      MobileAlert.alert(
        "退出失败",
        error instanceof Error ? error.message : "请稍后重试。",
      );
    }
  };

  return (
    <SafeAreaView edges={["top"]} style={styles.root}>
      <IosHeader title="账户与设备" onBack={() => router.back()} />
      <ScrollView contentContainerStyle={styles.content}>
        <Pressable
          accessibilityRole="button"
          onPress={() => router.push("/agents")}
          style={({ pressed }) => [
            styles.profile,
            pressed && styles.profilePressed,
          ]}
        >
          <AgentAvatar
            active
            avatarUri={activeAppearance.avatarUri}
            size={58}
          />
          <View style={styles.profileText}>
            <Text maxFontSizeMultiplier={1.4} style={styles.profileName}>
              {activeAppearance.name}
            </Text>
            <Text
              maxFontSizeMultiplier={1.3}
              numberOfLines={1}
              style={styles.profileMeta}
            >
              {connection?.source === "platform"
                ? "Platform 云端 QwenPaw"
                : "私人部署的 QwenPaw"}
            </Text>
          </View>
          <View style={styles.online} />
        </Pressable>

        <IosGroup title="安全与外观">
          <IosRow
            icon={ShieldCheck}
            label="安全"
            onPress={() => router.push("/module/security")}
            subtitle="Sandbox、Tool Guard、File Guard 与扫描"
          />
          <IosRow
            icon={Bell}
            label="通知与待办"
            onPress={() => router.push("/notifications")}
            subtitle="完成、等待输入、审批和失败提醒"
          />
          <IosRow
            icon={SunMoon}
            label="外观"
            onPress={() => setAppearanceOpen(true)}
            subtitle="浅色、深色或跟随系统"
            trailing={themePreferenceLabel(preference)}
          />
        </IosGroup>

        <IosGroup title="已配对的 QwenPaw">
          {connections.map((item) => {
            const active = connection
              ? connectionKey(item) === connectionKey(connection)
              : false;
            return (
              <IosRow
                key={connectionKey(item)}
                icon={item.source === "platform" ? Cloud : Server}
                label={workspaceName(item)}
                onPress={() =>
                  active
                    ? undefined
                    : void switchConnection(connectionKey(item)).catch(
                        (error) => {
                          MobileAlert.alert(
                            "切换失败",
                            error instanceof Error
                              ? error.message
                              : "请稍后重试。",
                          );
                        },
                      )
                }
                subtitle={item.baseUrl}
                accessory={(
                  <View style={styles.connectionAccessory}>
                    <Text style={styles.connectionState}>
                      {active ? "当前" : "切换"}
                    </Text>
                    <Pressable
                      accessibilityLabel={`取消配对${workspaceName(item)}`}
                      accessibilityRole="button"
                      hitSlop={8}
                      onPress={(event) => {
                        event.stopPropagation();
                        confirmDisconnect(item);
                      }}
                      style={({ pressed }) => [
                        styles.connectionAction,
                        pressed && styles.profilePressed,
                      ]}
                    >
                      <MoreHorizontal color={colors.muted} size={20} />
                    </Pressable>
                  </View>
                )}
              />
            );
          })}
          <IosRow
            icon={Plus}
            label="再配对一只 QwenPaw"
            onPress={() => router.push({ pathname: "/", params: { add: "1" } })}
            subtitle="同时保留私人部署和 Platform 云端"
          />
        </IosGroup>

        <IosGroup title="当前 Agent">
          <IosRow
            icon={Bot}
            iconTone="ink"
            label={activeAppearance.name}
            onPress={() => router.push("/agents")}
            subtitle="头像、昵称与 Agent 切换"
            trailing={activeAgent?.id}
          />
          <IosRow
            icon={RefreshCw}
            label="重新连接"
            onPress={reconnect}
            subtitle="刷新 Agent 和会话数据"
          />
        </IosGroup>

        <IosGroup title="Platform 账号">
          <IosRow
            icon={Cloud}
            label="Platform 账号"
            subtitle={
              platformSession
                ? platformSession.username || "已安全登录"
                : "社区浏览无需登录，互动时再登录"
            }
            trailing={platformSession ? "已登录" : "未登录"}
          />
          {platformSession ? (
            <IosRow
              destructive
              icon={LogOut}
              iconTone="ink"
              label="退出 Platform"
              onPress={confirmPlatformLogout}
            />
          ) : (
            <IosRow
              icon={LogIn}
              label="登录 Platform"
              onPress={() => router.push("/community/login")}
              subtitle="启用点赞、评论和发布"
            />
          )}
        </IosGroup>

        <IosGroup title="设备">
          <IosRow
            icon={ShieldCheck}
            label="配对状态"
            subtitle="除非主动移除，否则此设备保持配对"
            trailing="已配对"
          />
        </IosGroup>

        <IosGroup title="关于">
          <IosRow
            icon={Info}
            iconTone="ink"
            label="QwenPaw Mobile"
            trailing={Constants.expoConfig?.version || "1.0.0"}
          />
        </IosGroup>

        <IosGroup>
          <IosRow
            destructive
            icon={Trash2}
            iconTone="ink"
            label="移除这只 QwenPaw"
            onPress={() => confirmDisconnect()}
          />
        </IosGroup>
      </ScrollView>
      <AppearanceSheet
        onClose={() => setAppearanceOpen(false)}
        visible={appearanceOpen}
      />
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.groupedBackground },
  content: {
    width: "100%",
    maxWidth: 760,
    alignSelf: "center",
    gap: spacing.lg,
    paddingHorizontal: spacing.md,
    paddingBottom: spacing.xxl,
  },
  profile: {
    minHeight: 98,
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.md,
    padding: spacing.md,
    borderRadius: radius.md,
    backgroundColor: colors.surface,
  },
  profilePressed: { backgroundColor: colors.pressed },
  profileText: { flex: 1, minWidth: 0, gap: 4 },
  profileName: { color: colors.ink, fontSize: 20, fontWeight: "600" },
  profileMeta: { color: colors.muted, fontSize: 13 },
  online: {
    width: 9,
    height: 9,
    borderRadius: 5,
    backgroundColor: colors.accent,
  },
  connectionAction: {
    width: 44,
    height: 44,
    alignItems: "center",
    justifyContent: "center",
    borderRadius: 22,
  },
  connectionAccessory: {
    flexDirection: "row",
    alignItems: "center",
  },
  connectionState: { color: colors.muted, fontSize: 13 },
});
