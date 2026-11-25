import { useCallback, useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { request } from "../../../api/request";
import { useAgentStore } from "../../../stores/agentStore";
import {
  ensureFrontendPlugin,
  reloadFrontendPlugin,
} from "../../../plugins/usePluginLoader";
import { useAppMessage } from "../../../hooks/useAppMessage";
import { installPlugin } from "../../../api/modules/plugin";
import { subscribeToPluginChanges } from "../../../utils/pluginChangeEvents";
import { runPluginInstall } from "../../Settings/PluginManager/dependencyUpgrade";

export interface MCPPluginState {
  id: "qwenpaw-mcp";
  installed: boolean;
  enabled: boolean;
  available?: boolean;
  status: "not_installed" | "disabled" | "active" | "inactive" | "failed";
  diagnostics: string[];
  legacy_mcp_archived?: boolean;
  version?: string | null;
  update?: {
    installed_version: string;
    version: string;
    source: string;
  } | null;
  update_diagnostics?: string[];
  upgrade?: { status: string; diagnostics: string[] };
  workspace?: {
    id: string;
    status: "unused" | "configured" | "needs_review";
    eligible: boolean;
    diagnostics: string[];
  };
}

export function useMCPPlugin(mounted: boolean) {
  const { t } = useTranslation();
  const { message } = useAppMessage();
  const { selectedAgent } = useAgentStore();
  const [state, setState] = useState<MCPPluginState | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [loadError, setLoadError] = useState("");
  const [revision, setRevision] = useState(0);
  const operation = useRef(false);
  const alive = useRef(true);
  const agent = useRef(selectedAgent);
  agent.current = selectedAgent;
  const refresh = useCallback(() => setRevision((value) => value + 1), []);

  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
    };
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    setState(null);
    setLoadError("");
    request<MCPPluginState>("/mcp-plugin", { signal: controller.signal })
      .then(async (value) => {
        if (controller.signal.aborted) return;
        setState(value);
        if (value.status === "active" && !mounted) {
          await ensureFrontendPlugin("qwenpaw-mcp");
        }
      })
      .catch((failure: unknown) => {
        if (!controller.signal.aborted) setLoadError(String(failure));
      });
    return () => controller.abort();
  }, [selectedAgent, revision, mounted]);

  useEffect(() => setError(""), [selectedAgent]);

  useEffect(() => {
    window.addEventListener("qwenpaw:mcp-plugin-changed", refresh);
    const unsubscribe = subscribeToPluginChanges(refresh);
    return () => {
      window.removeEventListener("qwenpaw:mcp-plugin-changed", refresh);
      unsubscribe();
    };
  }, [refresh]);

  const mutate = async (action: () => Promise<void>) => {
    if (operation.current || !alive.current) return;
    operation.current = true;
    const owner = selectedAgent;
    setBusy(true);
    setError("");
    try {
      await action();
    } catch (failure) {
      if (alive.current && agent.current === owner) setError(String(failure));
    } finally {
      operation.current = false;
      if (alive.current) setBusy(false);
    }
  };

  const activate = () =>
    mutate(async () => {
      if (
        !state?.installed ||
        state.status === "failed" ||
        state.diagnostics.length > 0 ||
        (state.workspace?.diagnostics.length ?? 0) > 0
      ) {
        await request("/mcp-plugin/install", { method: "POST" });
      } else {
        await request("/plugins/qwenpaw-mcp/enabled", {
          method: "POST",
          body: JSON.stringify({ enabled: true }),
        });
      }
      if (alive.current) refresh();
    });

  const update = () =>
    mutate(async () => {
      if (state?.update?.source !== "bundled:qwenpaw-mcp") return;
      const result = await runPluginInstall(
        () => installPlugin(state.update!.source, { force: true }),
        t,
      );
      if (result === null || !alive.current) return;
      refresh();
      if (result.loaded && result.enabled !== false) {
        try {
          await reloadFrontendPlugin("qwenpaw-mcp");
        } catch {
          const detail = t("mcp.plugin.frontendRefreshFailed");
          message.error(detail);
          throw new Error(detail);
        }
      }
    });

  return { state, busy, error: error || loadError, activate, update, refresh };
}
