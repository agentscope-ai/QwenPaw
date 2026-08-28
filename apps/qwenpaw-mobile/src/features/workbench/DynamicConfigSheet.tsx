import { MobileAlert } from "@/components/MobileAlert";
import { Check, X } from "lucide-react-native";
import { useState } from "react";
import {
  KeyboardAvoidingView,
  Modal,
  Platform,
  Pressable,
  ScrollView,
  StyleSheet,
  Switch,
  Text,
  TextInput,
  View,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";

import { colors, radius, spacing } from "../../theme/tokens";

export interface DynamicField {
  name: string;
  label: string;
  type: "text" | "password" | "number" | "boolean" | "switch" | "select" | "textarea";
  required?: boolean;
  placeholder?: string;
  help?: string;
  options?: string[];
  default?: unknown;
}

export function DynamicConfigSheet({
  fields,
  onClose,
  onSave,
  title,
  values,
}: {
  fields: DynamicField[];
  onClose: () => void;
  onSave: (values: Record<string, unknown>) => Promise<void>;
  title: string;
  values: Record<string, unknown>;
}) {
  const [form, setForm] = useState<Record<string, unknown>>(() => (
    initialForm(fields, values)
  ));
  const [saving, setSaving] = useState(false);

  const save = async () => {
    const missing = fields.find((field) => (
      field.required && !String(form[field.name] ?? "").trim()
    ));
    if (missing) {
      MobileAlert.alert("请补全必填项", missing.label);
      return;
    }
    setSaving(true);
    try {
      await onSave(Object.fromEntries(fields.map((field) => {
        const value = form[field.name];
        return [
          field.name,
          field.type === "number" && value !== "" ? Number(value) : value,
        ];
      })));
      onClose();
    } catch (reason) {
      MobileAlert.alert("保存失败", reason instanceof Error ? reason.message : "操作失败");
    } finally {
      setSaving(false);
    }
  };

  const choose = (field: DynamicField) => {
    MobileAlert.alert(field.label, undefined, [
      ...(field.options ?? []).map((option) => ({
        text: option,
        onPress: () => setForm((current) => ({
          ...current,
          [field.name]: option,
        })),
      })),
      { text: "取消", style: "cancel" },
    ]);
  };

  return (
    <Modal animationType="slide" presentationStyle="pageSheet">
      <SafeAreaView style={styles.root}>
        <View style={styles.header}>
          <Pressable accessibilityLabel="取消" onPress={onClose} style={styles.action}>
            <X color={colors.ink} size={22} />
          </Pressable>
          <Text numberOfLines={1} style={styles.title}>{title}</Text>
          <Pressable
            accessibilityLabel="保存"
            disabled={saving}
            onPress={() => void save()}
            style={styles.action}
          >
            <Check color={saving ? colors.faint : colors.accentDark} size={22} />
          </Pressable>
        </View>
        <KeyboardAvoidingView
          behavior={Platform.OS === "ios" ? "padding" : undefined}
          style={styles.flex}
        >
          <ScrollView contentContainerStyle={styles.content} keyboardShouldPersistTaps="handled">
            {fields.map((field) => {
              const value = form[field.name];
              const boolean = field.type === "boolean" || field.type === "switch";
              return (
                <View key={field.name} style={styles.field}>
                  <View style={styles.labelRow}>
                    <Text style={styles.label}>{field.label}</Text>
                    {field.required ? <Text style={styles.required}>必填</Text> : null}
                  </View>
                  {boolean ? (
                    <View style={styles.switchRow}>
                      <Text style={styles.switchValue}>{value === true ? "已开启" : "已关闭"}</Text>
                      <Switch
                        onValueChange={(next) => setForm((current) => ({
                          ...current,
                          [field.name]: next,
                        }))}
                        trackColor={{ false: colors.hairline, true: colors.accent }}
                        value={value === true}
                      />
                    </View>
                  ) : field.type === "select" ? (
                    <Pressable onPress={() => choose(field)} style={styles.select}>
                      <Text style={styles.selectText}>{String(value || "请选择")}</Text>
                    </Pressable>
                  ) : (
                    <TextInput
                      autoCapitalize="none"
                      keyboardType={field.type === "number" ? "decimal-pad" : "default"}
                      multiline={field.type === "textarea"}
                      onChangeText={(next) => setForm((current) => ({
                        ...current,
                        [field.name]: next,
                      }))}
                      placeholder={field.placeholder}
                      placeholderTextColor={colors.faint}
                      secureTextEntry={field.type === "password"}
                      style={[styles.input, field.type === "textarea" && styles.textarea]}
                      value={String(value ?? "")}
                    />
                  )}
                  {field.help ? <Text style={styles.help}>{field.help}</Text> : null}
                </View>
              );
            })}
          </ScrollView>
        </KeyboardAvoidingView>
      </SafeAreaView>
    </Modal>
  );
}

function defaultValue(type: DynamicField["type"]): unknown {
  return type === "boolean" || type === "switch" ? false : "";
}

function initialForm(
  fields: DynamicField[],
  values: Record<string, unknown>,
): Record<string, unknown> {
  return Object.fromEntries(fields.map((field) => [
    field.name,
    values[field.name] ?? field.default ?? defaultValue(field.type),
  ]));
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.groupedBackground },
  flex: { flex: 1 },
  header: {
    height: 58,
    flexDirection: "row",
    alignItems: "center",
    borderBottomWidth: StyleSheet.hairlineWidth,
    borderBottomColor: colors.hairline,
    backgroundColor: colors.tabBar,
  },
  action: { width: 54, height: 54, alignItems: "center", justifyContent: "center" },
  title: { flex: 1, color: colors.ink, fontSize: 17, fontWeight: "600", textAlign: "center" },
  content: { gap: spacing.md, padding: spacing.md, paddingBottom: spacing.xxl },
  field: { gap: 7 },
  labelRow: { flexDirection: "row", alignItems: "center", gap: spacing.xs },
  label: { color: colors.ink, fontSize: 14, fontWeight: "600" },
  required: { color: colors.accentDark, fontSize: 11 },
  input: {
    minHeight: 50,
    paddingHorizontal: spacing.md,
    borderRadius: radius.md,
    color: colors.ink,
    backgroundColor: colors.surface,
    fontSize: 16,
  },
  textarea: { minHeight: 120, paddingTop: spacing.md, textAlignVertical: "top" },
  select: {
    minHeight: 50,
    justifyContent: "center",
    paddingHorizontal: spacing.md,
    borderRadius: radius.md,
    backgroundColor: colors.surface,
  },
  selectText: { color: colors.ink, fontSize: 16 },
  switchRow: {
    minHeight: 50,
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    paddingHorizontal: spacing.md,
    borderRadius: radius.md,
    backgroundColor: colors.surface,
  },
  switchValue: { color: colors.muted, fontSize: 15 },
  help: { color: colors.muted, fontSize: 12, lineHeight: 17, paddingHorizontal: 4 },
});
