import { X } from "lucide-react-native";
import type { ReactNode } from "react";
import { useEffect, useState } from "react";
import {
  AccessibilityInfo,
  KeyboardAvoidingView,
  Modal,
  Pressable,
  StyleSheet,
  Text,
  View,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";

import { colors, radius, spacing } from "../theme/tokens";

export function MobileBottomSheet({
  children,
  expanded = false,
  onClose,
  subtitle,
  title,
  visible,
}: {
  children: ReactNode;
  expanded?: boolean;
  onClose: () => void;
  subtitle?: string;
  title: string;
  visible: boolean;
}) {
  const [reduceMotion, setReduceMotion] = useState(false);

  useEffect(() => {
    void AccessibilityInfo.isReduceMotionEnabled().then(setReduceMotion);
    const listener = AccessibilityInfo.addEventListener(
      "reduceMotionChanged",
      setReduceMotion,
    );
    return () => listener.remove();
  }, []);

  return (
    <Modal
      animationType={reduceMotion ? "none" : "slide"}
      navigationBarTranslucent
      onRequestClose={onClose}
      statusBarTranslucent
      transparent
      visible={visible}
    >
      <View style={styles.root}>
        <Pressable
          accessibilityLabel={`关闭${title}`}
          onPress={onClose}
          style={StyleSheet.absoluteFill}
        />
        <KeyboardAvoidingView behavior="padding" pointerEvents="box-none">
          <SafeAreaView
            edges={["bottom"]}
            style={[styles.sheet, expanded && styles.sheetExpanded]}
          >
            <View style={styles.grabber} />
            <View style={styles.header}>
              <View style={styles.heading}>
                <Text maxFontSizeMultiplier={1.35} style={styles.title}>
                  {title}
                </Text>
                {subtitle ? (
                  <Text maxFontSizeMultiplier={1.35} style={styles.subtitle}>
                    {subtitle}
                  </Text>
                ) : null}
              </View>
              <Pressable
                accessibilityLabel="关闭"
                accessibilityRole="button"
                onPress={onClose}
                style={({ pressed }) => [
                  styles.close,
                  pressed && styles.pressed,
                ]}
              >
                <X color={colors.ink} size={19} />
              </Pressable>
            </View>
            <View style={[styles.body, expanded && styles.bodyExpanded]}>
              {children}
            </View>
          </SafeAreaView>
        </KeyboardAvoidingView>
      </View>
    </Modal>
  );
}

const styles = StyleSheet.create({
  root: {
    flex: 1,
    justifyContent: "flex-end",
    backgroundColor: colors.scrim,
  },
  sheet: {
    maxHeight: "88%",
    paddingHorizontal: spacing.md,
    paddingBottom: spacing.sm,
    borderTopLeftRadius: radius.lg,
    borderTopRightRadius: radius.lg,
    backgroundColor: colors.groupedBackground,
    shadowColor: colors.black,
    shadowOffset: { width: 0, height: -8 },
    shadowOpacity: 0.16,
    shadowRadius: 24,
    elevation: 20,
  },
  sheetExpanded: { height: "88%" },
  grabber: {
    width: 38,
    height: 5,
    alignSelf: "center",
    marginTop: 8,
    borderRadius: 3,
    backgroundColor: colors.hairline,
  },
  header: {
    minHeight: 72,
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.sm,
  },
  heading: { flex: 1, minWidth: 0, gap: 3 },
  title: {
    color: colors.ink,
    fontSize: 21,
    lineHeight: 27,
    fontWeight: "700",
    letterSpacing: -0.35,
  },
  subtitle: { color: colors.muted, fontSize: 13, lineHeight: 18 },
  close: {
    width: 48,
    height: 48,
    alignItems: "center",
    justifyContent: "center",
    borderRadius: 24,
    backgroundColor: colors.surfaceSoft,
  },
  body: { paddingBottom: spacing.sm },
  bodyExpanded: { flex: 1 },
  pressed: { backgroundColor: colors.pressed },
});
