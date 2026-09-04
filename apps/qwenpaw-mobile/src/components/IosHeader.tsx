import { ChevronLeft, type LucideIcon } from "lucide-react-native";
import { memo } from "react";
import { Pressable, StyleSheet, Text, View } from "react-native";

import { colors, spacing } from "../theme/tokens";

export const IosHeader = memo(function IosHeader({
  actionIcon: ActionIcon,
  actionLabel,
  emphasizedAction = false,
  onBack,
  onAction,
  title,
}: {
  actionIcon?: LucideIcon;
  actionLabel?: string;
  emphasizedAction?: boolean;
  onBack?: () => void;
  onAction?: () => void;
  title: string;
}) {
  return (
    <View style={styles.header}>
      {onBack ? (
        <Pressable
          accessibilityLabel="返回"
          accessibilityRole="button"
          hitSlop={8}
          onPress={onBack}
          style={({ pressed }) => [styles.back, pressed && styles.pressed]}
        >
          <ChevronLeft color={colors.ink} size={27} strokeWidth={2.1} />
        </Pressable>
      ) : null}
      <Text maxFontSizeMultiplier={1.4} style={styles.title}>{title}</Text>
      {ActionIcon && onAction ? (
        <Pressable
          accessibilityLabel={actionLabel}
          accessibilityRole="button"
          hitSlop={8}
          onPress={onAction}
          style={({ pressed }) => [
            styles.action,
            emphasizedAction && styles.actionEmphasized,
            pressed && styles.pressed,
          ]}
        >
          <ActionIcon
            color={emphasizedAction ? colors.white : colors.ink}
            size={emphasizedAction ? 21 : 23}
          />
        </Pressable>
      ) : <View style={styles.action} />}
    </View>
  );
});

const styles = StyleSheet.create({
  header: {
    minHeight: 66,
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    paddingHorizontal: spacing.sm,
  },
  title: {
    flex: 1,
    minWidth: 0,
    paddingHorizontal: spacing.xs,
    color: colors.ink,
    fontSize: 31,
    fontWeight: "700",
    letterSpacing: -1.1,
  },
  back: {
    width: 44,
    height: 44,
    alignItems: "center",
    justifyContent: "center",
  },
  action: {
    width: 44,
    height: 44,
    alignItems: "center",
    justifyContent: "center",
  },
  actionEmphasized: {
    borderRadius: 22,
    backgroundColor: colors.accent,
  },
  pressed: { opacity: 0.5 },
});
