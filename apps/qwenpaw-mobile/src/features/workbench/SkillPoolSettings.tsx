import { MobileAlert } from "@/components/MobileAlert";
import * as DocumentPicker from "expo-document-picker";
import { Download, Library, Plus, RefreshCw, Upload } from "lucide-react-native";
import { useCallback, useEffect, useState } from "react";

import { QwenPawClient } from "../../api/client";
import type { Connection } from "../../api/types";
import { IosGroup, IosRow } from "../../components/IosList";
import { DynamicConfigSheet } from "./DynamicConfigSheet";
import { ModuleEmpty, ModuleError, ModuleFooter, ModuleLoading } from "./ModuleState";

interface PoolSkill {
  name: string;
  description?: string;
  source?: string;
  sync_status?: string;
  auto_update?: boolean;
  tags?: string[];
  content?: string;
  config?: Record<string, unknown>;
}

export function SkillPoolSettings({ connection }: { connection: Connection }) {
  const [skills, setSkills] = useState<PoolSkill[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState<string | null>(null);
  const [editing, setEditing] = useState<PoolSkill | "new" | null>(null);

  const load = useCallback(async () => {
    try {
      const value = await new QwenPawClient(connection).inspectModule("/skills/pool");
      setError(null);
      setSkills(Array.isArray(value) ? value as PoolSkill[] : []);
    } catch (reason) {
      setError(errorMessage(reason));
    }
  }, [connection]);

  useEffect(() => {
    const task = setTimeout(() => void load(), 0);
    return () => clearTimeout(task);
  }, [load]);

  const install = (skill: PoolSkill) => {
    MobileAlert.alert(
      `安装 ${skill.name}？`,
      `会复制到当前 Agent「${connection.agentId}」并执行安全扫描。`,
      [
        { text: "取消", style: "cancel" },
        {
          text: "安装",
          onPress: () => void (async () => {
            setSaving(skill.name);
            try {
              await new QwenPawClient(connection).mutateModule(
                "/skills/pool/download",
                "POST",
                {
                  skill_name: skill.name,
                  targets: [{ workspace_id: connection.agentId }],
                  all_workspaces: false,
                  overwrite: false,
                  preview_only: false,
                },
              );
              MobileAlert.alert("已安装", `${skill.name} 已加入当前 Agent。`);
            } catch (reason) {
              MobileAlert.alert("安装失败", errorMessage(reason));
            } finally {
              setSaving(null);
            }
          })(),
        },
      ],
    );
  };

  const actions = (skill: PoolSkill) => {
    MobileAlert.alert(skill.name, skill.description || skill.source || "Skill Pool", [
      { text: "取消", style: "cancel" },
      { text: "安装到当前 Agent", onPress: () => install(skill) },
      {
        text: "编辑",
        onPress: () => void new QwenPawClient(connection).inspectModule(
          `/skills/pool/${encodeURIComponent(skill.name)}`,
        ).then((value) => setEditing(value as PoolSkill))
          .catch((reason) => MobileAlert.alert("读取失败", errorMessage(reason))),
      },
      {
        text: "删除",
        style: "destructive",
        onPress: () => MobileAlert.alert("删除 Pool Skill？", "已安装到 Agent 的副本不会被删除。", [
          { text: "取消", style: "cancel" },
          {
            text: "删除",
            style: "destructive",
            onPress: () => void new QwenPawClient(connection).mutateModule(
              `/skills/pool/${encodeURIComponent(skill.name)}`,
              "DELETE",
            ).then(load).catch((reason) => MobileAlert.alert("删除失败", errorMessage(reason))),
          },
        ]),
      },
    ]);
  };

  const uploadZip = async () => {
    const result = await DocumentPicker.getDocumentAsync({ type: "application/zip" });
    if (result.canceled) return;
    setSaving("upload");
    try {
      await new QwenPawClient(connection).uploadModule(
        "/skills/pool/upload-zip",
        [{
          field: "file",
          uri: result.assets[0].uri,
          name: result.assets[0].name,
          mimeType: result.assets[0].mimeType,
        }],
      );
      await load();
    } catch (reason) {
      MobileAlert.alert("导入失败", errorMessage(reason));
    } finally {
      setSaving(null);
    }
  };

  if (error) return <ModuleError message={error} onRetry={() => void load()} />;
  if (!skills) return <ModuleLoading />;

  return (
    <>
      <IosGroup title={`Skill Pool · ${skills.length}`}>
        <IosRow icon={Plus} label="新建 Pool Skill" onPress={() => setEditing("new")} />
        <IosRow
          icon={Upload}
          label="导入 ZIP"
          onPress={saving ? undefined : () => void uploadZip()}
          subtitle="导入前执行安全扫描"
        />
        <IosRow
          icon={RefreshCw}
          iconTone="ink"
          label="刷新 Skill Pool"
          onPress={() => void new QwenPawClient(connection)
            .mutateModule("/skills/pool/refresh", "POST")
            .then(load)
            .catch((reason) => MobileAlert.alert("刷新失败", errorMessage(reason)))}
        />
        {skills.map((skill) => (
          <IosRow
            icon={Download}
            key={skill.name}
            label={skill.name}
            onPress={saving ? undefined : () => actions(skill)}
            subtitle={skill.description || skill.source || "共享 Skill"}
            trailing={skill.sync_status || (skill.auto_update ? "自动同步" : "安装")}
          />
        ))}
      </IosGroup>
      {!skills.length ? (
        <ModuleEmpty
          icon={Library}
          title="Skill Pool 为空"
          subtitle="当前 QwenPaw 尚未添加可跨 Agent 复用的 Skill。"
        />
      ) : null}
      <ModuleFooter>安装操作只写入当前 Agent；Skill Pool 原件保持不变。</ModuleFooter>
      {editing ? (
        <DynamicConfigSheet
          fields={[
            { name: "name", label: "Skill 名称", type: "text", required: true },
            { name: "content", label: "SKILL.md", type: "textarea", required: true },
            { name: "tags", label: "标签", type: "text", help: "用逗号分隔。" },
            { name: "config", label: "Config", type: "textarea", help: "可选 JSON 对象。" },
          ]}
          onClose={() => setEditing(null)}
          onSave={async (values) => {
            const current = editing === "new" ? null : editing;
            const payload = {
              name: String(values.name || "").trim(),
              content: String(values.content || ""),
              ...(current ? { source_name: current.name, overwrite: false } : {}),
              config: parseConfig(values.config),
            };
            const client = new QwenPawClient(connection);
            const result = await client.mutateModule<{ name?: string }>(
              current ? "/skills/pool/save" : "/skills/pool/create",
              current ? "PUT" : "POST",
              payload,
            );
            const tags = String(values.tags || "").split(",")
              .map((tag) => tag.trim()).filter(Boolean);
            if (tags.length) {
              await client.mutateModule(
                `/skills/pool/${encodeURIComponent(result.name || payload.name)}/tags`,
                "PUT",
                tags,
              );
            }
            await load();
          }}
          title={editing === "new" ? "新建 Pool Skill" : `编辑 ${editing.name}`}
          values={editing === "new" ? { config: "{}" } : {
            name: editing.name,
            content: editing.content ?? "",
            tags: (editing.tags ?? []).join(", "),
            config: JSON.stringify(editing.config ?? {}, null, 2),
          }}
        />
      ) : null}
    </>
  );
}

function parseConfig(value: unknown): Record<string, unknown> {
  const text = String(value || "").trim();
  if (!text) return {};
  try {
    const parsed = JSON.parse(text) as unknown;
    if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) throw new Error();
    return parsed as Record<string, unknown>;
  } catch {
    throw new Error("Config 必须是有效的 JSON 对象。");
  }
}

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : "操作失败";
}
