import { MobileAlert } from "@/components/MobileAlert";
import { Bot, Brain, Gauge, Pencil, RefreshCw, X } from "lucide-react-native";
import { useCallback, useEffect, useState } from "react";
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
import { ModuleError, ModuleFooter, ModuleLoading } from "./ModuleState";
import { AgentAdvancedSettings } from "./AgentAdvancedSettings";

interface AgentConfig {
  id: string;
  name: string;
  description?: string;
  approval_level?: string;
  thinking_level?: string;
  workspace_dir?: string;
}

export function AgentSettings({ connection }: { connection: Connection }) {
  const [config, setConfig] = useState<AgentConfig | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [editing, setEditing] = useState(false);

  const load = useCallback(async () => {
    try {
      const value = await new QwenPawClient(connection).inspectModule(
        `/agents/${encodeURIComponent(connection.agentId)}`,
      );
      setError(null);
      setConfig(value as AgentConfig);
    } catch (reason) {
      setError(errorMessage(reason));
    }
  }, [connection]);

  useEffect(() => {
    const task = setTimeout(() => void load(), 0);
    return () => clearTimeout(task);
  }, [load]);

  const update = useCallback(async (body: Record<string, unknown>) => {
    const next = await new QwenPawClient(connection)
      .mutateModule<AgentConfig>(
        `/agents/${encodeURIComponent(connection.agentId)}`,
        "PUT",
        body,
      );
    setConfig(next);
  }, [connection]);

  const chooseApproval = () => {
    if (!config) return;
    const option = (value: string, label: string) => ({
      text: label,
      onPress: () => void update({ approval_level: value }).catch((reason) => {
        MobileAlert.alert("保存失败", errorMessage(reason));
      }),
    });
    MobileAlert.alert("默认审批等级", "会话仍可单独覆盖。", [
      option("STRICT", "严格"),
      option("SMART", "智能"),
      option("AUTO", "自动"),
      option("OFF", "关闭"),
      { text: "取消", style: "cancel" },
    ]);
  };

  const chooseThinking = () => {
    if (!config) return;
    const save = (thinking_level: string) => void new QwenPawClient(connection)
      .mutateModule<AgentConfig>(
        `/agents/${encodeURIComponent(connection.agentId)}/model-settings`,
        "PATCH",
        { thinking_level },
      ).then(setConfig).catch((reason) => {
        MobileAlert.alert("保存失败", errorMessage(reason));
      });
    MobileAlert.alert("思考等级", "控制当前 Agent 的默认推理强度。", [
      { text: "跟随模型", onPress: () => save("inherit") },
      { text: "关闭", onPress: () => save("off") },
      { text: "低", onPress: () => save("low") },
      { text: "中", onPress: () => save("medium") },
      { text: "高", onPress: () => save("high") },
      { text: "取消", style: "cancel" },
    ]);
  };

  const reindexMemory = () => {
    MobileAlert.alert("重建记忆索引？", "会在后台重新索引当前 Agent 的 Memory。", [
      { text: "取消", style: "cancel" },
      {
        text: "开始重建",
        onPress: () => void new QwenPawClient(connection).mutateModule(
          `/agents/${encodeURIComponent(connection.agentId)}/memory/reindex`,
          "POST",
        ).then(() => MobileAlert.alert("已开始", "重建任务正在后台运行。"))
          .catch((reason) => MobileAlert.alert("启动失败", errorMessage(reason))),
      },
    ]);
  };

  if (error) return <ModuleError message={error} onRetry={() => void load()} />;
  if (!config) return <ModuleLoading />;

  return (
    <>
      <IosGroup title="身份">
        <IosRow
          icon={Bot}
          label={config.name}
          onPress={() => setEditing(true)}
          subtitle={config.description || "未设置描述"}
          trailing={config.id}
        />
        <IosRow
          icon={Pencil}
          iconTone="ink"
          label="编辑名称与描述"
          onPress={() => setEditing(true)}
        />
      </IosGroup>
      <IosGroup title="默认行为">
        <IosRow
          icon={Gauge}
          label="审批等级"
          onPress={chooseApproval}
          subtitle="会话可单独覆盖"
          trailing={approvalLabel(config.approval_level)}
        />
        <IosRow
          icon={Brain}
          iconTone="ink"
          label="思考等级"
          onPress={chooseThinking}
          subtitle="模型推理强度"
          trailing={thinkingLabel(config.thinking_level)}
        />
      </IosGroup>
      <IosGroup title="Memory">
        <IosRow
          icon={RefreshCw}
          label="重建记忆索引"
          onPress={reindexMemory}
          subtitle="不会删除原始记忆文件"
        />
      </IosGroup>
      <AgentAdvancedSettings connection={connection} />
      <ModuleFooter>{config.workspace_dir ?? "当前 Agent workspace"}</ModuleFooter>
      {editing ? (
        <AgentEditor
          config={config}
          onClose={() => setEditing(false)}
          onSave={(body) => update(body).then(() => setEditing(false))}
        />
      ) : null}
    </>
  );
}

function AgentEditor({
  config,
  onClose,
  onSave,
}: {
  config: AgentConfig;
  onClose: () => void;
  onSave: (body: Record<string, unknown>) => Promise<void>;
}) {
  const [name, setName] = useState(config.name);
  const [description, setDescription] = useState(config.description ?? "");
  const [saving, setSaving] = useState(false);
  const save = async () => {
    if (!name.trim() || saving) return;
    setSaving(true);
    try {
      await onSave({ name: name.trim(), description: description.trim() });
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
          <Text style={styles.modalTitle}>编辑 Agent</Text>
          <Pressable accessibilityLabel="关闭" onPress={onClose} style={styles.close}>
            <X color={colors.ink} size={22} />
          </Pressable>
        </View>
        <View style={styles.form}>
          <Text style={styles.label}>名称</Text>
          <TextInput
            onChangeText={setName}
            placeholderTextColor={colors.faint}
            style={styles.input}
            value={name}
          />
          <Text style={styles.label}>描述</Text>
          <TextInput
            multiline
            onChangeText={setDescription}
            placeholder="这个 Agent 负责什么"
            placeholderTextColor={colors.faint}
            style={[styles.input, styles.textarea]}
            value={description}
          />
          <Pressable
            disabled={!name.trim() || saving}
            onPress={() => void save()}
            style={[styles.save, (!name.trim() || saving) && styles.disabled]}
          >
            <Text style={styles.saveText}>{saving ? "正在保存…" : "保存"}</Text>
          </Pressable>
        </View>
      </SafeAreaView>
    </Modal>
  );
}

function approvalLabel(value?: string): string {
  return ({ STRICT: "严格", SMART: "智能", AUTO: "自动", OFF: "关闭" })[value ?? ""] ?? "自动";
}

function thinkingLabel(value?: string): string {
  return ({ inherit: "跟随", off: "关闭", low: "低", medium: "中", high: "高" })[value ?? ""] ?? "跟随";
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
    minHeight: 52,
    paddingHorizontal: spacing.md,
    borderRadius: radius.md,
    color: colors.ink,
    backgroundColor: colors.surface,
    fontSize: 16,
  },
  textarea: { minHeight: 120, paddingTop: spacing.md, textAlignVertical: "top" },
  save: {
    height: 50,
    alignItems: "center",
    justifyContent: "center",
    marginTop: spacing.md,
    borderRadius: radius.md,
    backgroundColor: colors.accent,
  },
  disabled: { opacity: 0.45 },
  saveText: { color: colors.white, fontSize: 16, fontWeight: "700" },
});
