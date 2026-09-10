import { MobileAlert } from "@/components/MobileAlert";
import * as DocumentPicker from "expo-document-picker";
import { File, Paths } from "expo-file-system";
import * as Sharing from "expo-sharing";
import {
  Archive,
  BarChart3,
  DatabaseBackup,
  MessageSquare,
  Plus,
  Upload,
  Wrench,
} from "lucide-react-native";
import { useCallback, useEffect, useState } from "react";

import { QwenPawClient } from "../../api/client";
import type { Connection } from "../../api/types";
import { IosGroup, IosRow } from "../../components/IosList";
import { ModuleEmpty, ModuleError, ModuleFooter, ModuleLoading } from "./ModuleState";

interface BackupMeta {
  id: string;
  name: string;
  description?: string;
  created_at: string;
  agent_count?: number;
  scope?: {
    include_agents?: boolean;
    include_global_config?: boolean;
    include_secrets?: boolean;
    include_skill_pool?: boolean;
  };
}

interface TokenUsage {
  total_prompt_tokens?: number;
  total_completion_tokens?: number;
  total_calls?: number;
}

interface AgentStats {
  total_active_sessions?: number;
  total_messages?: number;
  total_llm_calls?: number;
  total_tool_calls?: number;
}

export function OperationsSettings({ connection }: { connection: Connection }) {
  const [backups, setBackups] = useState<BackupMeta[] | null>(null);
  const [usage, setUsage] = useState<TokenUsage | null>(null);
  const [stats, setStats] = useState<AgentStats | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [progress, setProgress] = useState<number | null>(null);

  const load = useCallback(async () => {
    const client = new QwenPawClient(connection);
    try {
      const [backupValue, usageValue, statsValue] = await Promise.all([
        client.inspectModule("/backups"),
        client.inspectModule(`/token-usage?${dateQuery()}`),
        client.inspectModule(`/agent-stats?${dateQuery()}`),
      ]);
      setError(null);
      setBackups(Array.isArray(backupValue) ? backupValue as BackupMeta[] : []);
      setUsage(usageValue as TokenUsage);
      setStats(statsValue as AgentStats);
    } catch (reason) {
      setError(errorMessage(reason));
    }
  }, [connection]);

  useEffect(() => {
    const task = setTimeout(() => void load(), 0);
    return () => clearTimeout(task);
  }, [load]);

  const createBackup = () => {
    MobileAlert.alert(
      "创建完整备份？",
      "包含当前 Agent、全局配置、凭据与 Skill Pool。",
      [
        { text: "取消", style: "cancel" },
        {
          text: "创建",
          onPress: () => void run(async () => {
            setProgress(0);
            await new QwenPawClient(connection).createBackup({
              name: `Mobile ${new Date().toLocaleString()}`,
              description: "Created from QwenPaw Mobile",
              scope: {
                include_agents: true,
                include_global_config: true,
                include_secrets: true,
                include_skill_pool: true,
              },
              agents: [connection.agentId],
            }, setProgress);
          }, "备份已创建"),
        },
      ],
    );
  };

  const openBackup = (backup: BackupMeta) => {
    MobileAlert.alert(backup.name, "选择要执行的操作。", [
      { text: "取消", style: "cancel" },
      {
        text: "导出",
        onPress: () => void exportBackup(backup),
      },
      {
        text: "恢复",
        onPress: () => void confirmRestore(backup),
      },
      {
        text: "删除",
        style: "destructive",
        onPress: () => confirmDelete(backup),
      },
    ]);
  };

  const importBackup = async () => {
    const result = await DocumentPicker.getDocumentAsync({
      type: ["application/zip", "application/octet-stream"],
    });
    if (result.canceled) return;
    await run(
      () => new QwenPawClient(connection).uploadModule(
        "/backups/import",
        [{
          field: "file",
          uri: result.assets[0].uri,
          name: result.assets[0].name,
          mimeType: result.assets[0].mimeType,
        }],
      ),
      "备份已导入",
    );
  };

  const exportBackup = async (backup: BackupMeta) => {
    if (busy) return;
    setBusy(true);
    try {
      const data = await new QwenPawClient(connection).downloadModule(
        `/backups/${encodeURIComponent(backup.id)}/export`,
      );
      const safeName = backup.name.replace(/[^a-zA-Z0-9._-]+/g, "-") || "qwenpaw-backup";
      const file = new File(Paths.cache, `${safeName}.zip`);
      file.create({ overwrite: true, intermediates: true });
      file.write(data.bytes);
      await Sharing.shareAsync(file.uri, { mimeType: data.contentType });
    } catch (reason) {
      MobileAlert.alert("导出失败", errorMessage(reason));
    } finally {
      setBusy(false);
    }
  };

  const confirmRestore = async (backup: BackupMeta) => {
    setBusy(true);
    try {
      const client = new QwenPawClient(connection);
      const detail = await client.inspectModule(`/backups/${encodeURIComponent(backup.id)}`) as {
        workspace_stats?: Record<string, unknown>;
      };
      const agents = Object.keys(detail.workspace_stats ?? {});
      MobileAlert.alert(
        "恢复此备份？",
        "QwenPaw 会重载受影响的 Agent。当前数据可能被备份内容覆盖。",
        [
          { text: "取消", style: "cancel" },
          {
            text: "恢复",
            style: "destructive",
            onPress: () => void run(
              () => client.mutateModule(
                `/backups/${encodeURIComponent(backup.id)}/restore`,
                "POST",
                {
                  include_agents: Boolean(backup.scope?.include_agents),
                  agent_ids: agents,
                  include_global_config: Boolean(backup.scope?.include_global_config),
                  include_secrets: Boolean(backup.scope?.include_secrets),
                  include_skill_pool: Boolean(backup.scope?.include_skill_pool),
                  mode: "full",
                  preserve_local_protected_config: true,
                },
              ),
              "备份已恢复",
            ),
          },
        ],
      );
    } catch (reason) {
      MobileAlert.alert("无法读取备份", errorMessage(reason));
    } finally {
      setBusy(false);
    }
  };

  const confirmDelete = (backup: BackupMeta) => {
    MobileAlert.alert("删除备份？", backup.name, [
      { text: "取消", style: "cancel" },
      {
        text: "删除",
        style: "destructive",
        onPress: () => void run(
          () => new QwenPawClient(connection).mutateModule(
            "/backups/delete",
            "POST",
            { ids: [backup.id] },
          ),
          "备份已删除",
        ),
      },
    ]);
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
      setProgress(null);
    }
  };

  if (error) return <ModuleError message={error} onRetry={() => void load()} />;
  if (!backups || !usage || !stats) return <ModuleLoading />;

  return (
    <>
      <IosGroup title="最近 30 天">
        <IosRow
          icon={BarChart3}
          label="Token 用量"
          subtitle={`${number(usage.total_calls)} 次模型调用`}
          trailing={number(
            (usage.total_prompt_tokens ?? 0) +
            (usage.total_completion_tokens ?? 0),
          )}
        />
        <IosRow
          icon={Upload}
          iconTone="ink"
          label="导入备份"
          onPress={busy ? undefined : () => void importBackup()}
          subtitle="从 QwenPaw 备份 ZIP 恢复"
        />
        <IosRow
          icon={MessageSquare}
          iconTone="ink"
          label="消息"
          subtitle={`${number(stats.total_active_sessions)} 个活跃会话`}
          trailing={number(stats.total_messages)}
        />
        <IosRow
          icon={Wrench}
          label="工具调用"
          subtitle={`${number(stats.total_llm_calls)} 次 LLM 调用`}
          trailing={number(stats.total_tool_calls)}
        />
      </IosGroup>

      <IosGroup title={`备份 · ${backups.length}`}>
        <IosRow
          icon={Plus}
          label={progress === null ? "创建完整备份" : `正在备份 ${progress}%`}
          onPress={busy ? undefined : createBackup}
          subtitle="当前 Agent、配置、凭据与 Skill Pool"
        />
        {backups.map((backup) => (
          <IosRow
            icon={DatabaseBackup}
            iconTone="ink"
            key={backup.id}
            label={backup.name}
            onPress={() => openBackup(backup)}
            subtitle={`${backup.agent_count ?? 0} 个 Agent · ${formatDate(backup.created_at)}`}
            trailing="管理"
          />
        ))}
      </IosGroup>
      {!backups.length ? (
        <ModuleEmpty
          icon={Archive}
          title="还没有备份"
          subtitle="创建后可在本地或云端 QwenPaw 中恢复。"
        />
      ) : null}
      <ModuleFooter>
        统计按当前 Agent 计算；备份存放在当前 QwenPaw，不上传到 App。
      </ModuleFooter>
    </>
  );
}

function dateQuery(): string {
  const end = new Date();
  const start = new Date(end);
  start.setDate(end.getDate() - 29);
  return new URLSearchParams({
    start_date: dateValue(start),
    end_date: dateValue(end),
  }).toString();
}

function dateValue(value: Date): string {
  const year = value.getFullYear();
  const month = String(value.getMonth() + 1).padStart(2, "0");
  const day = String(value.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

function number(value?: number): string {
  return new Intl.NumberFormat().format(value ?? 0);
}

function formatDate(value: string): string {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleDateString();
}

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : "操作失败";
}
