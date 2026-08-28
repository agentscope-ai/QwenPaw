import type { LucideIcon } from "lucide-react-native";
import { ActivityIndicator, Pressable, StyleSheet, Text } from "react-native";

import { colors, radius, spacing } from "../theme/tokens";

interface PrimaryButtonProps {
  label: string;
  onPress: () => void;
  icon?: LucideIcon;
  loading?: boolean;
  disabled?: boolean;
  tone?: "dark" | "light";
}

export function PrimaryButton({
  label,
  onPress,
  icon: Icon,
  loading = false,
  disabled = false,
  tone = "dark",
}: PrimaryButtonProps) {
  const dark = tone === "dark";
  return (
    <Pressable
      accessibilityRole="button"
      disabled={disabled || loading}
      onPress={onPress}
      style={({ pressed }) => [
        styles.button,
        dark ? styles.dark : styles.light,
        pressed && styles.pressed,
        (disabled || loading) && styles.disabled,
      ]}
    >
      {loading ? (
        <ActivityIndicator color={dark ? colors.white : colors.ink} />
      ) : (
        <>
          {Icon ? <Icon size={18} color={dark ? colors.white : colors.ink} /> : null}
          <Text style={[styles.label, dark ? styles.darkLabel : styles.lightLabel]}>
            {label}
          </Text>
        </>
      )}
    </Pressable>
  );
}

const styles = StyleSheet.create({
  button: {
    minHeight: 52,
    borderRadius: radius.md,
    paddingHorizontal: spacing.lg,
    alignItems: "center",
    justifyContent: "center",
    flexDirection: "row",
    gap: spacing.sm,
    borderWidth: 1,
  },
  dark: { backgroundColor: colors.accent, borderColor: colors.accent },
  light: { backgroundColor: colors.surfaceStrong, borderColor: colors.line },
  label: { fontSize: 16, fontWeight: "600", letterSpacing: -0.2 },
  darkLabel: { color: colors.white },
  lightLabel: { color: colors.ink },
  pressed: { opacity: 0.82, transform: [{ scale: 0.99 }] },
  disabled: { opacity: 0.45 },
});
