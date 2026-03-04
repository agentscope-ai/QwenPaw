import { useState, useEffect } from "react";
import api from "../../../api";

export function useChannels() {
  const [channels, setChannels] = useState<
    Record<string, Record<string, unknown>>
  >({});
  const [channelTypes, setChannelTypes] = useState<string[]>([]);
  const [loading, setLoading] = useState(true);

  const fetchChannels = async () => {
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
  };

  useEffect(() => {
    fetchChannels();
  }, []);

  // Built-in channels come first (in a fixed order), then custom channels
  const builtinOrder = [
    "console",
    "dingtalk",
    "feishu",
    "imessage",
    "discord",
    "telegram",
    "qq",
  ];

  const orderedKeys = [
    ...builtinOrder.filter((k) => channelTypes.includes(k)),
    ...channelTypes.filter((k) => !builtinOrder.includes(k)),
  ];

  // Read isBuiltin from API response
  const isBuiltin = (key: string) => Boolean(channels[key]?.isBuiltin);

  return {
    channels,
    channelTypes,
    orderedKeys,
    isBuiltin,
    loading,
    fetchChannels,
  };
}
