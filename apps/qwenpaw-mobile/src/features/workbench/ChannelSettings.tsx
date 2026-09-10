import { MobileAlert } from "@/components/MobileAlert";
import { MessageCircleMore } from "lucide-react-native";
import { useCallback, useEffect, useState } from "react";
import { Switch } from "react-native";

import { QwenPawClient } from "../../api/client";
import type { Connection } from "../../api/types";
import { IosGroup, IosRow } from "../../components/IosList";
import { colors } from "../../theme/tokens";
import { DynamicConfigSheet } from "./DynamicConfigSheet";
import type { DynamicField } from "./DynamicConfigSheet";
import { ChannelAccessSettings } from "./ChannelAccessSettings";
import { ModuleEmpty, ModuleError, ModuleFooter, ModuleLoading } from "./ModuleState";

type ChannelMap = Record<string, Record<string, unknown>>;
type ChannelSchemas = Record<string, { config_fields?: unknown[] }>;

export function ChannelSettings({ connection }: { connection: Connection }) {
  const [channels, setChannels] = useState<ChannelMap | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState<string | null>(null);
  const [schemas, setSchemas] = useState<ChannelSchemas>({});
  const [editing, setEditing] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const client = new QwenPawClient(connection);
      const [value, schemaValue] = await Promise.all([
        client.inspectModule("/config/channels"),
        client.inspectModule("/config/channels/schemas"),
      ]);
      setError(null);
      setChannels(isRecord(value) ? normalizeChannels(value) : {});
      setSchemas(isRecord(schemaValue) ? schemaValue as ChannelSchemas : {});
    } catch (reason) {
      setError(errorMessage(reason));
    }
  }, [connection]);

  useEffect(() => {
    const task = setTimeout(() => void load(), 0);
    return () => clearTimeout(task);
  }, [load]);

  const toggle = useCallback(async (key: string) => {
    const current = channels?.[key];
    if (!current || saving) return;
    setSaving(key);
    try {
      const next = { ...current, enabled: current.enabled !== true };
      const saved = await new QwenPawClient(connection)
        .mutateModule<Record<string, unknown>>(
          `/config/channels/${encodeURIComponent(key)}`,
          "PUT",
          next,
        );
      setChannels((value) => value ? { ...value, [key]: saved } : value);
    } catch (reason) {
      MobileAlert.alert("渠道设置保存失败", errorMessage(reason));
    } finally {
      setSaving(null);
    }
  }, [channels, connection, saving]);

  if (error) return <ModuleError message={error} onRetry={() => void load()} />;
  if (!channels) return <ModuleLoading />;
  const entries = Object.entries(channels);
  if (!entries.length) {
    return (
      <ModuleEmpty
        icon={MessageCircleMore}
        title="暂无渠道"
        subtitle="当前 QwenPaw 没有返回可配置消息渠道。"
      />
    );
  }

  return (
    <>
      <ChannelAccessSettings connection={connection} />
      <IosGroup title="消息渠道">
        {entries.map(([key, channel]) => (
          <IosRow
            accessory={(
              <Switch
                disabled={saving !== null}
                ios_backgroundColor={colors.hairline}
                onValueChange={() => void toggle(key)}
                trackColor={{ false: colors.hairline, true: colors.accent }}
                value={channel.enabled === true}
              />
            )}
            icon={MessageCircleMore}
            key={key}
            label={channelLabel(key)}
            onPress={() => setEditing(key)}
            subtitle={channel.enabled === true ? "已连接并接收消息" : "未启用"}
          />
        ))}
      </IosGroup>
      <ModuleFooter>点击渠道编辑账号、凭据、消息呈现与访问策略；开关立即保存。</ModuleFooter>
      {editing && channels[editing] ? (
        <DynamicConfigSheet
          fields={channelFields(editing, schemas[editing])}
          onClose={() => setEditing(null)}
          onSave={async (values) => {
            const current = channels[editing];
            const saved = await new QwenPawClient(connection)
              .mutateModule<Record<string, unknown>>(
                `/config/channels/${encodeURIComponent(editing)}`,
                "PUT",
                { ...current, ...values },
              );
            setChannels((state) => state
              ? { ...state, [editing]: saved }
              : state);
          }}
          title={channelLabel(editing)}
          values={channels[editing]}
        />
      ) : null}
    </>
  );
}

const commonFields: DynamicField[] = [
  { name: "bot_prefix", label: "机器人前缀", type: "text" },
  { name: "show_tool_calls", label: "显示工具调用", type: "boolean", default: true },
  { name: "show_tool_results", label: "显示工具结果", type: "boolean", default: true },
  { name: "show_thinking", label: "显示思考过程", type: "boolean", default: false },
  { name: "access_control_dm", label: "允许私聊", type: "boolean", default: true },
  { name: "access_control_group", label: "允许群聊", type: "boolean", default: true },
  { name: "require_mention", label: "群聊需要 @", type: "boolean", default: true },
];

const builtinFields: Record<string, DynamicField[]> = {
  dingtalk: [
    secret("client_id", "Client ID"),
    secret("client_secret", "Client Secret"),
  ],
  feishu: [
    secret("app_id", "App ID"),
    secret("app_secret", "App Secret"),
    secret("encrypt_key", "Encrypt Key"),
    secret("verification_token", "Verification Token"),
  ],
  telegram: [
    secret("bot_token", "Bot Token"),
    textField("base_url", "API Base URL"),
    textField("http_proxy", "HTTP Proxy"),
  ],
  discord: [
    secret("bot_token", "Bot Token"),
    textField("http_proxy", "HTTP Proxy"),
  ],
  slack: [secret("bot_token", "Bot Token"), secret("app_token", "App Token")],
  wecom: [textField("bot_id", "Bot ID"), secret("secret", "Secret")],
  wechat: [secret("bot_token", "Bot Token"), textField("bot_token_file", "Token File")],
  qq: [textField("app_id", "App ID"), secret("client_secret", "Client Secret")],
  mattermost: [textField("url", "Server URL"), secret("bot_token", "Bot Token")],
  matrix: [
    textField("homeserver", "Homeserver URL"),
    textField("user_id", "User ID"),
    secret("access_token", "Access Token"),
    secret("password", "Password"),
  ],
  mqtt: [
    textField("host", "Host"),
    { name: "port", label: "Port", type: "number", default: 1883 },
    textField("username", "Username"),
    secret("password", "Password"),
    textField("subscribe_topic", "Subscribe Topic"),
    textField("publish_topic", "Publish Topic"),
  ],
  imessage: [textField("db_path", "Messages DB Path")],
};

function channelFields(
  key: string,
  schema?: { config_fields?: unknown[] },
): DynamicField[] {
  const plugin = Array.isArray(schema?.config_fields)
    ? schema.config_fields.flatMap(normalizeSchemaField)
    : [];
  return [...(plugin.length ? plugin : builtinFields[key] ?? []), ...commonFields];
}

function normalizeSchemaField(value: unknown): DynamicField[] {
  if (!isRecord(value)) return [];
  const name = typeof value.name === "string" ? value.name : "";
  const type = value.type === "switch" ? "boolean" : value.type;
  if (!name || typeof type !== "string" || ![
    "text", "password", "number", "boolean", "select",
  ].includes(type)) return [];
  return [{
    name,
    label: localized(value.label) || name,
    type: type as DynamicField["type"],
    required: value.required === true,
    placeholder: localized(value.placeholder) || undefined,
    help: localized(value.help) || undefined,
    options: Array.isArray(value.options)
      ? value.options.filter((item): item is string => typeof item === "string")
      : undefined,
    default: value.default,
  }];
}

function localized(value: unknown): string {
  if (typeof value === "string") return value;
  if (!isRecord(value)) return "";
  for (const key of ["zh-CN", "zh", "en-US", "en"]) {
    if (typeof value[key] === "string") return value[key] as string;
  }
  return Object.values(value).find((item): item is string => typeof item === "string") ?? "";
}

function textField(name: string, label: string): DynamicField {
  return { name, label, type: "text" };
}

function secret(name: string, label: string): DynamicField {
  return { name, label, type: "password" };
}

function normalizeChannels(value: Record<string, unknown>): ChannelMap {
  return Object.fromEntries(Object.entries(value).flatMap(([key, channel]) => (
    isRecord(channel) ? [[key, channel]] : []
  )));
}

function channelLabel(key: string): string {
  const names: Record<string, string> = {
    console: "Console",
    dingtalk: "钉钉",
    feishu: "飞书",
    wechat: "微信",
    wecom: "企业微信",
    telegram: "Telegram",
    discord: "Discord",
    slack: "Slack",
    imessage: "iMessage",
    mattermost: "Mattermost",
    mqtt: "MQTT",
    matrix: "Matrix",
    qq: "QQ",
  };
  return names[key] ?? key;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : "读取失败";
}
