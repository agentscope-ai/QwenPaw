import { useCallback, useEffect, useState } from "react";
import { message } from "@agentscope-ai/design";
import api from "../../../api";
import type { ToolInfo } from "../../../api/modules/tools";
import { useTranslation } from "react-i18next";
import { useAgentStore } from "../../../stores/agentStore";

export function useTools() {
  const { t } = useTranslation();
  const { selectedAgent } = useAgentStore();
  const [tools, setTools] = useState<ToolInfo[]>([]);
  const [loading, setLoading] = useState(false);
  const [batchLoading, setBatchLoading] = useState(false);

  const loadTools = useCallback(async () => {
    setLoading(true);
    try {
      const data = await api.listTools();
      setTools(data);
    } catch (error) {
      console.error("Failed to load tools:", error);
      message.error(t("tools.loadError"));
    } finally {
      setLoading(false);
    }
  }, [t]);

  useEffect(() => {
    loadTools();
  }, [loadTools, selectedAgent]);

  const toggleEnabled = useCallback(
    async (tool: ToolInfo) => {
      // Optimistic update
      setTools((prev) =>
        prev.map((t) =>
          t.name === tool.name ? { ...t, enabled: !t.enabled } : t,
        ),
      );

      try {
        const result = await api.toggleTool(tool.name);
        message.success(
          tool.enabled ? t("tools.disableSuccess") : t("tools.enableSuccess"),
        );
        // Update with server response (no full reload)
        setTools((prev) =>
          prev.map((t) => (t.name === result.name ? result : t)),
        );
      } catch (error) {
        // Revert optimistic update on error
        setTools((prev) =>
          prev.map((t) =>
            t.name === tool.name ? { ...t, enabled: tool.enabled } : t,
          ),
        );
        message.error(t("tools.toggleError"));
      }
    },
    [t],
  );

  const toggleAsyncExecution = useCallback(
    async (tool: ToolInfo) => {
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
        message.success(
          result.async_execution
            ? t("tools.asyncExecutionEnabled")
            : t("tools.asyncExecutionDisabled"),
        );
        // Update with server response
        setTools((prev) =>
          prev.map((t) => (t.name === result.name ? result : t)),
        );
      } catch (error) {
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
    [t],
  );

  const enableAll = useCallback(async () => {
    const disabledTools = tools.filter((tool) => !tool.enabled);
    if (disabledTools.length === 0) {
      message.info(t("tools.allEnabled"));
      return;
    }

    // Optimistic update
    setTools((prev) => prev.map((t) => ({ ...t, enabled: true })));

    setBatchLoading(true);
    try {
      const results = await Promise.all(
        disabledTools.map((tool) => api.toggleTool(tool.name)),
      );
      message.success(t("tools.enableAllSuccess"));
      // Update with server responses
      setTools((prev) =>
        prev.map((t) => {
          const result = results.find((r) => r.name === t.name);
          return result || t;
        }),
      );
    } catch (error) {
      message.error(t("tools.toggleError"));
      // Reload on error to sync with server
      await loadTools();
    } finally {
      setBatchLoading(false);
    }
  }, [tools, t, loadTools]);

  const disableAll = useCallback(async () => {
    const enabledTools = tools.filter((tool) => tool.enabled);
    if (enabledTools.length === 0) {
      message.info(t("tools.allDisabled"));
      return;
    }

    // Optimistic update
    setTools((prev) => prev.map((t) => ({ ...t, enabled: false })));

    setBatchLoading(true);
    try {
      const results = await Promise.all(
        enabledTools.map((tool) => api.toggleTool(tool.name)),
      );
      message.success(t("tools.disableAllSuccess"));
      // Update with server responses
      setTools((prev) =>
        prev.map((t) => {
          const result = results.find((r) => r.name === t.name);
          return result || t;
        }),
      );
    } catch (error) {
      message.error(t("tools.toggleError"));
      // Reload on error to sync with server
      await loadTools();
    } finally {
      setBatchLoading(false);
    }
  }, [tools, t, loadTools]);

  return {
    tools,
    loading,
    batchLoading,
    toggleEnabled,
    toggleAsyncExecution,
    enableAll,
    disableAll,
  };
}
