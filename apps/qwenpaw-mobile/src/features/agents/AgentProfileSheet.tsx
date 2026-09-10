import * as DocumentPicker from "expo-document-picker";
import { ImagePlus, RotateCcw, X } from "lucide-react-native";
import { useState } from "react";
import {
  KeyboardAvoidingView,
  Modal,
  Platform,
  Pressable,
  StyleSheet,
  Text,
  TextInput,
  View,
} from "react-native";

import type { AgentSummary } from "../../api/types";
import type { AgentAppearance } from "../../storage/agentAppearance";
import { colors, radius, spacing } from "../../theme/tokens";
import { AgentAvatar } from "./AgentAvatar";

export function AgentProfileSheet({
  agent,
  appearance,
  onClose,
  onSave,
}: {
  agent: AgentSummary;
  appearance?: AgentAppearance;
  onClose: () => void;
  onSave: (appearance: AgentAppearance) => Promise<void>;
}) {
  const [nickname, setNickname] = useState(
    appearance?.nickname || agent.name,
  );
  const [avatarUri, setAvatarUri] = useState<string | undefined>(
    appearance?.avatarUri,
  );
  const [saving, setSaving] = useState(false);

  const chooseAvatar = async () => {
    const result = await DocumentPicker.getDocumentAsync({
      type: "image/*",
      copyToCacheDirectory: true,
      multiple: false,
    });
    if (!result.canceled) setAvatarUri(result.assets[0].uri);
  };

  const save = async () => {
    setSaving(true);
    try {
      await onSave({
        nickname: nickname.trim() === agent.name ? undefined : nickname.trim(),
        avatarUri,
      });
      onClose();
    } finally {
      setSaving(false);
    }
  };

  return (
    <Modal
      animationType="slide"
      onRequestClose={onClose}
      transparent
      visible
    >
      <KeyboardAvoidingView
        behavior={Platform.OS === "ios" ? "padding" : undefined}
        style={styles.mask}
      >
        <Pressable onPress={onClose} style={StyleSheet.absoluteFill} />
        <View style={styles.sheet}>
          <View style={styles.grabber} />
          <View style={styles.header}>
            <Text style={styles.title}>智能体资料</Text>
            <Pressable accessibilityLabel="关闭" onPress={onClose} style={styles.close}>
              <X color={colors.ink} size={20} />
            </Pressable>
          </View>
          <View style={styles.avatarRow}>
            <AgentAvatar avatarUri={avatarUri} size={68} />
            <View style={styles.avatarActions}>
              <Pressable onPress={() => void chooseAvatar()} style={styles.photoAction}>
                <ImagePlus color={colors.accentDark} size={17} />
                <Text style={styles.photoActionText}>选择图片</Text>
              </Pressable>
              {avatarUri ? (
                <Pressable onPress={() => setAvatarUri(undefined)} style={styles.photoAction}>
                  <RotateCcw color={colors.muted} size={16} />
                  <Text style={styles.resetText}>恢复默认</Text>
                </Pressable>
              ) : null}
            </View>
          </View>
          <Text style={styles.label}>Mobile 昵称</Text>
          <TextInput
            autoCorrect={false}
            maxLength={36}
            onChangeText={setNickname}
            placeholder={agent.name}
            placeholderTextColor={colors.faint}
            style={styles.input}
            value={nickname}
          />
          <Text style={styles.note}>
            仅改变此设备上的显示，不修改智能体运行名称和工作区配置。
          </Text>
          <Pressable
            disabled={!nickname.trim() || saving}
            onPress={() => void save()}
            style={({ pressed }) => [
              styles.save,
              pressed && styles.pressed,
              (!nickname.trim() || saving) && styles.disabled,
            ]}
          >
            <Text style={styles.saveText}>{saving ? "保存中…" : "保存"}</Text>
          </Pressable>
        </View>
      </KeyboardAvoidingView>
    </Modal>
  );
}

const styles = StyleSheet.create({
  mask: {
    flex: 1,
    justifyContent: "flex-end",
    backgroundColor: "rgba(20, 15, 12, 0.32)",
  },
  sheet: {
    paddingHorizontal: spacing.lg,
    paddingBottom: Platform.OS === "ios" ? 34 : spacing.xl,
    borderTopLeftRadius: 28,
    borderTopRightRadius: 28,
    backgroundColor: colors.surfaceStrong,
  },
  grabber: {
    width: 38,
    height: 5,
    alignSelf: "center",
    marginTop: 8,
    marginBottom: spacing.md,
    borderRadius: 3,
    backgroundColor: colors.line,
  },
  header: { minHeight: 44, flexDirection: "row", alignItems: "center" },
  title: { flex: 1, color: colors.ink, fontSize: 20, fontWeight: "700" },
  close: { width: 40, height: 40, alignItems: "center", justifyContent: "center" },
  avatarRow: { flexDirection: "row", alignItems: "center", gap: spacing.md, marginVertical: spacing.lg },
  avatarActions: { gap: 10 },
  photoAction: { flexDirection: "row", alignItems: "center", gap: 7, minHeight: 28 },
  photoActionText: { color: colors.accentDark, fontSize: 14, fontWeight: "600" },
  resetText: { color: colors.muted, fontSize: 13 },
  label: { marginLeft: 3, marginBottom: 7, color: colors.muted, fontSize: 12 },
  input: {
    height: 50,
    paddingHorizontal: spacing.md,
    borderWidth: 1,
    borderColor: colors.line,
    borderRadius: radius.md,
    color: colors.ink,
    backgroundColor: colors.surface,
    fontSize: 16,
  },
  note: { margin: 8, color: colors.faint, fontSize: 11, lineHeight: 17 },
  save: {
    height: 50,
    alignItems: "center",
    justifyContent: "center",
    marginTop: spacing.md,
    borderRadius: radius.md,
    backgroundColor: colors.accent,
  },
  saveText: { color: colors.white, fontSize: 16, fontWeight: "700" },
  pressed: { opacity: 0.75 },
  disabled: { opacity: 0.35 },
});
