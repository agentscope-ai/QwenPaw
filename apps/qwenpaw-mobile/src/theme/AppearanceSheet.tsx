import {
  Check,
  Moon,
  Sun,
  SunMoon,
  X,
  type LucideIcon,
} from "lucide-react-native";
import { Modal, Pressable, StyleSheet, Text, View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";

import type { ThemePreference } from "./model";
import { useAppTheme } from "./ThemeProvider";
import { colors, radius, spacing } from "./tokens";

const choices: {
  icon: LucideIcon;
  label: string;
  value: ThemePreference;
}[] = [
  { icon: SunMoon, label: "跟随系统", value: "system" },
  { icon: Sun, label: "浅色", value: "light" },
  { icon: Moon, label: "深色", value: "dark" },
];

export function AppearanceSheet({
  onClose,
  visible,
}: {
  onClose: () => void;
  visible: boolean;
}) {
  const { preference, setPreference } = useAppTheme();

  const select = async (value: ThemePreference) => {
    await setPreference(value);
    onClose();
  };

  return (
    <Modal
      animationType="slide"
      onRequestClose={onClose}
      presentationStyle="formSheet"
      visible={visible}
    >
      <SafeAreaView edges={["bottom"]} style={styles.root}>
        <View style={styles.header}>
          <View style={styles.heading}>
            <Text style={styles.title}>外观</Text>
            <Text style={styles.subtitle}>选择适合当前环境的显示方式</Text>
          </View>
          <Pressable
            accessibilityLabel="关闭"
            accessibilityRole="button"
            hitSlop={8}
            onPress={onClose}
            style={({ pressed }) => [styles.close, pressed && styles.pressed]}
          >
            <X color={colors.ink} size={20} />
          </Pressable>
        </View>
        <View style={styles.group}>
          {choices.map((choice, index) => {
            const selected = choice.value === preference;
            const Icon = choice.icon;
            return (
              <Pressable
                accessibilityRole="radio"
                accessibilityState={{ checked: selected }}
                key={choice.value}
                onPress={() => void select(choice.value)}
                style={({ pressed }) => [
                  styles.row,
                  index > 0 && styles.divider,
                  pressed && styles.pressed,
                ]}
              >
                <View style={styles.icon}>
                  <Icon color={colors.accentDark} size={19} />
                </View>
                <Text style={styles.label}>{choice.label}</Text>
                {selected ? (
                  <View style={styles.check}>
                    <Check color={colors.white} size={15} strokeWidth={2.8} />
                  </View>
                ) : null}
              </Pressable>
            );
          })}
        </View>
      </SafeAreaView>
    </Modal>
  );
}

export function themePreferenceLabel(preference: ThemePreference): string {
  if (preference === "light") return "浅色";
  if (preference === "dark") return "深色";
  return "跟随系统";
}

const styles = StyleSheet.create({
  root: {
    flex: 1,
    paddingHorizontal: spacing.md,
    backgroundColor: colors.groupedBackground,
  },
  header: {
    minHeight: 78,
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    gap: spacing.md,
  },
  heading: { flex: 1, gap: 3 },
  title: {
    color: colors.ink,
    fontSize: 26,
    fontWeight: "700",
    letterSpacing: -0.7,
  },
  subtitle: { color: colors.muted, fontSize: 13 },
  close: {
    width: 44,
    height: 44,
    alignItems: "center",
    justifyContent: "center",
    borderRadius: 22,
    backgroundColor: colors.surfaceSoft,
  },
  group: {
    overflow: "hidden",
    borderWidth: StyleSheet.hairlineWidth,
    borderColor: colors.line,
    borderRadius: radius.md,
    backgroundColor: colors.surface,
  },
  row: {
    minHeight: 62,
    flexDirection: "row",
    alignItems: "center",
    gap: 12,
    paddingHorizontal: spacing.md,
  },
  divider: { borderTopWidth: StyleSheet.hairlineWidth, borderTopColor: colors.line },
  icon: {
    width: 34,
    height: 34,
    alignItems: "center",
    justifyContent: "center",
    borderRadius: 11,
    backgroundColor: colors.accentSoft,
  },
  label: { flex: 1, color: colors.ink, fontSize: 16, fontWeight: "500" },
  check: {
    width: 24,
    height: 24,
    alignItems: "center",
    justifyContent: "center",
    borderRadius: 12,
    backgroundColor: colors.accent,
  },
  pressed: { opacity: 0.64 },
});
