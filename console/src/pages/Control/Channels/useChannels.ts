import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import api from "../../../api";
import type { ChannelSchema } from "../../../api/modules/channel";
import { useAgentStore } from "../../../stores/agentStore";

type Channels = Record<string, Record<string, unknown>>;
type ChannelsUpdater = Channels | ((current: Channels) => Channels);

export function useChannels() {
  const { selectedAgent } = useAgentStore();
  const selectedAgentRef = useRef(selectedAgent);
  const loadedAgentRef = useRef<string | null>(null);
  const requestIdRef = useRef(0);
  const [channels, setChannelsState] = useState<Channels>({});
  const [channelTypes, setChannelTypes] = useState<string[]>([]);
  const [channelSchemas, setChannelSchemas] = useState<
    Record<string, ChannelSchema>
  >({});
  const [loadedAgentId, setLoadedAgentId] = useState<string | null>(null);
  const [viewAgentId, setViewAgentId] = useState(selectedAgent);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<Error | null>(null);

  selectedAgentRef.current = selectedAgent;

  const fetchChannels = useCallback(async (agentId?: string) => {
    const requestAgentId = agentId ?? selectedAgentRef.current;
    const requestId = ++requestIdRef.current;
    const isCurrent = () =>
      requestIdRef.current === requestId &&
      selectedAgentRef.current === requestAgentId;

    if (!isCurrent()) return;
    loadedAgentRef.current = null;
    setViewAgentId(requestAgentId);
    setLoadedAgentId(null);
    setLoading(true);
    setError(null);
    const schemasRequest = api
      .listChannelSchemas(requestAgentId)
      .catch(() => undefined);

    try {
      const [data, types] = await Promise.all([
        api.listChannels(requestAgentId),
        api.listChannelTypes(requestAgentId),
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
        reason instanceof Error ? reason : new Error("Failed to load channels"),
      );
    } finally {
      if (isCurrent()) setLoading(false);
    }

    const schemas = await schemasRequest;
    if (isCurrent() && schemas) setChannelSchemas(schemas);
  }, []);

  useEffect(() => {
    void fetchChannels(selectedAgent);
  }, [fetchChannels, selectedAgent]);

  const canMutate = useCallback(
    (ownerAgentId: string) =>
      selectedAgentRef.current === ownerAgentId &&
      loadedAgentRef.current === ownerAgentId,
    [],
  );

  const setChannels = useCallback(
    (ownerAgentId: string, updater: ChannelsUpdater) => {
      if (!canMutate(ownerAgentId)) return false;
      setChannelsState(updater);
      return true;
    },
    [canMutate],
  );

  const currentAgentLoaded = loadedAgentId === selectedAgent;
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

  const orderedKeys = useMemo(
    () => [
      ...builtinOrder.filter((key) => currentChannelTypes.includes(key)),
      ...currentChannelTypes.filter((key) => !builtinOrder.includes(key)),
    ],
    [builtinOrder, currentChannelTypes],
  );

  const isBuiltin = useCallback(
    (key: string) => Boolean(currentChannels[key]?.isBuiltin),
    [currentChannels],
  );

  return {
    agentId: selectedAgent,
    channels: currentChannels,
    channelTypes: currentChannelTypes,
    channelSchemas: currentChannelSchemas,
    orderedKeys,
    isBuiltin,
    loading: viewAgentId === selectedAgent ? loading : true,
    error: viewAgentId === selectedAgent ? error : null,
    ready: currentAgentLoaded && !loading && error === null,
    canMutate,
    fetchChannels,
    setChannels,
  };
}
