import { useCallback, useEffect, useState } from "react";
import { useAppMessage } from "../../../hooks/useAppMessage";
import api from "../../../api";
import type { ToolInfo } from "../../../api/modules/tools";
import { useTranslation } from "react-i18next";
import { useAgentStore } from "../../../stores/agentStore";

export function useTools() {
  const { t, i18n } = useTranslation();
  const { selectedAgent } = useAgentStore();
  const [tools, setTools] = useState<ToolInfo[]>([]);
  const [loading, setLoading] = useState(false);
  const [batchLoading, setBatchLoading] = useState(false);
  const { message } = useAppMessage();
  const lang = i18n.resolvedLanguage || i18n.language || "en";

  const loadTools = useCallback(async () => {
    setLoading(true);
    try {
      const data = await api.listTools(lang);
      setTools(data);
    } catch (error) {
      console.error("Failed to load tools:", error);
      message.error(t("tools.loadError"));
    } finally {
      setLoading(false);
    }
  }, [t, lang, message]);

  useEffect(() => {
    loadTools();
  }, [loadTools, selectedAgent]);

  const toggleEnabled = useCallback(
    async (tool: ToolInfo) => {
      // Optimistic update
      setTools((prev) =>
        prev.map((item) =>
          item.name === tool.name ? { ...item, enabled: !item.enabled } : item,
        ),
      );

      try {
        const result = await api.toggleTool(tool.name, lang);
        message.success(
          tool.enabled ? t("tools.disableSuccess") : t("tools.enableSuccess"),
        );
        // Merge rather than replace to preserve any local state not returned
        // by the server (e.g. UI-only fields added in future expansions).
        setTools((prev) =>
          prev.map((item) =>
            item.name === result.name ? { ...item, ...result } : item,
          ),
        );
      } catch (error) {
        // Revert optimistic update on error
        setTools((prev) =>
          prev.map((item) =>
            item.name === tool.name ? { ...item, enabled: tool.enabled } : item,
          ),
        );
        message.error(t("tools.toggleError"));
      }
    },
    [t, lang, message],
  );

  const toggleAsyncExecution = useCallback(
    async (tool: ToolInfo) => {
      // Optimistic update
      setTools((prev) =>
        prev.map((item) =>
          item.name === tool.name
            ? { ...item, async_execution: !item.async_execution }
            : item,
        ),
      );

      try {
        const result = await api.updateAsyncExecution(
          tool.name,
          !tool.async_execution,
          lang,
        );
        message.success(
          result.async_execution
            ? t("tools.asyncExecutionEnabled")
            : t("tools.asyncExecutionDisabled"),
        );
        // Merge server response to preserve static metadata.
        setTools((prev) =>
          prev.map((item) =>
            item.name === result.name ? { ...item, ...result } : item,
          ),
        );
      } catch (error) {
        // Revert optimistic update on error
        setTools((prev) =>
          prev.map((item) =>
            item.name === tool.name
              ? { ...item, async_execution: tool.async_execution }
              : item,
          ),
        );
        message.error(t("tools.toggleError"));
      }
    },
    [t, lang, message],
  );

  const enableAll = useCallback(async () => {
    const disabledTools = tools.filter((tool) => !tool.enabled);
    if (disabledTools.length === 0) {
      message.info(t("tools.allEnabled"));
      return;
    }

    // Optimistic update - preserve async_execution state
    setTools((prev) => prev.map((item) => ({ ...item, enabled: true })));

    setBatchLoading(true);
    try {
      const results = await Promise.all(
        disabledTools.map((tool) => api.toggleTool(tool.name, lang)),
      );
      message.success(t("tools.enableAllSuccess"));
      // Merge server responses, preserving all static metadata.
      setTools((prev) =>
        prev.map((item) => {
          const result = results.find((r) => r.name === item.name);
          return result ? { ...item, ...result } : item;
        }),
      );
    } catch (error) {
      message.error(t("tools.toggleError"));
      // Reload on error to sync with server
      await loadTools();
    } finally {
      setBatchLoading(false);
    }
  }, [tools, t, loadTools, lang, message]);

  const disableAll = useCallback(async () => {
    const enabledTools = tools.filter((tool) => tool.enabled);
    if (enabledTools.length === 0) {
      message.info(t("tools.allDisabled"));
      return;
    }

    // Optimistic update - preserve async_execution state
    setTools((prev) => prev.map((item) => ({ ...item, enabled: false })));

    setBatchLoading(true);
    try {
      const results = await Promise.all(
        enabledTools.map((tool) => api.toggleTool(tool.name, lang)),
      );
      message.success(t("tools.disableAllSuccess"));
      // Merge server responses, preserving all static metadata.
      setTools((prev) =>
        prev.map((item) => {
          const result = results.find((r) => r.name === item.name);
          return result ? { ...item, ...result } : item;
        }),
      );
    } catch (error) {
      message.error(t("tools.toggleError"));
      // Reload on error to sync with server
      await loadTools();
    } finally {
      setBatchLoading(false);
    }
  }, [tools, t, loadTools, lang, message]);

  const saveToolConfig = useCallback(
    async (toolName: string, config: Record<string, any>) => {
      try {
        await api.updateToolConfig(toolName, config);
        message.success(t("tools.configSaved"));
      } catch (error) {
        console.error("Failed to save tool config:", error);
        message.error(t("tools.configSaveError"));
        throw error;
      }
    },
    [t, message],
  );

  return {
    tools,
    loading,
    batchLoading,
    toggleEnabled,
    toggleAsyncExecution,
    enableAll,
    disableAll,
    loadTools,
    saveToolConfig,
  };
}
