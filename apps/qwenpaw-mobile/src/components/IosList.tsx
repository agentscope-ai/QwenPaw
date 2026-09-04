import type { LucideIcon } from "lucide-react-native";
import { ChevronRight } from "lucide-react-native";
import type { ReactNode } from "react";
import { memo } from "react";
import {
  Pressable,
  StyleSheet,
  Text,
  View,
} from "react-native";

import { colors, radius, spacing } from "../theme/tokens";

export function IosGroup({
  children,
  title,
}: {
  children: ReactNode;
  title?: string;
}) {
  return (
    <View style={styles.section}>
      {title ? (
        <Text maxFontSizeMultiplier={1.4} style={styles.sectionTitle}>
          {title}
        </Text>
      ) : null}
      <View style={styles.group}>{children}</View>
    </View>
  );
}

export const IosRow = memo(function IosRow({
  accessory,
  destructive = false,
  icon: Icon,
  label,
  onPress,
  subtitle,
  trailing,
}: {
  accessory?: ReactNode;
  destructive?: boolean;
  icon: LucideIcon;
  iconTone?: "orange" | "ink";
  label: string;
  onPress?: () => void;
  subtitle?: string;
  trailing?: string;
}) {
  return (
    <Pressable
      accessibilityRole={onPress ? "button" : undefined}
      disabled={!onPress}
      onPress={onPress}
      style={({ pressed }) => [styles.row, pressed && styles.pressed]}
    >
      <View style={styles.icon}>
        <Icon color={colors.ink} size={18} strokeWidth={1.9} />
      </View>
      <View style={styles.body}>
        <View style={styles.textBlock}>
          <Text
            maxFontSizeMultiplier={1.4}
            style={[styles.label, destructive && styles.destructive]}
          >
            {label}
          </Text>
          {subtitle ? (
            <Text
              maxFontSizeMultiplier={1.3}
              numberOfLines={1}
              style={styles.subtitle}
            >
              {subtitle}
            </Text>
          ) : null}
        </View>
        {accessory ?? (trailing ? (
          <Text
            maxFontSizeMultiplier={1.25}
            numberOfLines={1}
            style={styles.trailing}
          >
            {trailing}
          </Text>
        ) : null)}
        {onPress ? <ChevronRight color={colors.faint} size={17} /> : null}
      </View>
    </Pressable>
  );
});

const styles = StyleSheet.create({
  section: { gap: 7 },
  sectionTitle: {
    color: colors.muted,
    fontSize: 13,
    marginLeft: spacing.md,
    textTransform: "uppercase",
  },
  group: {
    overflow: "hidden",
    borderWidth: StyleSheet.hairlineWidth,
    borderColor: colors.line,
    borderRadius: radius.md,
    backgroundColor: colors.surface,
  },
  row: {
    minHeight: 64,
    flexDirection: "row",
    alignItems: "center",
    paddingLeft: spacing.md,
    backgroundColor: colors.surface,
  },
  pressed: { backgroundColor: colors.pressed },
  icon: {
    width: 30,
    height: 30,
    borderRadius: 10,
    alignItems: "center",
    justifyContent: "center",
    backgroundColor: colors.surfaceSoft,
  },
  body: {
    flex: 1,
    minHeight: 64,
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.sm,
    marginLeft: 12,
    paddingRight: 12,
    borderBottomWidth: StyleSheet.hairlineWidth,
    borderBottomColor: colors.hairline,
  },
  textBlock: { flex: 1, minWidth: 0 },
  label: { color: colors.ink, fontSize: 16, fontWeight: "500" },
  destructive: { color: colors.danger },
  subtitle: { color: colors.muted, fontSize: 12, marginTop: 2 },
  trailing: { color: colors.muted, fontSize: 13 },
});
