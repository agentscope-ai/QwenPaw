import { useCallback, useLayoutEffect, useMemo, useRef, useState } from "react";
import api from "../../../api";
import type { ChannelSchema } from "../../../api/modules/channel";
import { useAgentStore } from "../../../stores/agentStore";

type Channels = Record<string, Record<string, unknown>>;
type ChannelsUpdater = Channels | ((current: Channels) => Channels);

export function useChannels() {
  const { selectedAgent } = useAgentStore();
  const agentId = selectedAgent || "default";
  const loadedAgentRef = useRef<string | null>(null);
  const generation = useRef(0);
  const controller = useRef<AbortController>();
  const [channels, setChannelsState] = useState<Channels>({});
  const [channelTypes, setChannelTypes] = useState<string[]>([]);
  const [channelSchemas, setChannelSchemas] = useState<
    Record<string, ChannelSchema>
  >({});
  const [loadedAgentId, setLoadedAgentId] = useState<string | null>(null);
  const [viewAgentId, setViewAgentId] = useState(agentId);
  const [schemasLoading, setSchemasLoading] = useState(true);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<Error | null>(null);

  const fetchChannels = useCallback(async (target?: boolean | string) => {
    const selected = useAgentStore.getState().selectedAgent || "default";
    const requestAgentId = typeof target === "string" ? target : selected;
    if (requestAgentId !== selected) return;
    const schemasOnly = target === true && loadedAgentRef.current === selected;
    const requestGeneration = ++generation.current;
    controller.current?.abort();
    const currentController = new AbortController();
    controller.current = currentController;
    const scope = { agentId: requestAgentId, signal: currentController.signal };
    const isCurrent = () =>
      generation.current === requestGeneration &&
      !currentController.signal.aborted &&
      (useAgentStore.getState().selectedAgent || "default") === requestAgentId;

    setViewAgentId(requestAgentId);
    setSchemasLoading(true);
    if (!schemasOnly) {
      loadedAgentRef.current = null;
      setLoadedAgentId(null);
      setLoading(true);
      setError(null);
    }
    // Schema availability must not delay core loading or its error recovery.
    const schemasRequest = (async () => {
      try {
        const schemas = await api.listChannelSchemas(scope);
        if (isCurrent()) setChannelSchemas(schemas ?? {});
      } catch {
        if (isCurrent()) setChannelSchemas({});
      } finally {
        if (isCurrent()) setSchemasLoading(false);
      }
    })();

    if (!schemasOnly) {
      try {
        const [data, types] = await Promise.all([
          api.listChannels(scope),
          api.listChannelTypes(scope),
        ]);
        if (!isCurrent()) return;
        setChannelsState((data ?? {}) as unknown as Channels);
        setChannelTypes(types ?? []);
        loadedAgentRef.current = requestAgentId;
        setLoadedAgentId(requestAgentId);
      } catch (reason) {
        if (!isCurrent()) return;
        console.error("Failed to load channels:", reason);
        setChannelsState({});
        setChannelTypes([]);
        setChannelSchemas({});
        setError(
          reason instanceof Error
            ? reason
            : new Error("Failed to load channels"),
        );
      } finally {
        if (isCurrent()) setLoading(false);
      }
    }
    await schemasRequest;
  }, []);

  useLayoutEffect(() => {
    const changeScope = () => {
      loadedAgentRef.current = null;
      setChannelsState({});
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
      loadedAgentRef.current = null;
      generation.current += 1;
      controller.current?.abort();
    };
  }, [fetchChannels]);

  const canMutate = useCallback(
    (ownerAgentId: string) =>
      (useAgentStore.getState().selectedAgent || "default") === ownerAgentId &&
      loadedAgentRef.current === ownerAgentId,
    [],
  );

  const setChannels = useCallback(
    (ownerAgentId: string, updater: ChannelsUpdater) => {
      if (!canMutate(ownerAgentId)) return false;
      const updateGeneration = generation.current;
      setChannelsState((current) => {
        if (generation.current !== updateGeneration || !canMutate(ownerAgentId))
          return current;
        return typeof updater === "function" ? updater(current) : updater;
      });
      return true;
    },
    [canMutate],
  );

  const currentAgentLoaded = loadedAgentId === agentId;
  const currentChannels = useMemo(
    () => (currentAgentLoaded ? channels : {}),
    [channels, currentAgentLoaded],
  );
  const currentChannelTypes = useMemo(
    () => (currentAgentLoaded ? channelTypes : []),
    [channelTypes, currentAgentLoaded],
  );
  const currentChannelSchemas = useMemo(
    () => (currentAgentLoaded ? channelSchemas : {}),
    [channelSchemas, currentAgentLoaded],
  );

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
        ...currentChannelTypes,
        ...Object.keys(currentChannels),
        ...Object.keys(currentChannelSchemas),
      ]),
    );
    return [
      ...builtinOrder.filter((key) => keys.includes(key)),
      ...keys.filter((key) => !builtinOrder.includes(key)),
    ];
  }, [
    builtinOrder,
    currentChannelTypes,
    currentChannels,
    currentChannelSchemas,
  ]);

  const isBuiltin = useCallback(
    (key: string) => Boolean(currentChannels[key]?.isBuiltin),
    [currentChannels],
  );

  return {
    agentId,
    channels: currentChannels,
    channelTypes: currentChannelTypes,
    channelSchemas: currentChannelSchemas,
    schemasLoading: viewAgentId === agentId ? schemasLoading : true,
    orderedKeys,
    isBuiltin,
    loading: viewAgentId === agentId ? loading : true,
    error: viewAgentId === agentId ? error : null,
    ready: currentAgentLoaded && !loading && error === null,
    canMutate,
    fetchChannels,
    setChannels,
  };
}
