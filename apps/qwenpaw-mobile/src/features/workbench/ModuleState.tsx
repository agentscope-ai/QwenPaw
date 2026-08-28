import type { LucideIcon } from "lucide-react-native";
import { AlertCircle, RefreshCw } from "lucide-react-native";
import type { ReactNode } from "react";
import {
  ActivityIndicator,
  Pressable,
  StyleSheet,
  Text,
  View,
} from "react-native";

import { colors, radius, spacing } from "../../theme/tokens";

export function ModuleLoading({ label = "正在读取 QwenPaw…" }: { label?: string }) {
  return (
    <View style={styles.state}>
      <ActivityIndicator color={colors.accent} />
      <Text style={styles.stateText}>{label}</Text>
    </View>
  );
}

export function ModuleError({
  message,
  onRetry,
}: {
  message: string;
  onRetry: () => void;
}) {
  return (
    <View style={styles.error}>
      <AlertCircle color={colors.danger} size={22} />
      <View style={styles.errorBody}>
        <Text style={styles.errorTitle}>无法读取当前设置</Text>
        <Text style={styles.errorText}>{message}</Text>
      </View>
      <Pressable accessibilityLabel="重试" hitSlop={8} onPress={onRetry}>
        <RefreshCw color={colors.accentDark} size={20} />
      </Pressable>
    </View>
  );
}

export function ModuleEmpty({
  icon: Icon,
  title,
  subtitle,
}: {
  icon: LucideIcon;
  title: string;
  subtitle: string;
}) {
  return (
    <View style={styles.state}>
      <Icon color={colors.faint} size={28} />
      <Text style={styles.emptyTitle}>{title}</Text>
      <Text style={styles.stateText}>{subtitle}</Text>
    </View>
  );
}

export function ModuleFooter({ children }: { children: ReactNode }) {
  return <Text style={styles.footer}>{children}</Text>;
}

const styles = StyleSheet.create({
  state: {
    minHeight: 170,
    alignItems: "center",
    justifyContent: "center",
    gap: spacing.sm,
    padding: spacing.xl,
    borderRadius: radius.md,
    backgroundColor: colors.surface,
  },
  stateText: {
    color: colors.muted,
    fontSize: 13,
    lineHeight: 19,
    textAlign: "center",
  },
  emptyTitle: { color: colors.ink, fontSize: 16, fontWeight: "600" },
  error: {
    flexDirection: "row",
    alignItems: "flex-start",
    gap: spacing.sm,
    padding: spacing.md,
    borderRadius: radius.md,
    backgroundColor: "#FFF1EF",
  },
  errorBody: { flex: 1, gap: 3 },
  errorTitle: { color: colors.danger, fontSize: 14, fontWeight: "600" },
  errorText: { color: colors.danger, fontSize: 12, lineHeight: 18 },
  footer: {
    color: colors.muted,
    fontSize: 12,
    lineHeight: 18,
    paddingHorizontal: spacing.md,
    textAlign: "center",
  },
});
