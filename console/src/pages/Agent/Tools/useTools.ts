import { useCallback, useEffect, useRef, useState } from "react";
import { useAppMessage } from "../../../hooks/useAppMessage";
import api from "../../../api";
import type { ToolInfo } from "../../../api/modules/tools";
import { useTranslation } from "react-i18next";
import { useAgentStore } from "../../../stores/agentStore";

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
        if (background) {
          // Config refreshes must not overwrite concurrent switch changes.
          setTools((previous) => {
            const current = new Map(previous.map((tool) => [tool.name, tool]));
            return data.map((tool) => {
              const local = current.get(tool.name);
              return local
                ? {
                    ...tool,
                    enabled: local.enabled,
                    async_execution: local.async_execution,
                  }
                : tool;
            });
          });
          setRefreshState("idle");
        } else {
          setTools(data);
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
    loadTools();
    return () => {
      requestGeneration.current += 1;
      loadedAgentRef.current = null;
    };
  }, [loadTools]);

  const toggleEnabled = useCallback(
    async (tool: ToolInfo) => {
      const owner = loadedAgentRef.current;
      if (!ownsCurrentAgent(owner)) return;
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
      }
    },
    [message, ownsCurrentAgent, t],
  );

  const toggleAsyncExecution = useCallback(
    async (tool: ToolInfo) => {
      const owner = loadedAgentRef.current;
      if (!ownsCurrentAgent(owner)) return;
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
      }
    },
    [message, ownsCurrentAgent, t],
  );

  const enableAll = useCallback(async () => {
    const owner = loadedAgentRef.current;
    if (!ownsCurrentAgent(owner)) return;
    const disabledTools = tools.filter((tool) => !tool.enabled);
    if (disabledTools.length === 0) {
      message.info(t("tools.allEnabled"));
      return;
    }

    // Optimistic update - preserve async_execution state
    setTools((prev) => prev.map((t) => ({ ...t, enabled: true })));

    setBatchLoading(true);
    try {
      const results = await Promise.all(
        disabledTools.map((tool) => api.toggleTool(tool.name)),
      );
      if (!ownsCurrentAgent(owner)) return;
      message.success(t("tools.enableAllSuccess"));
      setTools((prev) =>
        prev.map((t) => {
          const result = results.find((r) => r.name === t.name);
          return result ? { ...t, enabled: result.enabled } : t;
        }),
      );
    } catch {
      if (!ownsCurrentAgent(owner)) return;
      message.error(t("tools.toggleError"));
      // Reload on error to sync with server
      await loadTools();
    } finally {
      if (ownsCurrentAgent(owner)) setBatchLoading(false);
    }
  }, [loadTools, message, ownsCurrentAgent, t, tools]);

  const disableAll = useCallback(async () => {
    const owner = loadedAgentRef.current;
    if (!ownsCurrentAgent(owner)) return;
    const enabledTools = tools.filter((tool) => tool.enabled);
    if (enabledTools.length === 0) {
      message.info(t("tools.allDisabled"));
      return;
    }

    // Optimistic update - preserve async_execution state
    setTools((prev) => prev.map((t) => ({ ...t, enabled: false })));

    setBatchLoading(true);
    try {
      const results = await Promise.all(
        enabledTools.map((tool) => api.toggleTool(tool.name)),
      );
      if (!ownsCurrentAgent(owner)) return;
      message.success(t("tools.disableAllSuccess"));
      setTools((prev) =>
        prev.map((t) => {
          const result = results.find((r) => r.name === t.name);
          return result ? { ...t, enabled: result.enabled } : t;
        }),
      );
    } catch {
      if (!ownsCurrentAgent(owner)) return;
      message.error(t("tools.toggleError"));
      // Reload on error to sync with server
      await loadTools();
    } finally {
      if (ownsCurrentAgent(owner)) setBatchLoading(false);
    }
  }, [loadTools, message, ownsCurrentAgent, t, tools]);

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
