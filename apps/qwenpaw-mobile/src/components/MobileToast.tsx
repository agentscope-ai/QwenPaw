import { CircleAlert, CircleCheck } from "lucide-react-native";
import { useEffect } from "react";
import { StyleSheet, Text, View } from "react-native";

import { colors, radius, spacing } from "../theme/tokens";

export function MobileToast({
  message,
  onHide,
  tone = "error",
}: {
  message: string | null;
  onHide: () => void;
  tone?: "error" | "success";
}) {
  useEffect(() => {
    if (!message) return undefined;
    const timer = setTimeout(onHide, 3200);
    return () => clearTimeout(timer);
  }, [message, onHide]);

  if (!message) return null;
  const Icon = tone === "success" ? CircleCheck : CircleAlert;
  const color = tone === "success" ? colors.positive : colors.danger;

  return (
    <View accessibilityLiveRegion="polite" pointerEvents="none" style={styles.wrap}>
      <View style={styles.toast}>
        <Icon color={color} size={19} />
        <Text maxFontSizeMultiplier={1.35} style={styles.text}>
          {message}
        </Text>
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  wrap: {
    position: "absolute",
    zIndex: 100,
    top: 72,
    right: spacing.md,
    left: spacing.md,
    alignItems: "center",
  },
  toast: {
    maxWidth: 520,
    minHeight: 48,
    flexDirection: "row",
    alignItems: "center",
    gap: 9,
    paddingHorizontal: 14,
    paddingVertical: 10,
    borderWidth: StyleSheet.hairlineWidth,
    borderColor: colors.line,
    borderRadius: radius.md,
    backgroundColor: colors.surfaceStrong,
    shadowColor: colors.black,
    shadowOffset: { width: 0, height: 6 },
    shadowOpacity: 0.16,
    shadowRadius: 16,
    elevation: 10,
  },
  text: {
    flexShrink: 1,
    color: colors.ink,
    fontSize: 14,
    lineHeight: 20,
    fontWeight: "600",
  },
});
