import type {
  NotificationPreferences,
  NotificationPreview,
} from "@qwenpaw/api-contract";
import {
  Bell,
  Check,
  CircleAlert,
  Eye,
  MessageCircleQuestion,
  ShieldCheck,
  TriangleAlert,
  type LucideIcon,
} from "lucide-react-native";
import { router, useFocusEffect } from "expo-router";
import { useCallback, useState } from "react";
import {
  ActivityIndicator,
  ScrollView,
  StyleSheet,
  Switch,
  Text,
  View,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";

import { IosHeader } from "../components/IosHeader";
import { IosGroup, IosRow } from "../components/IosList";
import {
  disablePushSubscription,
  syncPushSubscription,
  type NotificationSetupState,
} from "../notifications/service";
import {
  loadNotificationPreferences,
  saveNotificationPreferences,
} from "../notifications/storage";
import { useAppStore } from "../store/app";
import { colors, radius, spacing } from "../theme/tokens";

const previewOptions: {
  label: string;
  subtitle: string;
  value: NotificationPreview;
}[] = [
  { label: "显示标题和内容", subtitle: "锁屏可看到会话摘要", value: "full" },
  {
    label: "仅显示通知类型",
    subtitle: "推荐，不显示会话内容",
    value: "title_only",
  },
  { label: "隐藏全部内容", subtitle: "锁屏只显示有新通知", value: "hidden" },
];

export default function NotificationSettingsScreen() {
  const connection = useAppStore((state) => state.connection);
  const [preferences, setPreferences] =
    useState<NotificationPreferences | null>(null);
  const [setupState, setSetupState] =
    useState<NotificationSetupState>("disabled");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useFocusEffect(
    useCallback(() => {
      if (!connection) return;
      let active = true;
      void loadNotificationPreferences(connection).then(async (loaded) => {
        if (!active) return;
        setPreferences(loaded);
        if (!loaded.enabled) {
          setSetupState("disabled");
          return;
        }
        const result = await syncPushSubscription(
          connection,
          loaded,
          false,
        ).catch(() => null);
        if (active && result) setSetupState(result.state);
      });
      return () => {
        active = false;
      };
    }, [connection]),
  );

  const save = async (
    next: NotificationPreferences,
    requestPermission = false,
  ) => {
    if (!connection) return;
    setSaving(true);
    setError(null);
    setPreferences(next);
    try {
      await saveNotificationPreferences(connection, next);
      if (!next.enabled) {
        const disabled = await disablePushSubscription(connection, next);
        setPreferences(disabled);
        setSetupState("disabled");
      } else {
        const result = await syncPushSubscription(
          connection,
          next,
          requestPermission,
        );
        setPreferences(result.preferences);
        setSetupState(result.state);
      }
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "通知设置保存失败");
    } finally {
      setSaving(false);
    }
  };

  const update = (patch: Partial<NotificationPreferences>) => {
    if (!preferences || saving) return;
    void save({ ...preferences, ...patch });
  };

  return (
    <SafeAreaView edges={["top"]} style={styles.root}>
      <IosHeader title="通知与待办" onBack={() => router.back()} />
      <ScrollView contentContainerStyle={styles.content}>
        <View style={styles.hero}>
          <View style={styles.heroIcon}>
            <Bell color={colors.accentDark} size={24} />
          </View>
          <View style={styles.heroText}>
            <Text style={styles.heroTitle}>离开 App 也不错过任务</Text>
            <Text style={styles.heroSubtitle}>
              完成、等待输入、审批和失败会通过系统通知提醒你。
            </Text>
          </View>
          {saving ? <ActivityIndicator color={colors.accent} /> : null}
        </View>

        {preferences ? (
          <>
            <IosGroup title="系统通知">
              <IosRow
                accessory={
                  <Switch
                    disabled={saving}
                    onValueChange={(enabled) =>
                      void save({ ...preferences, enabled }, enabled)
                    }
                    trackColor={{ false: colors.line, true: colors.accentSoft }}
                    thumbColor={
                      preferences.enabled ? colors.accent : colors.faint
                    }
                    value={preferences.enabled}
                  />
                }
                icon={Bell}
                label="允许通知"
                subtitle={setupDescription(setupState)}
              />
            </IosGroup>

            <IosGroup title="提醒类型">
              <NotificationSwitch
                icon={Check}
                label="运行完成"
                name="run_completed"
                onChange={update}
                preferences={preferences}
              />
              <NotificationSwitch
                icon={MessageCircleQuestion}
                label="等待我的输入"
                name="input_required"
                onChange={update}
                preferences={preferences}
              />
              <NotificationSwitch
                icon={ShieldCheck}
                label="审批请求"
                name="approval_required"
                onChange={update}
                preferences={preferences}
              />
              <NotificationSwitch
                icon={TriangleAlert}
                label="运行失败"
                name="run_failed"
                onChange={update}
                preferences={preferences}
              />
            </IosGroup>

            <IosGroup title="锁屏预览">
              {previewOptions.map((option) => (
                <IosRow
                  accessory={
                    preferences.preview === option.value ? (
                      <Check
                        color={colors.accent}
                        size={20}
                        strokeWidth={2.5}
                      />
                    ) : null
                  }
                  icon={Eye}
                  key={option.value}
                  label={option.label}
                  onPress={() => update({ preview: option.value })}
                  subtitle={option.subtitle}
                />
              ))}
            </IosGroup>
          </>
        ) : (
          <ActivityIndicator color={colors.accent} style={styles.loader} />
        )}

        {setupState === "project_required" ? (
          <View style={styles.notice}>
            <CircleAlert color={colors.accentDark} size={19} />
            <Text style={styles.noticeText}>
              App 尚未绑定 EAS
              projectId。设置已经保留，配置项目并重新构建后即可注册系统推送。
            </Text>
          </View>
        ) : null}
        {error ? <Text style={styles.error}>{error}</Text> : null}
        <Text style={styles.privacy}>
          通知深链只携带工作区哈希与不透明
          ID，不包含服务器地址、令牌或完整消息内容。
        </Text>
      </ScrollView>
    </SafeAreaView>
  );
}

function NotificationSwitch({
  icon,
  label,
  name,
  onChange,
  preferences,
}: {
  icon: LucideIcon;
  label: string;
  name: "run_completed" | "input_required" | "approval_required" | "run_failed";
  onChange: (patch: Partial<NotificationPreferences>) => void;
  preferences: NotificationPreferences;
}) {
  return (
    <IosRow
      accessory={
        <Switch
          disabled={!preferences.enabled}
          onValueChange={(value) => onChange({ [name]: value })}
          trackColor={{ false: colors.line, true: colors.accentSoft }}
          thumbColor={preferences[name] ? colors.accent : colors.faint}
          value={preferences[name]}
        />
      }
      icon={icon}
      label={label}
    />
  );
}

function setupDescription(state: NotificationSetupState): string {
  if (state === "ready") return "当前设备已启用";
  if (state === "denied") return "系统权限未允许，请到系统设置中开启";
  if (state === "device_required")
    return "系统推送需要在 Android 或 iPhone 真机测试";
  if (state === "project_required") return "等待配置推送项目";
  return "关闭时不会向此设备发送通知";
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
  hero: {
    minHeight: 92,
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.md,
    padding: spacing.md,
    borderRadius: radius.md,
    backgroundColor: colors.surface,
  },
  heroIcon: {
    width: 46,
    height: 46,
    alignItems: "center",
    justifyContent: "center",
    borderRadius: 15,
    backgroundColor: colors.accentSoft,
  },
  heroText: { flex: 1, gap: 4 },
  heroTitle: { color: colors.ink, fontSize: 17, fontWeight: "600" },
  heroSubtitle: { color: colors.muted, fontSize: 13, lineHeight: 19 },
  loader: { marginTop: spacing.xl },
  notice: {
    flexDirection: "row",
    alignItems: "flex-start",
    gap: spacing.sm,
    padding: spacing.md,
    borderRadius: radius.md,
    backgroundColor: colors.accentSoft,
  },
  noticeText: {
    flex: 1,
    color: colors.accentDark,
    fontSize: 13,
    lineHeight: 19,
  },
  error: { color: colors.danger, fontSize: 13, lineHeight: 19 },
  privacy: {
    color: colors.muted,
    fontSize: 12,
    lineHeight: 18,
    paddingHorizontal: 4,
  },
});
