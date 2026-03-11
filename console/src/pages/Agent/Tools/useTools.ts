import { useCallback, useEffect, useState } from "react";
import { message } from "@agentscope-ai/design";
import api from "../../../api";
import type { ToolInfo } from "../../../api/modules/tools";
import { useTranslation } from "react-i18next";

export function useTools() {
  const { t } = useTranslation();
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
  }, [loadTools]);

  const toggleEnabled = useCallback(
    async (tool: ToolInfo) => {
      try {
        await api.toggleTool(tool.name);
        message.success(
          tool.enabled ? t("tools.disableSuccess") : t("tools.enableSuccess"),
        );
        await loadTools();
      } catch {
        message.error(t("tools.toggleError"));
      }
    },
    [t, loadTools],
  );

  const enableAll = useCallback(async () => {
    const disabledTools = tools.filter((tool) => !tool.enabled);
    if (disabledTools.length === 0) {
      message.info(t("tools.allEnabled"));
      return;
    }

    setBatchLoading(true);
    try {
      await Promise.all(disabledTools.map((tool) => api.toggleTool(tool.name)));
      message.success(t("tools.enableAllSuccess"));
      await loadTools();
    } catch {
      message.error(t("tools.toggleError"));
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

    setBatchLoading(true);
    try {
      await Promise.all(enabledTools.map((tool) => api.toggleTool(tool.name)));
      message.success(t("tools.disableAllSuccess"));
      await loadTools();
    } catch {
      message.error(t("tools.toggleError"));
    } finally {
      setBatchLoading(false);
    }
  }, [tools, t, loadTools]);

  return {
    tools,
    loading,
    batchLoading,
    toggleEnabled,
    enableAll,
    disableAll,
  };
}
