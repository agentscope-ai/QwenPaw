import type { TextInputProps } from "react-native";
import { StyleSheet, Text, TextInput, View } from "react-native";

import { colors, radius, spacing } from "../theme/tokens";

interface FieldProps extends TextInputProps {
  label: string;
}

export function Field({ label, style, ...props }: FieldProps) {
  return (
    <View style={styles.group}>
      <Text style={styles.label}>{label}</Text>
      <TextInput
        placeholderTextColor={colors.faint}
        selectionColor={colors.accent}
        style={[styles.input, style]}
        {...props}
      />
    </View>
  );
}

const styles = StyleSheet.create({
  group: { gap: spacing.xs },
  label: {
    color: colors.muted,
    fontSize: 12,
    fontWeight: "600",
    letterSpacing: 0.8,
    textTransform: "uppercase",
  },
  input: {
    minHeight: 52,
    borderWidth: 1,
    borderColor: colors.line,
    borderRadius: radius.md,
    backgroundColor: colors.surfaceStrong,
    color: colors.ink,
    paddingHorizontal: spacing.md,
    fontSize: 16,
  },
});
