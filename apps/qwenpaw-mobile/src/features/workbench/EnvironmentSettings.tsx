import { MobileAlert } from "@/components/MobileAlert";
import { KeyRound, Plus, Trash2, X } from "lucide-react-native";
import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Modal,
  Pressable,
  StyleSheet,
  Text,
  TextInput,
  View,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";

import { QwenPawClient } from "../../api/client";
import type { Connection } from "../../api/types";
import { IosGroup, IosRow } from "../../components/IosList";
import { colors, radius, spacing } from "../../theme/tokens";
import { ModuleEmpty, ModuleError, ModuleFooter, ModuleLoading } from "./ModuleState";

interface EnvVar { key: string; value: string }

export function EnvironmentSettings({ connection }: { connection: Connection }) {
  const [envs, setEnvs] = useState<EnvVar[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [editing, setEditing] = useState<EnvVar | "new" | null>(null);

  const load = useCallback(async () => {
    try {
      const value = await new QwenPawClient(connection).inspectModule("/envs");
      setError(null);
      setEnvs(Array.isArray(value) ? value as EnvVar[] : []);
    } catch (reason) {
      setError(errorMessage(reason));
    }
  }, [connection]);

  useEffect(() => {
    const task = setTimeout(() => void load(), 0);
    return () => clearTimeout(task);
  }, [load]);

  const remove = useCallback((item: EnvVar) => {
    MobileAlert.alert("删除环境变量？", item.key, [
      { text: "取消", style: "cancel" },
      {
        text: "删除",
        style: "destructive",
        onPress: () => void new QwenPawClient(connection)
          .mutateModule<EnvVar[]>(`/envs/${encodeURIComponent(item.key)}`, "DELETE")
          .then(setEnvs)
          .catch((reason) => MobileAlert.alert("删除失败", errorMessage(reason))),
      },
    ]);
  }, [connection]);

  if (error) return <ModuleError message={error} onRetry={() => void load()} />;
  if (!envs) return <ModuleLoading />;

  return (
    <>
      <IosGroup title={`环境变量 · ${envs.length}`}>
        {envs.map((item) => (
          <IosRow
            accessory={(
              <Pressable
                accessibilityLabel={`删除 ${item.key}`}
                hitSlop={8}
                onPress={() => remove(item)}
              >
                <Trash2 color={colors.danger} size={18} />
              </Pressable>
            )}
            icon={KeyRound}
            iconTone="ink"
            key={item.key}
            label={item.key}
            onPress={() => setEditing(item)}
            subtitle="值已隐藏"
          />
        ))}
        <IosRow
          icon={Plus}
          label="添加环境变量"
          onPress={() => setEditing("new")}
        />
      </IosGroup>
      {!envs.length ? (
        <ModuleEmpty
          icon={KeyRound}
          title="暂无环境变量"
          subtitle="添加的值会安全保存到当前 QwenPaw。"
        />
      ) : null}
      <ModuleFooter>密钥值不会显示在列表、日志或错误信息中。</ModuleFooter>
      {editing ? (
        <EnvironmentEditor
          envs={envs}
          initial={editing === "new" ? null : editing}
          onClose={() => setEditing(null)}
          onSaved={(next) => {
            setEnvs(next);
            setEditing(null);
          }}
          connection={connection}
        />
      ) : null}
    </>
  );
}

function EnvironmentEditor({
  connection,
  envs,
  initial,
  onClose,
  onSaved,
}: {
  connection: Connection;
  envs: EnvVar[];
  initial: EnvVar | null;
  onClose: () => void;
  onSaved: (items: EnvVar[]) => void;
}) {
  const [key, setKey] = useState(initial?.key ?? "");
  const [value, setValue] = useState("");
  const [saving, setSaving] = useState(false);
  const normalizedKey = key.trim();
  const valid = Boolean(normalizedKey && value);
  const existingMap = useMemo(() => Object.fromEntries(
    envs.map((item) => [item.key, item.value]),
  ), [envs]);

  const save = async () => {
    if (!valid || saving) return;
    setSaving(true);
    try {
      const nextMap = { ...existingMap };
      if (initial && initial.key !== normalizedKey) delete nextMap[initial.key];
      nextMap[normalizedKey] = value;
      const next = await new QwenPawClient(connection)
        .mutateModule<EnvVar[]>("/envs", "PUT", nextMap);
      onSaved(next);
    } catch (reason) {
      MobileAlert.alert("保存失败", errorMessage(reason));
    } finally {
      setSaving(false);
    }
  };

  return (
    <Modal animationType="slide" presentationStyle="pageSheet">
      <SafeAreaView style={styles.modalRoot}>
        <View style={styles.modalHeader}>
          <Text style={styles.modalTitle}>{initial ? "更新环境变量" : "添加环境变量"}</Text>
          <Pressable accessibilityLabel="关闭" onPress={onClose} style={styles.close}>
            <X color={colors.ink} size={22} />
          </Pressable>
        </View>
        <View style={styles.form}>
          <Text style={styles.label}>名称</Text>
          <TextInput
            autoCapitalize="characters"
            autoCorrect={false}
            editable={!initial}
            onChangeText={setKey}
            placeholder="例如 OPENAI_API_KEY"
            placeholderTextColor={colors.faint}
            style={styles.input}
            value={key}
          />
          <Text style={styles.label}>值</Text>
          <TextInput
            autoCapitalize="none"
            autoCorrect={false}
            onChangeText={setValue}
            placeholder={initial ? "输入新值" : "输入值"}
            placeholderTextColor={colors.faint}
            secureTextEntry
            style={styles.input}
            value={value}
          />
          <Pressable
            disabled={!valid || saving}
            onPress={() => void save()}
            style={[styles.save, (!valid || saving) && styles.saveDisabled]}
          >
            <Text style={styles.saveText}>{saving ? "正在保存…" : "保存"}</Text>
          </Pressable>
        </View>
      </SafeAreaView>
    </Modal>
  );
}

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : "操作失败";
}

const styles = StyleSheet.create({
  modalRoot: { flex: 1, backgroundColor: colors.groupedBackground },
  modalHeader: {
    height: 58,
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    paddingHorizontal: spacing.md,
  },
  modalTitle: { color: colors.ink, fontSize: 20, fontWeight: "700" },
  close: {
    width: 36,
    height: 36,
    borderRadius: 18,
    alignItems: "center",
    justifyContent: "center",
    backgroundColor: colors.searchBackground,
  },
  form: { gap: spacing.sm, padding: spacing.md },
  label: { color: colors.muted, fontSize: 13, marginTop: spacing.sm },
  input: {
    height: 52,
    paddingHorizontal: spacing.md,
    borderRadius: radius.md,
    color: colors.ink,
    backgroundColor: colors.surface,
    fontSize: 16,
  },
  save: {
    height: 50,
    alignItems: "center",
    justifyContent: "center",
    marginTop: spacing.md,
    borderRadius: radius.md,
    backgroundColor: colors.accent,
  },
  saveDisabled: { opacity: 0.45 },
  saveText: { color: colors.white, fontSize: 16, fontWeight: "700" },
});
