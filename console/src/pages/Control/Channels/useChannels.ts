import { useState, useEffect, useCallback, useMemo, useRef } from "react";
import api from "../../../api";
import type { ChannelSchema } from "../../../api/modules/channel";
import type { UserChannelBinding } from "../../../api/modules/channelBindings";
import { useAgentStore } from "../../../stores/agentStore";

export type ChannelViewMode = "agent" | "user";

const BUILTIN_ORDER = [
  "console",
  "dingtalk",
  "feishu",
  "imessage",
  "discord",
  "telegram",
  "qq",
  "wechat",
  "wecom",
  "yuanbao",
  "matrix",
  "sip",
  "xiaoyi",
  "mqtt",
  "mattermost",
  "slack",
  "voice",
  "onebot",
];

function bindingConfigs(
  types: string[],
  bindings: UserChannelBinding[],
): Record<string, Record<string, unknown>> {
  const byType = new Map(
    bindings.map((binding) => [binding.channel_type, binding]),
  );
  return Object.fromEntries(
    types.map((type) => {
      const binding = byType.get(type);
      return [
        type,
        {
          enabled: binding?.enabled ?? false,
          bot_prefix: "",
          ...(binding?.config ?? {}),
          display_name: binding?.display_name ?? "",
          isBuiltin: BUILTIN_ORDER.includes(type),
          ...(binding ? { bindingId: binding.id } : {}),
          configuredSecretFields: binding?.configured_secret_fields ?? [],
        },
      ];
    }),
  );
}

export function useChannels(mode: ChannelViewMode = "agent") {
  const { selectedAgent } = useAgentStore();
  const [channels, setChannels] = useState<
    Record<string, Record<string, unknown>>
  >({});
  const [channelTypes, setChannelTypes] = useState<string[]>([]);
  const [channelSchemas, setChannelSchemas] = useState<
    Record<string, ChannelSchema>
  >({});
  const [loading, setLoading] = useState(true);
  const requestIdRef = useRef(0);

  const fetchChannels = useCallback(async () => {
    const requestId = ++requestIdRef.current;
    setLoading(true);
    try {
      const types = await api.listChannelTypes();
      const data =
        mode === "user"
          ? bindingConfigs(
              types ?? [],
              await api.listUserChannelBindings(selectedAgent),
            )
          : await api.listChannels();
      if (requestId === requestIdRef.current) {
        if (data) setChannels(data as Record<string, Record<string, unknown>>);
        if (types) setChannelTypes(types);
      }
    } catch (error) {
      console.error("❌ Failed to load channels:", error);
    } finally {
      if (requestId === requestIdRef.current) setLoading(false);
    }
    // Fetch schemas separately so failures don't block core channel loading
    try {
      const schemas = await api.listChannelSchemas();
      if (schemas && requestId === requestIdRef.current) {
        setChannelSchemas(schemas);
      }
    } catch {
      // Plugin system may not be available; non-critical
    }
  }, [mode, selectedAgent]);

  useEffect(() => {
    fetchChannels();
  }, [fetchChannels, selectedAgent]);

  // Built-in channels come first (in a fixed order), then custom channels
  const builtinOrder = useMemo(() => BUILTIN_ORDER, []);

  const orderedKeys = useMemo(
    () => [
      ...builtinOrder.filter((k) => channelTypes.includes(k)),
      ...channelTypes.filter((k) => !builtinOrder.includes(k)),
    ],
    [builtinOrder, channelTypes],
  );

  // Read isBuiltin from API response
  const isBuiltin = useCallback(
    (key: string) => Boolean(channels[key]?.isBuiltin),
    [channels],
  );

  return {
    channels,
    channelTypes,
    channelSchemas,
    orderedKeys,
    isBuiltin,
    loading,
    fetchChannels,
  };
}
