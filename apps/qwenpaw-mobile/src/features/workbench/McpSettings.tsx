import { MobileAlert } from "@/components/MobileAlert";
import { Blocks, Plus } from "lucide-react-native";
import { useCallback, useEffect, useState } from "react";
import { Linking, Switch } from "react-native";

import { QwenPawClient } from "../../api/client";
import type { Connection } from "../../api/types";
import { IosGroup, IosRow } from "../../components/IosList";
import { colors } from "../../theme/tokens";
import { DynamicConfigSheet } from "./DynamicConfigSheet";
import type { DynamicField } from "./DynamicConfigSheet";
import { McpAccessSheet } from "./McpAccessSheet";
import { ModuleEmpty, ModuleError, ModuleFooter, ModuleLoading } from "./ModuleState";

interface McpClient {
  key: string;
  name: string;
  description?: string;
  enabled: boolean;
  transport: "stdio" | "streamable_http" | "sse";
  url?: string;
  command?: string;
  args?: string[];
  cwd?: string;
  headers?: Record<string, string>;
  env?: Record<string, string>;
  oauth_status?: { authorized?: boolean };
  access_summary?: { default_effect?: string; overrides_count?: number };
}

const baseFields: DynamicField[] = [
  { name: "name", label: "显示名称", type: "text", required: true },
  { name: "description", label: "说明", type: "textarea" },
  {
    name: "transport",
    label: "连接方式",
    type: "select",
    options: ["streamable_http", "sse", "stdio"],
    default: "streamable_http",
  },
  { name: "url", label: "HTTP / SSE URL", type: "text", placeholder: "https://example.com/mcp" },
  { name: "command", label: "Stdio Command", type: "text", placeholder: "npx" },
  { name: "args", label: "Stdio 参数", type: "textarea", help: "每行一个参数。" },
  { name: "cwd", label: "工作目录", type: "text" },
  { name: "headers", label: "HTTP Headers", type: "textarea", help: "填写 JSON 对象；凭据仅保存到当前 QwenPaw。" },
  { name: "env", label: "环境变量", type: "textarea", help: "填写 JSON 对象。" },
];

export function McpSettings({ connection }: { connection: Connection }) {
  const [clients, setClients] = useState<McpClient[] | null>(null);
  const [editing, setEditing] = useState<McpClient | "new" | null>(null);
  const [managingAccess, setManagingAccess] = useState<McpClient | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const value = await new QwenPawClient(connection).inspectModule("/mcp");
      setError(null);
      setClients(Array.isArray(value) ? value as McpClient[] : []);
    } catch (reason) {
      setError(errorMessage(reason));
    }
  }, [connection]);

  useEffect(() => {
    const task = setTimeout(() => void load(), 0);
    return () => clearTimeout(task);
  }, [load]);

  const toggle = async (client: McpClient) => {
    if (saving) return;
    setSaving(client.key);
    try {
      await new QwenPawClient(connection).mutateModule(
        `/mcp/toggle/${encodeURIComponent(client.key)}`,
        "PATCH",
      );
      await load();
    } catch (reason) {
      MobileAlert.alert("保存失败", errorMessage(reason));
    } finally {
      setSaving(null);
    }
  };

  const openActions = (client: McpClient) => {
    MobileAlert.alert(client.name, client.description || client.key, [
      { text: "取消", style: "cancel" },
      { text: "编辑", onPress: () => setEditing(client) },
      { text: "工具与权限", onPress: () => setManagingAccess(client) },
      ...(client.transport === "stdio" ? [] : [{
        text: client.oauth_status?.authorized ? "重新授权 OAuth" : "授权 OAuth",
        onPress: () => void startOAuth(client),
      }]),
      {
        text: "删除",
        style: "destructive",
        onPress: () => confirmDelete(client),
      },
    ]);
  };

  const startOAuth = async (client: McpClient) => {
    try {
      const value = await new QwenPawClient(connection).mutateModule<{
        auth_url: string;
      }>(`/mcp/oauth/start/${encodeURIComponent(client.key)}`, "POST", {
        url: client.url,
      });
      if (!value.auth_url) throw new Error("服务端没有返回授权地址。");
      await Linking.openURL(value.auth_url);
    } catch (reason) {
      MobileAlert.alert("OAuth 启动失败", errorMessage(reason));
    }
  };

  const confirmDelete = (client: McpClient) => {
    MobileAlert.alert("删除 MCP 服务？", client.name, [
      { text: "取消", style: "cancel" },
      {
        text: "删除",
        style: "destructive",
        onPress: () => void new QwenPawClient(connection).mutateModule(
          `/mcp/${encodeURIComponent(client.key)}`,
          "DELETE",
        ).then(load).catch((reason) => MobileAlert.alert("删除失败", errorMessage(reason))),
      },
    ]);
  };

  if (error) return <ModuleError message={error} onRetry={() => void load()} />;
  if (!clients) return <ModuleLoading />;

  const current = editing === "new" ? null : editing;
  const fields = editing === "new"
    ? [{ name: "key", label: "唯一标识", type: "text", required: true } as DynamicField, ...baseFields]
    : baseFields;

  return (
    <>
      <IosGroup title={`MCP 服务 · ${clients.length}`}>
        <IosRow
          icon={Plus}
          label="添加 MCP 服务"
          onPress={() => setEditing("new")}
          subtitle="Streamable HTTP、SSE 或 Stdio"
        />
        {clients.map((client) => (
          <IosRow
            accessory={(
              <Switch
                disabled={saving !== null}
                onValueChange={() => void toggle(client)}
                trackColor={{ false: colors.hairline, true: colors.accent }}
                value={client.enabled}
              />
            )}
            icon={Blocks}
            key={client.key}
            label={client.name}
            onPress={() => openActions(client)}
            subtitle={mcpSubtitle(client)}
          />
        ))}
      </IosGroup>
      {!clients.length ? (
        <ModuleEmpty
          icon={Blocks}
          title="还没有 MCP 服务"
          subtitle="添加后可直接启用，并由当前 Agent 调用。"
        />
      ) : null}
      <ModuleFooter>服务配置、开关与凭据直接保存到当前 Agent。</ModuleFooter>
      {editing ? (
        <DynamicConfigSheet
          fields={fields}
          onClose={() => setEditing(null)}
          onSave={async (values) => {
            const key = current?.key || String(values.key || "").trim();
            const client = toClientPayload(values, current);
            const api = new QwenPawClient(connection);
            if (current) {
              await api.mutateModule(
                `/mcp/${encodeURIComponent(current.key)}`,
                "PUT",
                client,
              );
            } else {
              await api.mutateModule("/mcp", "POST", { client_key: key, client });
            }
            await load();
          }}
          title={current ? `编辑 ${current.name}` : "添加 MCP 服务"}
          values={current ? editorValues(current) : { transport: "streamable_http" }}
        />
      ) : null}
      {managingAccess ? (
        <McpAccessSheet
          client={managingAccess}
          connection={connection}
          onClose={() => setManagingAccess(null)}
          onChanged={load}
        />
      ) : null}
    </>
  );
}

function toClientPayload(
  values: Record<string, unknown>,
  current: McpClient | null,
): Record<string, unknown> {
  const transport = String(values.transport || "streamable_http");
  const url = String(values.url || "").trim();
  const command = String(values.command || "").trim();
  if (transport === "stdio" && !command) {
    throw new Error("Stdio 服务必须填写 Command。");
  }
  if (transport !== "stdio" && !url) {
    throw new Error("HTTP / SSE 服务必须填写 URL。");
  }
  return {
    name: String(values.name || "").trim(),
    description: String(values.description || "").trim(),
    enabled: current?.enabled ?? true,
    transport,
    url,
    command,
    args: String(values.args || "").split("\n").map((item) => item.trim()).filter(Boolean),
    cwd: String(values.cwd || "").trim(),
    headers: jsonMap(values.headers, "HTTP Headers"),
    env: jsonMap(values.env, "环境变量"),
  };
}

function editorValues(client: McpClient): Record<string, unknown> {
  return {
    name: client.name,
    description: client.description ?? "",
    transport: client.transport,
    url: client.url ?? "",
    command: client.command ?? "",
    args: (client.args ?? []).join("\n"),
    cwd: client.cwd ?? "",
    headers: JSON.stringify(client.headers ?? {}, null, 2),
    env: JSON.stringify(client.env ?? {}, null, 2),
  };
}

function jsonMap(value: unknown, label: string): Record<string, string> {
  const text = String(value || "").trim();
  if (!text) return {};
  try {
    const parsed = JSON.parse(text) as unknown;
    if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
      throw new Error();
    }
    return Object.fromEntries(Object.entries(parsed as Record<string, unknown>).map(
      ([key, item]) => [key, String(item)],
    ));
  } catch {
    throw new Error(`${label} 必须是有效的 JSON 对象。`);
  }
}

function mcpSubtitle(client: McpClient): string {
  const access = client.access_summary?.default_effect;
  const oauth = client.oauth_status?.authorized ? " · OAuth 已授权" : "";
  return `${client.transport}${access ? ` · ${access}` : ""}${oauth}`;
}

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : "操作失败";
}
