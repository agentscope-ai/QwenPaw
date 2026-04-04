import { useState, useEffect, useCallback, useMemo } from "react";
import api from "../../../api";
import { useAgentStore } from "../../../stores/agentStore";

export function useChannels() {
  const { selectedAgent } = useAgentStore();
  const [channels, setChannels] = useState<
    Record<string, Record<string, unknown>>
  >({});
  const [channelTypes, setChannelTypes] = useState<string[]>([]);
  const [loading, setLoading] = useState(true);

  const fetchChannels = useCallback(async () => {
    setLoading(true);
    try {
      const [data, types] = await Promise.all([
        api.listChannels(),
        api.listChannelTypes(),
      ]);
      if (data)
        setChannels(data as unknown as Record<string, Record<string, unknown>>);
      if (types) setChannelTypes(types);
    } catch (error) {
      console.error("❌ Failed to load channels:", error);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchChannels();
  }, [fetchChannels, selectedAgent]);

  // Built-in channels come first (in a fixed order), then custom channels
  const builtinOrder = useMemo(
    () => [
      "console",
      "dingtalk",
      "feishu",
      "imessage",
      "discord",
      "telegram",
      "qq",
      "matrix",
      "xiaoyi",
      "signal",
      "whatsapp",
    ],
    [],
  );

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
    orderedKeys,
    isBuiltin,
    loading,
    fetchChannels,
  };
}
