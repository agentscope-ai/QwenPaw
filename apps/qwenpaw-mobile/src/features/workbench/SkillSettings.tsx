import { MobileAlert } from "@/components/MobileAlert";
import * as DocumentPicker from "expo-document-picker";
import { Plus, RefreshCw, Sparkles, Upload } from "lucide-react-native";
import { useCallback, useEffect, useState } from "react";
import { Switch } from "react-native";

import { QwenPawClient } from "../../api/client";
import type { Connection } from "../../api/types";
import { IosGroup, IosRow } from "../../components/IosList";
import { colors } from "../../theme/tokens";
import { DynamicConfigSheet } from "./DynamicConfigSheet";
import type { DynamicField } from "./DynamicConfigSheet";
import { ModuleEmpty, ModuleError, ModuleFooter, ModuleLoading } from "./ModuleState";

interface SkillSummary {
  name: string;
  description?: string;
  source?: string;
  enabled: boolean;
  channels?: string[];
  tags?: string[];
}

interface SkillDetail extends SkillSummary {
  content: string;
  config?: Record<string, unknown>;
}

const fields: DynamicField[] = [
  { name: "name", label: "Skill 名称", type: "text", required: true },
  {
    name: "content",
    label: "SKILL.md",
    type: "textarea",
    required: true,
    help: "保存前由当前 QwenPaw 执行安全扫描。",
  },
  { name: "config", label: "Config", type: "textarea", help: "可选 JSON 对象。" },
];

export function SkillSettings({ connection }: { connection: Connection }) {
  const [skills, setSkills] = useState<SkillSummary[] | null>(null);
  const [editing, setEditing] = useState<SkillDetail | "new" | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const value = await new QwenPawClient(connection).inspectModule("/skills");
      setError(null);
      setSkills(Array.isArray(value) ? value as SkillSummary[] : []);
    } catch (reason) {
      setError(errorMessage(reason));
    }
  }, [connection]);

  useEffect(() => {
    const task = setTimeout(() => void load(), 0);
    return () => clearTimeout(task);
  }, [load]);

  const toggle = async (skill: SkillSummary) => {
    if (saving) return;
    setSaving(skill.name);
    try {
      await new QwenPawClient(connection).mutateModule(
        `/skills/${encodeURIComponent(skill.name)}/${skill.enabled ? "disable" : "enable"}`,
        "POST",
      );
      await load();
    } catch (reason) {
      MobileAlert.alert("保存失败", errorMessage(reason));
    } finally {
      setSaving(null);
    }
  };

  const open = async (skill: SkillSummary) => {
    setSaving(skill.name);
    try {
      const detail = await new QwenPawClient(connection).inspectModule(
        `/skills/${encodeURIComponent(skill.name)}`,
      );
      setEditing(detail as SkillDetail);
    } catch (reason) {
      MobileAlert.alert("读取失败", errorMessage(reason));
    } finally {
      setSaving(null);
    }
  };

  const openActions = (skill: SkillSummary) => {
    MobileAlert.alert(skill.name, skill.description || skill.source || "Skill", [
      { text: "取消", style: "cancel" },
      { text: "编辑", onPress: () => void open(skill) },
      { text: "删除", style: "destructive", onPress: () => confirmDelete(skill) },
    ]);
  };

  const confirmDelete = (skill: SkillSummary) => {
    MobileAlert.alert("删除 Skill？", "会从当前 Agent workspace 移除；Skill Pool 不受影响。", [
      { text: "取消", style: "cancel" },
      {
        text: "删除",
        style: "destructive",
        onPress: () => void (async () => {
          const client = new QwenPawClient(connection);
          if (skill.enabled) {
            await client.mutateModule(
              `/skills/${encodeURIComponent(skill.name)}/disable`,
              "POST",
            );
          }
          await client.mutateModule(`/skills/${encodeURIComponent(skill.name)}`, "DELETE");
          setEditing(null);
          await load();
        })().catch((reason) => MobileAlert.alert("删除失败", errorMessage(reason))),
      },
    ]);
  };

  const uploadZip = async () => {
    const result = await DocumentPicker.getDocumentAsync({ type: "application/zip" });
    if (result.canceled) return;
    setSaving("upload");
    try {
      await new QwenPawClient(connection).uploadModule(
        "/skills/upload?enable=true",
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

  const current = editing === "new" ? null : editing;
  return (
    <>
      <IosGroup title={`已安装 Skills · ${skills.length}`}>
        <IosRow
          icon={Plus}
          label="新建 Skill"
          onPress={() => setEditing("new")}
          subtitle="创建并安全扫描 SKILL.md"
        />
        <IosRow
          icon={Upload}
          label="导入 Skill ZIP"
          onPress={saving ? undefined : () => void uploadZip()}
          subtitle="导入并启用到当前 Agent"
        />
        <IosRow
          icon={RefreshCw}
          iconTone="ink"
          label="刷新 Skills"
          onPress={() => void new QwenPawClient(connection)
            .mutateModule("/skills/refresh", "POST")
            .then(load)
            .catch((reason) => MobileAlert.alert("刷新失败", errorMessage(reason)))}
        />
        {skills.map((skill) => (
          <IosRow
            accessory={(
              <Switch
                disabled={saving !== null}
                onValueChange={() => void toggle(skill)}
                trackColor={{ false: colors.hairline, true: colors.accent }}
                value={skill.enabled}
              />
            )}
            icon={Sparkles}
            key={skill.name}
            label={skill.name}
            onPress={() => openActions(skill)}
            subtitle={skill.description || skill.source || "未提供说明"}
          />
        ))}
      </IosGroup>
      {!skills.length ? (
        <ModuleEmpty
          icon={Sparkles}
          title="还没有 Skill"
          subtitle="可以直接创建一个新的 SKILL.md。"
        />
      ) : null}
      <ModuleFooter>所有操作只影响当前 Agent workspace。</ModuleFooter>
      {editing ? (
        <DynamicConfigSheet
          fields={fields}
          onClose={() => setEditing(null)}
          onSave={async (values) => {
            const name = String(values.name || "").trim();
            const content = String(values.content || "");
            const config = parseConfig(values.config);
            const client = new QwenPawClient(connection);
            if (current) {
              await client.mutateModule("/skills/save", "PUT", {
                name,
                content,
                source_name: current.name,
                config,
                overwrite: false,
              });
            } else {
              await client.mutateModule("/skills", "POST", {
                name,
                content,
                config,
                enable: true,
              });
            }
            await load();
          }}
          title={current ? `编辑 ${current.name}` : "新建 Skill"}
          values={current ? {
            name: current.name,
            content: current.content,
            config: JSON.stringify(current.config ?? {}, null, 2),
          } : { config: "{}" }}
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
