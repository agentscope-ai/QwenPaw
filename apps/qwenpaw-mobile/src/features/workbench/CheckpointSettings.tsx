import { MobileAlert } from "@/components/MobileAlert";
import {
  Clock3,
  FileClock,
  RotateCcw,
  Settings2,
  Sparkles,
  Trash2,
} from "lucide-react-native";
import { useCallback, useEffect, useState } from "react";
import { Switch } from "react-native";

import { QwenPawClient } from "../../api/client";
import type { Connection } from "../../api/types";
import { IosGroup, IosRow } from "../../components/IosList";
import { colors } from "../../theme/tokens";
import { DynamicConfigSheet } from "./DynamicConfigSheet";
import { ModuleEmpty, ModuleError, ModuleFooter, ModuleLoading } from "./ModuleState";

interface CheckpointStatus {
  auto_enabled: boolean;
  has_checkpoints: boolean;
  workspace_dir: string;
}

interface CheckpointNode {
  commit: string;
  sha?: string;
  kind: string;
  name?: string;
  subject?: string;
  session_id: string;
  session_title?: string;
  user_id?: string;
  channel?: string;
  timestamp_ms: number;
}

interface CheckpointGraph {
  nodes: CheckpointNode[];
  sessions: {
    session_id: string;
    user_id: string;
    channel: string;
    title?: string;
    archived?: boolean;
  }[];
  summary?: { total?: number };
}

interface CheckpointGcSettings {
  gc_keep_count: number;
  gc_keep_days: number;
  pre_restore_retention_days: number;
}

export function CheckpointSettings({ connection }: { connection: Connection }) {
  const [status, setStatus] = useState<CheckpointStatus | null>(null);
  const [graph, setGraph] = useState<CheckpointGraph | null>(null);
  const [gcSettings, setGcSettings] = useState<CheckpointGcSettings | null>(null);
  const [editingGc, setEditingGc] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    try {
      const client = new QwenPawClient(connection);
      const [nextStatus, nextGraph, nextGcSettings] = await Promise.all([
        client.inspectModule("/workspace/checkpoints/status"),
        client.inspectModule("/workspace/checkpoints/graph?limit=100"),
        client.inspectModule("/workspace/checkpoints/gc/settings"),
      ]);
      setError(null);
      setStatus(nextStatus as CheckpointStatus);
      setGraph(nextGraph as CheckpointGraph);
      setGcSettings(nextGcSettings as CheckpointGcSettings);
    } catch (reason) {
      setError(errorMessage(reason));
    }
  }, [connection]);

  useEffect(() => {
    const task = setTimeout(() => void load(), 0);
    return () => clearTimeout(task);
  }, [load]);

  const setAuto = async (enabled: boolean) => {
    if (!status || busy) return;
    const previous = status.auto_enabled;
    setStatus({ ...status, auto_enabled: enabled });
    setBusy(true);
    try {
      const result = await new QwenPawClient(connection).mutateModule<{
        auto_enabled: boolean;
      }>("/workspace/checkpoints/auto", "PATCH", { enabled });
      setStatus({ ...status, auto_enabled: result.auto_enabled });
    } catch (reason) {
      setStatus({ ...status, auto_enabled: previous });
      MobileAlert.alert("保存失败", errorMessage(reason));
    } finally {
      setBusy(false);
    }
  };

  const createSnapshot = () => {
    const session = graph?.sessions.find((item) => !item.archived) ?? graph?.sessions[0];
    if (!session) {
      MobileAlert.alert("暂无会话", "创建至少一个会话后才能建立手动快照。");
      return;
    }
    MobileAlert.alert(
      "创建当前工作区快照？",
      `快照会关联到「${session.title || session.session_id}」。`,
      [
        { text: "取消", style: "cancel" },
        {
          text: "创建",
          onPress: () => void run(async () => {
            await new QwenPawClient(connection).mutateModule(
              "/workspace/checkpoints/snapshot",
              "POST",
              {
                session_id: session.session_id,
                user_id: session.user_id,
                channel: session.channel,
                name: `Mobile ${new Date().toLocaleString()}`,
              },
            );
          }, "快照已创建"),
        },
      ],
    );
  };

  const previewRestore = async (node: CheckpointNode) => {
    setBusy(true);
    try {
      const client = new QwenPawClient(connection);
      const body = {
        commit: node.commit,
        session_id: node.session_id,
        user_id: node.user_id ?? "",
        channel: node.channel ?? "console",
        include_memory: false,
        include_files: false,
      };
      await client.mutateModule(
        "/workspace/checkpoints/restore/preview",
        "POST",
        body,
      );
      MobileAlert.alert(
        "恢复到这个版本？",
        "预检已通过。恢复前会自动创建安全快照。",
        [
          { text: "取消", style: "cancel" },
          {
            text: "恢复",
            style: "destructive",
            onPress: () => void run(
              () => client.mutateModule("/workspace/checkpoints/restore", "POST", body),
              "工作区已恢复",
            ),
          },
        ],
      );
    } catch (reason) {
      MobileAlert.alert("无法恢复", errorMessage(reason));
    } finally {
      setBusy(false);
    }
  };

  const cleanHistory = async () => {
    setBusy(true);
    try {
      const client = new QwenPawClient(connection);
      const preview = await client.mutateModule<{
        deleted_refs?: string[];
      }>("/workspace/checkpoints/gc/preview", "POST", {});
      const count = preview.deleted_refs?.length ?? 0;
      if (!count) {
        MobileAlert.alert("无需清理", "当前没有超过保留策略的历史版本。");
        return;
      }
      MobileAlert.alert("清理历史版本？", `将删除 ${count} 个过期版本。`, [
        { text: "取消", style: "cancel" },
        {
          text: "清理",
          style: "destructive",
          onPress: () => void run(
            () => client.mutateModule("/workspace/checkpoints/gc", "POST", {}),
            "历史版本已清理",
          ),
        },
      ]);
    } catch (reason) {
      MobileAlert.alert("预检失败", errorMessage(reason));
    } finally {
      setBusy(false);
    }
  };

  const run = async (action: () => Promise<unknown>, success: string) => {
    if (busy) return;
    setBusy(true);
    try {
      await action();
      await load();
      MobileAlert.alert(success);
    } catch (reason) {
      MobileAlert.alert("操作失败", errorMessage(reason));
    } finally {
      setBusy(false);
    }
  };

  if (error) return <ModuleError message={error} onRetry={() => void load()} />;
  if (!status || !graph || !gcSettings) return <ModuleLoading />;

  return (
    <>
      <IosGroup title="版本保护">
        <IosRow
          accessory={(
            <Switch
              disabled={busy}
              onValueChange={(value) => void setAuto(value)}
              trackColor={{ false: colors.faint, true: colors.accent }}
              value={status.auto_enabled}
            />
          )}
          icon={FileClock}
          label="自动建立 Checkpoint"
          subtitle="Agent 工作前后自动保存版本"
        />
        <IosRow
          icon={Sparkles}
          label="立即创建快照"
          onPress={createSnapshot}
          subtitle="保存当前 Agent workspace"
        />
        <IosRow
          icon={Settings2}
          iconTone="ink"
          label="历史保留策略"
          onPress={() => setEditingGc(true)}
          subtitle={`${gcSettings.gc_keep_count} 个 / ${gcSettings.gc_keep_days} 天 · 安全版本 ${gcSettings.pre_restore_retention_days} 天`}
        />
        <IosRow
          destructive
          icon={Trash2}
          iconTone="ink"
          label="按保留策略清理"
          onPress={() => void cleanHistory()}
          subtitle="先预检，再确认删除"
        />
      </IosGroup>

      {graph.nodes.length ? (
        <IosGroup title={`历史版本 · ${graph.summary?.total ?? graph.nodes.length}`}>
          {graph.nodes.slice(0, 30).map((node) => (
            <IosRow
              icon={node.kind === "snap" ? Sparkles : Clock3}
              iconTone={node.kind === "snap" ? "orange" : "ink"}
              key={`${node.commit}-${node.timestamp_ms}`}
              label={node.name || node.subject || checkpointKind(node.kind)}
              onPress={() => void previewRestore(node)}
              subtitle={`${node.session_title || node.session_id} · ${formatDate(node.timestamp_ms)}`}
              trailing={node.sha || node.commit.slice(0, 8)}
            />
          ))}
        </IosGroup>
      ) : (
        <ModuleEmpty
          icon={RotateCcw}
          title="还没有历史版本"
          subtitle="开启自动版本或创建一次手动快照。"
        />
      )}
      <ModuleFooter>{status.workspace_dir}</ModuleFooter>
      {editingGc ? (
        <DynamicConfigSheet
          fields={[
            {
              name: "gc_keep_count",
              label: "每个会话保留数量",
              type: "number",
              required: true,
            },
            {
              name: "gc_keep_days",
              label: "自动版本保留天数",
              type: "number",
              required: true,
            },
            {
              name: "pre_restore_retention_days",
              label: "恢复前安全版本保留天数",
              type: "number",
              required: true,
            },
          ]}
          onClose={() => setEditingGc(false)}
          onSave={async (values) => {
            const next = {
              gc_keep_count: positiveInteger(values.gc_keep_count, "保留数量"),
              gc_keep_days: positiveInteger(values.gc_keep_days, "保留天数"),
              pre_restore_retention_days: positiveInteger(
                values.pre_restore_retention_days,
                "安全版本保留天数",
              ),
            };
            const saved = await new QwenPawClient(connection)
              .mutateModule<CheckpointGcSettings>(
                "/workspace/checkpoints/gc/settings",
                "PATCH",
                next,
              );
            setGcSettings(saved);
          }}
          title="历史保留策略"
          values={{
            gc_keep_count: gcSettings.gc_keep_count,
            gc_keep_days: gcSettings.gc_keep_days,
            pre_restore_retention_days: gcSettings.pre_restore_retention_days,
          }}
        />
      ) : null}
    </>
  );
}

function checkpointKind(kind: string): string {
  if (kind === "auto") return "自动版本";
  if (kind === "pre-restore") return "恢复前安全版本";
  if (kind === "snap") return "手动快照";
  return "工作区版本";
}

function formatDate(timestamp: number): string {
  return new Date(timestamp).toLocaleString();
}

function positiveInteger(value: unknown, label: string): number {
  const parsed = Number(value);
  if (!Number.isInteger(parsed) || parsed < 1) {
    throw new Error(`${label}必须是大于 0 的整数。`);
  }
  return parsed;
}

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : "操作失败";
}
