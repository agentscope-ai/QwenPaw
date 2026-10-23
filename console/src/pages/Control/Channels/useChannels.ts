import { useState, useLayoutEffect, useCallback, useMemo, useRef } from "react";
import api from "../../../api";
import type { ChannelSchema } from "../../../api/modules/channel";
import { useAgentStore } from "../../../stores/agentStore";

export function useChannels() {
  const [channels, setChannels] = useState<
    Record<string, Record<string, unknown>>
  >({});
  const [channelTypes, setChannelTypes] = useState<string[]>([]);
  const [channelSchemas, setChannelSchemas] = useState<
    Record<string, ChannelSchema>
  >({});
  const [schemasLoading, setSchemasLoading] = useState(true);
  const [loading, setLoading] = useState(true);
  const generation = useRef(0);
  const controller = useRef<AbortController>();

  const fetchChannels = useCallback(async (schemasOnly = false) => {
    const agentId = useAgentStore.getState().selectedAgent || "default";
    const requestGeneration = ++generation.current;
    controller.current?.abort();
    const currentController = new AbortController();
    controller.current = currentController;
    const scope = { agentId, signal: currentController.signal };
    const current = () =>
      requestGeneration === generation.current &&
      !currentController.signal.aborted &&
      (useAgentStore.getState().selectedAgent || "default") === agentId;
    setSchemasLoading(true);
    setLoading(!schemasOnly);
    if (!schemasOnly) {
      try {
        const [data, types] = await Promise.all([
          api.listChannels(scope),
          api.listChannelTypes(scope),
        ]);
        if (!current()) return;
        if (data)
          setChannels(
            data as unknown as Record<string, Record<string, unknown>>,
          );
        if (types) setChannelTypes(types);
      } catch (error) {
        if (current()) console.error("❌ Failed to load channels:", error);
      } finally {
        if (current()) setLoading(false);
      }
    }
    if (!current()) return;
    // Fetch schemas separately so failures don't block core channel loading
    try {
      const schemas = await api.listChannelSchemas(scope);
      if (current() && schemas) setChannelSchemas(schemas);
    } catch {
      // Plugin system may not be available; non-critical
      if (current()) setChannelSchemas({});
    } finally {
      if (current()) setSchemasLoading(false);
    }
  }, []);

  useLayoutEffect(() => {
    const changeScope = () => {
      setChannels({});
      setChannelTypes([]);
      setChannelSchemas({});
      void fetchChannels();
    };
    // Observe every store transition, even an ABA batched into one render.
    const unsubscribe = useAgentStore.subscribe((next, previous) => {
      if (next.selectedAgent !== previous.selectedAgent) changeScope();
    });
    changeScope();
    return () => {
      unsubscribe();
      generation.current += 1;
      controller.current?.abort();
    };
  }, [fetchChannels]);

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
      "matrix",
      "sip",
      "xiaoyi",
    ],
    [],
  );

  const orderedKeys = useMemo(() => {
    const keys = Array.from(
      new Set([
        ...channelTypes,
        ...Object.keys(channels),
        ...Object.keys(channelSchemas),
      ]),
    );
    return [
      ...builtinOrder.filter((k) => keys.includes(k)),
      ...keys.filter((k) => !builtinOrder.includes(k)),
    ];
  }, [builtinOrder, channelTypes, channels, channelSchemas]);

  // Read isBuiltin from API response
  const isBuiltin = useCallback(
    (key: string) => Boolean(channels[key]?.isBuiltin),
    [channels],
  );

  return {
    channels,
    channelTypes,
    channelSchemas,
    schemasLoading,
    orderedKeys,
    isBuiltin,
    loading,
    fetchChannels,
    setChannels,
  };
}
