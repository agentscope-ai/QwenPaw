import { MobileAlert } from "@/components/MobileAlert";
import type { LucideIcon } from "lucide-react-native";
import { Wrench } from "lucide-react-native";
import { useCallback, useEffect, useMemo, useState } from "react";
import { Switch } from "react-native";

import { QwenPawClient } from "../../api/client";
import type { Connection } from "../../api/types";
import { IosGroup, IosRow } from "../../components/IosList";
import { colors } from "../../theme/tokens";
import { DynamicConfigSheet } from "./DynamicConfigSheet";
import type { DynamicField } from "./DynamicConfigSheet";
import { ModuleEmpty, ModuleError, ModuleFooter, ModuleLoading } from "./ModuleState";

type CollectionKind = "tools";

interface ToggleItem {
  id: string;
  title: string;
  subtitle: string;
  enabled: boolean;
  fields: DynamicField[];
  values: Record<string, unknown>;
}

const configs: Record<CollectionKind, {
  empty: string;
  endpoint: string;
  footer: string;
  icon: LucideIcon;
  title: string;
}> = {
  tools: {
    empty: "当前 QwenPaw 没有返回可配置工具。",
    endpoint: "/tools",
    footer: "关闭工具会立即阻止 Agent 在后续轮次中调用它。",
    icon: Wrench,
    title: "内置 Tools",
  },
};

export function ToggleCollectionSettings({
  connection,
  kind,
}: {
  connection: Connection;
  kind: CollectionKind;
}) {
  const config = configs[kind];
  const [items, setItems] = useState<ToggleItem[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [savingId, setSavingId] = useState<string | null>(null);
  const [editing, setEditing] = useState<ToggleItem | null>(null);

  const load = useCallback(async () => {
    try {
      const payload = await new QwenPawClient(connection)
        .inspectModule(config.endpoint);
      setError(null);
      setItems(normalizeItems(kind, payload));
    } catch (reason) {
      setError(errorMessage(reason));
    }
  }, [config.endpoint, connection, kind]);

  useEffect(() => {
    const task = setTimeout(() => void load(), 0);
    return () => clearTimeout(task);
  }, [load]);

  const enabledCount = useMemo(
    () => items?.filter((item) => item.enabled).length ?? 0,
    [items],
  );

  const toggle = useCallback(async (item: ToggleItem) => {
    if (savingId) return;
    setSavingId(item.id);
    try {
      const client = new QwenPawClient(connection);
      if (kind === "tools") {
        await client.mutateModule(
          `/tools/${encodeURIComponent(item.id)}/toggle`,
          "PATCH",
        );
      }
      setItems((current) => current?.map((candidate) => (
        candidate.id === item.id
          ? { ...candidate, enabled: !candidate.enabled }
          : candidate
      )) ?? null);
    } catch (reason) {
      MobileAlert.alert("保存失败", errorMessage(reason));
    } finally {
      setSavingId(null);
    }
  }, [connection, kind, savingId]);

  if (error) return <ModuleError message={error} onRetry={() => void load()} />;
  if (!items) return <ModuleLoading />;
  if (!items.length) {
    return <ModuleEmpty icon={config.icon} title="暂无配置" subtitle={config.empty} />;
  }

  return (
    <>
      <IosGroup title={`${config.title} · ${enabledCount}/${items.length} 已启用`}>
        {items.map((item) => (
          <IosRow
            accessory={(
              <Switch
                disabled={savingId !== null}
                ios_backgroundColor={colors.hairline}
                onValueChange={() => void toggle(item)}
                trackColor={{ false: colors.hairline, true: colors.accent }}
                value={item.enabled}
              />
            )}
            icon={config.icon}
            iconTone="ink"
            key={item.id}
            label={item.title}
            onPress={() => setEditing(item)}
            subtitle={item.subtitle}
          />
        ))}
      </IosGroup>
      <ModuleFooter>{config.footer}</ModuleFooter>
      {editing ? (
        <DynamicConfigSheet
          fields={editing.fields}
          onClose={() => setEditing(null)}
          onSave={async (values) => {
            const asyncExecution = values.__async_execution === true;
            const toolConfig = Object.fromEntries(
              Object.entries(values).filter(([key]) => key !== "__async_execution"),
            );
            const client = new QwenPawClient(connection);
            await client.mutateModule(
              `/tools/${encodeURIComponent(editing.id)}/async-execution`,
              "PATCH",
              { async_execution: asyncExecution },
            );
            if (editing.fields.some((field) => field.name !== "__async_execution")) {
              await client.mutateModule(
                `/tools/${encodeURIComponent(editing.id)}/config`,
                "POST",
                { config: toolConfig },
              );
            }
            await load();
          }}
          title={editing.title}
          values={editing.values}
        />
      ) : null}
    </>
  );
}

function normalizeItems(kind: CollectionKind, payload: unknown): ToggleItem[] {
  if (!Array.isArray(payload)) return [];
  return payload.flatMap((value) => {
    if (!value || typeof value !== "object") return [];
    const item = value as Record<string, unknown>;
    const id = stringValue(item.name);
    if (!id) return [];
    const title = stringValue(item.name) || id;
    const description = stringValue(item.description);
    const source = stringValue(item.source || item.transport);
    const fields = normalizeFields(item.config_fields);
    fields.push({
      name: "__async_execution",
      label: "后台异步执行",
      type: "boolean",
      help: "允许耗时工具在后台执行，不阻塞当前轮次。",
    });
    return [{
      id,
      title,
      subtitle: description || source || "未提供说明",
      enabled: item.enabled === true,
      fields,
      values: {
        ...(isRecord(item.config_values) ? item.config_values : {}),
        __async_execution: item.async_execution === true,
      },
    }];
  });
}

function normalizeFields(value: unknown): DynamicField[] {
  if (!Array.isArray(value)) return [];
  return value.flatMap((entry) => {
    if (!isRecord(entry)) return [];
    const name = stringValue(entry.name);
    const label = stringValue(entry.label);
    const type = stringValue(entry.type) as DynamicField["type"];
    if (!name || !label || ![
      "text", "password", "number", "boolean", "select", "textarea",
    ].includes(type)) return [];
    return [{
      name,
      label,
      type,
      required: entry.required === true,
      placeholder: stringValue(entry.placeholder) || undefined,
      help: stringValue(entry.help) || undefined,
      options: Array.isArray(entry.options)
        ? entry.options.filter((item): item is string => typeof item === "string")
        : undefined,
      default: entry.default,
    }];
  });
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

function stringValue(value: unknown): string {
  return typeof value === "string" ? value : "";
}

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : "读取失败";
}
