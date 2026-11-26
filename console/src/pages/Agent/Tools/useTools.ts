import { useCallback, useEffect, useRef, useState } from "react";
import { useAppMessage } from "../../../hooks/useAppMessage";
import api from "../../../api";
import type { ToolInfo } from "../../../api/modules/tools";
import { useTranslation } from "react-i18next";
import { useAgentStore } from "../../../stores/agentStore";

type SwitchField = "enabled" | "async_execution";
type SwitchEdit = { name: string; field: SwitchField };

function currentAgentId() {
  return useAgentStore.getState().selectedAgent || "default";
}

export function useTools() {
  const { t } = useTranslation();
  const { selectedAgent } = useAgentStore();
  const [tools, setTools] = useState<ToolInfo[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<unknown>(null);
  const [refreshState, setRefreshState] = useState<
    "idle" | "failed" | "retrying"
  >("idle");
  const [loadedAgent, setLoadedAgent] = useState<string | null>(null);
  const [batchLoading, setBatchLoading] = useState(false);
  const { message } = useAppMessage();
  const requestGeneration = useRef(0);
  const loadedAgentRef = useRef<string | null>(null);
  const pendingSwitchEdits = useRef(new Set<SwitchEdit>());
  const refreshSwitchEdits = useRef<Set<SwitchEdit> | null>(null);

  const trackSwitchEdit = useCallback((name: string, field: SwitchField) => {
    const edit = { name, field };
    const pending = pendingSwitchEdits.current;
    pending.add(edit);
    refreshSwitchEdits.current?.add(edit);
    return () => {
      pending.delete(edit);
    };
  }, []);

  const ownsCurrentAgent = useCallback(
    (agentId: string | null) =>
      agentId !== null &&
      loadedAgentRef.current === agentId &&
      currentAgentId() === agentId,
    [],
  );

  const loadToolsForAgent = useCallback(
    async (requestedAgent: string, background: boolean) => {
      if (currentAgentId() !== requestedAgent) return;
      if (background && !ownsCurrentAgent(requestedAgent)) return;
      const generation = ++requestGeneration.current;
      const isCurrentRequest = () =>
        generation === requestGeneration.current &&
        currentAgentId() === requestedAgent;
      // Include edits already in flight and any that start during this read.
      const overlappingEdits = background
        ? new Set(pendingSwitchEdits.current)
        : null;
      refreshSwitchEdits.current = overlappingEdits;

      if (background) {
        setRefreshState((state) => (state === "failed" ? "retrying" : state));
      } else {
        loadedAgentRef.current = null;
        setLoadedAgent(null);
        setLoading(true);
        setBatchLoading(false);
        setError(null);
        setRefreshState("idle");
      }
      try {
        const data = await api.listTools(requestedAgent);
        if (!isCurrentRequest()) return;
        if (overlappingEdits?.size) {
          const protectedFields = {
            enabled: new Set<string>(),
            async_execution: new Set<string>(),
          };
          for (const { name, field } of overlappingEdits) {
            protectedFields[field].add(name);
          }
          setTools((previous) => {
            const current = new Map(previous.map((tool) => [tool.name, tool]));
            return data.map((tool) => {
              const local = current.get(tool.name);
              return local
                ? {
                    ...tool,
                    enabled: protectedFields.enabled.has(tool.name)
                      ? local.enabled
                      : tool.enabled,
                    async_execution: protectedFields.async_execution.has(
                      tool.name,
                    )
                      ? local.async_execution
                      : tool.async_execution,
                  }
                : tool;
            });
          });
        } else {
          setTools(data);
        }
        if (background) {
          setRefreshState("idle");
        } else {
          loadedAgentRef.current = requestedAgent;
          setLoadedAgent(requestedAgent);
        }
      } catch (error) {
        if (!isCurrentRequest()) return;
        console.error("Failed to load tools:", error);
        if (background) {
          setRefreshState("failed");
        } else {
          loadedAgentRef.current = null;
          setLoadedAgent(null);
          setError(
            error instanceof Error ? error : new Error("Failed to load tools"),
          );
          message.error(t("tools.loadError"));
        }
      } finally {
        if (refreshSwitchEdits.current === overlappingEdits) {
          refreshSwitchEdits.current = null;
        }
        if (!background && isCurrentRequest()) setLoading(false);
      }
    },
    [message, ownsCurrentAgent, t],
  );

  const loadTools = useCallback(
    ({ background = false }: { background?: boolean } = {}) =>
      loadToolsForAgent(selectedAgent || "default", background),
    [loadToolsForAgent, selectedAgent],
  );

  useEffect(() => {
    const pending = pendingSwitchEdits.current;
    loadTools();
    return () => {
      requestGeneration.current += 1;
      loadedAgentRef.current = null;
      pending.clear();
      refreshSwitchEdits.current = null;
    };
  }, [loadTools]);

  const toggleEnabled = useCallback(
    async (tool: ToolInfo) => {
      const owner = loadedAgentRef.current;
      if (!ownsCurrentAgent(owner)) return;
      const finish = trackSwitchEdit(tool.name, "enabled");
      // Optimistic update
      setTools((prev) =>
        prev.map((t) =>
          t.name === tool.name ? { ...t, enabled: !t.enabled } : t,
        ),
      );

      try {
        const result = await api.toggleTool(tool.name);
        if (!ownsCurrentAgent(owner)) return;
        message.success(
          tool.enabled ? t("tools.disableSuccess") : t("tools.enableSuccess"),
        );
        setTools((prev) =>
          prev.map((t) =>
            t.name === result.name ? { ...t, enabled: result.enabled } : t,
          ),
        );
      } catch {
        if (!ownsCurrentAgent(owner)) return;
        // Revert optimistic update on error
        setTools((prev) =>
          prev.map((t) =>
            t.name === tool.name ? { ...t, enabled: tool.enabled } : t,
          ),
        );
        message.error(t("tools.toggleError"));
      } finally {
        finish();
      }
    },
    [message, ownsCurrentAgent, t, trackSwitchEdit],
  );

  const toggleAsyncExecution = useCallback(
    async (tool: ToolInfo) => {
      const owner = loadedAgentRef.current;
      if (!ownsCurrentAgent(owner)) return;
      const finish = trackSwitchEdit(tool.name, "async_execution");
      // Optimistic update
      setTools((prev) =>
        prev.map((t) =>
          t.name === tool.name
            ? { ...t, async_execution: !t.async_execution }
            : t,
        ),
      );

      try {
        const result = await api.updateAsyncExecution(
          tool.name,
          !tool.async_execution,
        );
        if (!ownsCurrentAgent(owner)) return;
        message.success(
          result.async_execution
            ? t("tools.asyncExecutionEnabled")
            : t("tools.asyncExecutionDisabled"),
        );
        setTools((prev) =>
          prev.map((t) =>
            t.name === result.name
              ? { ...t, async_execution: result.async_execution }
              : t,
          ),
        );
      } catch {
        if (!ownsCurrentAgent(owner)) return;
        // Revert optimistic update on error
        setTools((prev) =>
          prev.map((t) =>
            t.name === tool.name
              ? { ...t, async_execution: tool.async_execution }
              : t,
          ),
        );
        message.error(t("tools.toggleError"));
      } finally {
        finish();
      }
    },
    [message, ownsCurrentAgent, t, trackSwitchEdit],
  );

  const setAllEnabled = useCallback(
    async (enabled: boolean) => {
      const owner = loadedAgentRef.current;
      if (!ownsCurrentAgent(owner)) return;
      const targets = new Set(
        tools
          .filter((tool) => tool.enabled !== enabled)
          .map((tool) => tool.name),
      );
      if (targets.size === 0) {
        message.info(t(enabled ? "tools.allEnabled" : "tools.allDisabled"));
        return;
      }

      setTools((prev) =>
        prev.map((tool) =>
          targets.has(tool.name) ? { ...tool, enabled } : tool,
        ),
      );
      setBatchLoading(true);
      try {
        // Track each request separately and reload only after they all settle.
        const results = await Promise.allSettled(
          Array.from(targets, async (name) => {
            const finish = trackSwitchEdit(name, "enabled");
            try {
              const result = await api.toggleTool(name);
              if (!ownsCurrentAgent(owner)) return;
              setTools((prev) =>
                prev.map((tool) =>
                  tool.name === result.name
                    ? { ...tool, enabled: result.enabled }
                    : tool,
                ),
              );
            } finally {
              finish();
            }
          }),
        );
        if (!ownsCurrentAgent(owner)) return;
        if (results.some((result) => result.status === "rejected")) {
          message.error(t("tools.toggleError"));
          await loadTools();
          return;
        }
        message.success(
          t(enabled ? "tools.enableAllSuccess" : "tools.disableAllSuccess"),
        );
      } finally {
        if (ownsCurrentAgent(owner)) setBatchLoading(false);
      }
    },
    [loadTools, message, ownsCurrentAgent, t, tools, trackSwitchEdit],
  );

  const enableAll = useCallback(() => setAllEnabled(true), [setAllEnabled]);
  const disableAll = useCallback(() => setAllEnabled(false), [setAllEnabled]);

  const saveToolConfig = useCallback(
    async (
      toolName: string,
      config: Record<string, unknown>,
      agentId = selectedAgent || "default",
    ) => {
      try {
        await api.updateToolConfig(toolName, config, agentId);
      } catch (error) {
        console.error("Failed to save tool config:", error);
        message.error(t("tools.configSaveError"));
        throw error;
      }
    },
    [message, t, selectedAgent],
  );

  return {
    tools,
    loading,
    error,
    refreshState,
    ready: !loading && !error && loadedAgent === (selectedAgent || "default"),
    batchLoading,
    toggleEnabled,
    toggleAsyncExecution,
    enableAll,
    disableAll,
    loadTools,
    saveToolConfig,
  };
}
