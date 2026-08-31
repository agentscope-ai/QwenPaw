import { useCallback, useEffect, useState } from "react";
import type { ChatGroup } from "../api/types/chat";
import { chatApi } from "../api/modules/chat";
import { useAgentStore } from "../stores/agentStore";

export interface ChatGroupsState {
  groups: ChatGroup[];
  loading: boolean;
  refreshGroups: () => Promise<void>;
  createGroup: (name: string) => Promise<void>;
  renameGroup: (groupId: string, name: string) => Promise<void>;
  pinGroup: (groupId: string, pinned: boolean) => Promise<void>;
  deleteGroup: (groupId: string) => Promise<void>;
  reorderGroups: (groupIds: string[]) => Promise<void>;
}

export function useChatGroups(active = true): ChatGroupsState {
  const selectedAgent = useAgentStore((state) => state.selectedAgent);
  const [groups, setGroups] = useState<ChatGroup[]>([]);
  const [loading, setLoading] = useState(true);

  const refreshGroups = useCallback(async () => {
    const next = await chatApi.listGroups();
    setGroups(next);
  }, []);

  useEffect(() => {
    if (!active) return;
    let cancelled = false;
    setLoading(true);
    chatApi
      .listGroups()
      .then((next) => {
        if (!cancelled) setGroups(next);
      })
      .catch((error: unknown) => {
        console.error("Failed to load chat groups:", error);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [active, selectedAgent]);

  const createGroup = useCallback(
    async (name: string) => {
      await chatApi.createGroup(name);
      await refreshGroups();
    },
    [refreshGroups],
  );

  const renameGroup = useCallback(
    async (groupId: string, name: string) => {
      await chatApi.updateGroup(groupId, { name });
      await refreshGroups();
    },
    [refreshGroups],
  );

  const pinGroup = useCallback(
    async (groupId: string, pinned: boolean) => {
      await chatApi.updateGroup(groupId, { pinned });
      await refreshGroups();
    },
    [refreshGroups],
  );

  const deleteGroup = useCallback(
    async (groupId: string) => {
      await chatApi.deleteGroup(groupId);
      await refreshGroups();
    },
    [refreshGroups],
  );

  const reorderGroups = useCallback(async (groupIds: string[]) => {
    const next = await chatApi.reorderGroups(groupIds);
    setGroups(next);
  }, []);

  return {
    groups,
    loading,
    refreshGroups,
    createGroup,
    renameGroup,
    pinGroup,
    deleteGroup,
    reorderGroups,
  };
}
