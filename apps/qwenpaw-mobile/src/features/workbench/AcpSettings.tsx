import { MobileAlert } from "@/components/MobileAlert";
import { Cpu, GitFork, Plus } from "lucide-react-native";
import { useCallback, useEffect, useState } from "react";
import { Switch } from "react-native";

import { QwenPawClient } from "../../api/client";
import type { Connection } from "../../api/types";
import { IosGroup, IosRow } from "../../components/IosList";
import { colors } from "../../theme/tokens";
import { DynamicConfigSheet } from "./DynamicConfigSheet";
import type { DynamicField } from "./DynamicConfigSheet";
import { ModuleEmpty, ModuleError, ModuleFooter, ModuleLoading } from "./ModuleState";

interface AcpAgent {
  enabled: boolean;
  command: string;
  args: string[];
  env: Record<string, string>;
  trusted: boolean;
  tool_parse_mode: "call_title" | "update_detail" | "call_detail";
  stdio_buffer_limit_bytes?: number;
}

interface AcpConfig {
  node_path?: string;
  agents: Record<string, AcpAgent>;
}

interface NodeRuntime {
  node_path: string;
  effective_node_path: string;
  candidates?: { label: string; available: boolean }[];
}

const agentFields: DynamicField[] = [
  { name: "name", label: "Agent 标识", type: "text", required: true },
  { name: "command", label: "Command", type: "text", required: true, placeholder: "npx" },
  { name: "args", label: "参数", type: "textarea", help: "每行一个参数。" },
  { name: "env", label: "环境变量", type: "textarea", help: "填写 JSON 对象。" },
  { name: "trusted", label: "信任此 ACP Agent", type: "boolean" },
  {
    name: "tool_parse_mode",
    label: "工具解析方式",
    type: "select",
    options: ["call_title", "update_detail", "call_detail"],
    default: "call_title",
  },
  {
    name: "stdio_buffer_limit_bytes",
    label: "Stdio 缓冲上限",
    type: "number",
    default: 52428800,
  },
];

export function AcpSettings({ connection }: { connection: Connection }) {
  const [config, setConfig] = useState<AcpConfig | null>(null);
  const [runtime, setRuntime] = useState<NodeRuntime | null>(null);
  const [editing, setEditing] = useState<string | "new" | "runtime" | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const client = new QwenPawClient(connection);
      const [nextConfig, nextRuntime] = await Promise.all([
        client.inspectModule("/config/acp"),
        client.inspectModule("/config/acp/node-runtime"),
      ]);
      setError(null);
      setConfig(nextConfig as AcpConfig);
      setRuntime(nextRuntime as NodeRuntime);
    } catch (reason) {
      setError(errorMessage(reason));
    }
  }, [connection]);

  useEffect(() => {
    const task = setTimeout(() => void load(), 0);
    return () => clearTimeout(task);
  }, [load]);

  const toggle = async (name: string, agent: AcpAgent) => {
    if (saving) return;
    setSaving(name);
    try {
      await new QwenPawClient(connection).mutateModule(
        `/config/acp/${encodeURIComponent(name)}`,
        "PUT",
        { ...agent, enabled: !agent.enabled },
      );
      await load();
    } catch (reason) {
      MobileAlert.alert("保存失败", errorMessage(reason));
    } finally {
      setSaving(null);
    }
  };

  const actions = (name: string) => {
    MobileAlert.alert(name, "ACP Agent", [
      { text: "取消", style: "cancel" },
      { text: "编辑", onPress: () => setEditing(name) },
      {
        text: "删除",
        style: "destructive",
        onPress: () => void saveWholeConfig(withoutAgent(config, name))
          .catch((reason) => MobileAlert.alert("删除失败", errorMessage(reason))),
      },
    ]);
  };

  const saveWholeConfig = async (next: AcpConfig) => {
    const saved = await new QwenPawClient(connection)
      .mutateModule<AcpConfig>("/config/acp", "PUT", next);
    setConfig(saved);
  };

  if (error) return <ModuleError message={error} onRetry={() => void load()} />;
  if (!config || !runtime) return <ModuleLoading />;
  const current = editing && !["new", "runtime"].includes(editing)
    ? config.agents[editing]
    : null;

  return (
    <>
      <IosGroup title="Node Runtime">
        <IosRow
          icon={Cpu}
          iconTone="ink"
          label="Node.js"
          onPress={() => setEditing("runtime")}
          subtitle={`${runtime.candidates?.filter((item) => item.available).length ?? 0} 个可用 Runtime`}
          trailing={runtime.effective_node_path || "未检测到"}
        />
      </IosGroup>
      <IosGroup title={`ACP Agents · ${Object.keys(config.agents).length}`}>
        <IosRow
          icon={Plus}
          label="添加 ACP Agent"
          onPress={() => setEditing("new")}
          subtitle="配置外部 Agent 命令和信任策略"
        />
        {Object.entries(config.agents).map(([name, agent]) => (
          <IosRow
            accessory={(
              <Switch
                disabled={saving !== null}
                onValueChange={() => void toggle(name, agent)}
                trackColor={{ false: colors.hairline, true: colors.accent }}
                value={agent.enabled}
              />
            )}
            icon={GitFork}
            key={name}
            label={name}
            onPress={() => actions(name)}
            subtitle={`${agent.command} · ${agent.trusted ? "受信任" : "需审批"}`}
          />
        ))}
      </IosGroup>
      {!Object.keys(config.agents).length ? (
        <ModuleEmpty
          icon={GitFork}
          title="还没有 ACP Agent"
          subtitle="添加后即可从会话中委派给外部 Agent。"
        />
      ) : null}
      <ModuleFooter>ACP 修改会触发当前 Agent 热重载。</ModuleFooter>
      {editing === "runtime" ? (
        <DynamicConfigSheet
          fields={[{ name: "node_path", label: "Node.js Path", type: "text" }]}
          onClose={() => setEditing(null)}
          onSave={async (values) => {
            await new QwenPawClient(connection).mutateModule(
              "/config/acp/node-runtime",
              "PUT",
              { node_path: String(values.node_path || "") },
            );
            await load();
          }}
          title="Node Runtime"
          values={{ node_path: runtime.node_path }}
        />
      ) : editing ? (
        <DynamicConfigSheet
          fields={agentFields}
          onClose={() => setEditing(null)}
          onSave={async (values) => {
            const name = String(values.name || "").trim();
            const sourceName = current ? String(editing) : "";
            const agent = agentPayload(values, current);
            let next = sourceName && sourceName !== name
              ? withoutAgent(config, sourceName)
              : config;
            next = { ...next, agents: { ...next.agents, [name]: agent } };
            await saveWholeConfig(next);
          }}
          title={current ? `编辑 ${editing}` : "添加 ACP Agent"}
          values={current ? editorValues(String(editing), current) : {
            trusted: false,
            tool_parse_mode: "call_title",
          }}
        />
      ) : null}
    </>
  );
}

function agentPayload(values: Record<string, unknown>, current: AcpAgent | null): AcpAgent {
  const command = String(values.command || "").trim();
  if (!command) throw new Error("Command 不能为空。");
  return {
    enabled: current?.enabled ?? true,
    command,
    args: String(values.args || "").split("\n").map((item) => item.trim()).filter(Boolean),
    env: jsonMap(values.env),
    trusted: values.trusted === true,
    tool_parse_mode: String(values.tool_parse_mode || "call_title") as AcpAgent["tool_parse_mode"],
    stdio_buffer_limit_bytes: Number(values.stdio_buffer_limit_bytes || 52428800),
  };
}

function editorValues(name: string, agent: AcpAgent): Record<string, unknown> {
  return {
    name,
    command: agent.command,
    args: agent.args.join("\n"),
    env: JSON.stringify(agent.env, null, 2),
    trusted: agent.trusted,
    tool_parse_mode: agent.tool_parse_mode,
    stdio_buffer_limit_bytes: agent.stdio_buffer_limit_bytes ?? 52428800,
  };
}

function withoutAgent(config: AcpConfig | null, name: string): AcpConfig {
  if (!config) return { agents: {} };
  const agents = { ...config.agents };
  delete agents[name];
  return { ...config, agents };
}

function jsonMap(value: unknown): Record<string, string> {
  const text = String(value || "").trim();
  if (!text) return {};
  try {
    const parsed = JSON.parse(text) as unknown;
    if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) throw new Error();
    return Object.fromEntries(Object.entries(parsed as Record<string, unknown>)
      .map(([key, item]) => [key, String(item)]));
  } catch {
    throw new Error("环境变量必须是有效的 JSON 对象。");
  }
}

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : "操作失败";
}
