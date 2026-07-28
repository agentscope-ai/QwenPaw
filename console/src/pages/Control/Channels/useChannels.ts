import { useState, useEffect, useCallback, useMemo } from "react";
import api from "../../../api";
import type {
  ChannelDependencyStatus,
  ChannelSchema,
} from "../../../api/modules/channel";
import { useAgentStore } from "../../../stores/agentStore";

export function useChannels() {
  const { selectedAgent } = useAgentStore();
  const [channels, setChannels] = useState<
    Record<string, Record<string, unknown>>
  >({});
  const [channelTypes, setChannelTypes] = useState<string[]>([]);
  const [channelSchemas, setChannelSchemas] = useState<
    Record<string, ChannelSchema>
  >({});
  const [dependencyStatuses, setDependencyStatuses] = useState<
    Record<string, ChannelDependencyStatus>
  >({});
  const [dependencyStatusesLoaded, setDependencyStatusesLoaded] =
    useState(false);
  const [dependencyStatusError, setDependencyStatusError] = useState(false);
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
    // Fetch schemas separately so failures don't block core channel loading
    try {
      const schemas = await api.listChannelSchemas();
      if (schemas) setChannelSchemas(schemas);
    } catch {
      // Plugin system may not be available; non-critical
    }
  }, []);

  const fetchDependencyStatuses = useCallback(async () => {
    setDependencyStatusesLoaded(false);
    setDependencyStatusError(false);
    try {
      const dependencies = await api.listChannelDependencies();
      if (dependencies) setDependencyStatuses(dependencies);
    } catch (error) {
      console.error("Failed to load channel dependency status:", error);
      setDependencyStatusError(true);
    } finally {
      setDependencyStatusesLoaded(true);
    }
  }, []);

  useEffect(() => {
    fetchChannels();
  }, [fetchChannels, selectedAgent]);

  useEffect(() => {
    fetchDependencyStatuses();
  }, [fetchDependencyStatuses]);

  const installingChannels = useMemo(
    () =>
      Object.values(dependencyStatuses)
        .filter((status) => status.status === "installing")
        .map((status) => status.channel)
        .sort(),
    [dependencyStatuses],
  );

  useEffect(() => {
    if (installingChannels.length === 0) return;
    let cancelled = false;
    let timer: number | undefined;

    const poll = async () => {
      const results = await Promise.allSettled(
        installingChannels.map((key) => api.recheckChannelDependencies(key)),
      );
      if (!cancelled) {
        setDependencyStatuses((current) => {
          const updated = { ...current };
          results.forEach((result) => {
            if (result.status === "fulfilled") {
              updated[result.value.channel] = result.value;
            }
          });
          return updated;
        });
      }
      if (!cancelled) timer = window.setTimeout(poll, 1000);
    };

    timer = window.setTimeout(poll, 1000);
    return () => {
      cancelled = true;
      if (timer !== undefined) window.clearTimeout(timer);
    };
  }, [installingChannels]);

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
      "wechat",
      "wecom",
      "yuanbao",
      "slack",
      "mqtt",
      "mattermost",
      "matrix",
      "voice",
      "sip",
      "xiaoyi",
      "onebot",
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

  const setChannelDependencyStatus = useCallback(
    (status: ChannelDependencyStatus) => {
      setDependencyStatuses((current) => ({
        ...current,
        [status.channel]: status,
      }));
    },
    [],
  );

  return {
    channels,
    channelTypes,
    channelSchemas,
    dependencyStatuses,
    dependencyStatusesLoaded,
    dependencyStatusError,
    setChannelDependencyStatus,
    orderedKeys,
    isBuiltin,
    loading,
    fetchChannels,
  };
}
