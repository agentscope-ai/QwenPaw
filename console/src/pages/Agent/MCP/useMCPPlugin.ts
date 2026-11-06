import { useCallback, useEffect, useState } from "react";
import { request } from "../../../api/request";
import { useAgentStore } from "../../../stores/agentStore";
import { reloadFrontendPlugin } from "../../../plugins/usePluginLoader";

export interface MCPPluginState {
  id: "qwenpaw-mcp";
  installed: boolean;
  enabled: boolean;
  status: "not_installed" | "disabled" | "active" | "inactive" | "failed";
  diagnostics: string[];
  upgrade?: { status: string; diagnostics: string[] };
  workspace?: {
    id: string;
    status: "unused" | "configured" | "needs_review";
    eligible: boolean;
    diagnostics: string[];
  };
}

export function useMCPPlugin(mounted: boolean) {
  const { selectedAgent } = useAgentStore();
  const [state, setState] = useState<MCPPluginState | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [revision, setRevision] = useState(0);
  const refresh = useCallback(() => setRevision((value) => value + 1), []);

  useEffect(() => {
    const controller = new AbortController();
    setState(null);
    setError("");
    request<MCPPluginState>("/mcp-plugin", { signal: controller.signal })
      .then(async (value) => {
        if (controller.signal.aborted) return;
        setState(value);
        if (value.status === "active" && !mounted) {
          await reloadFrontendPlugin("qwenpaw-mcp");
        }
      })
      .catch((failure: unknown) => {
        if (!controller.signal.aborted) setError(String(failure));
      });
    return () => controller.abort();
  }, [selectedAgent, revision, mounted]);

  useEffect(() => {
    window.addEventListener("qwenpaw:mcp-plugin-changed", refresh);
    return () =>
      window.removeEventListener("qwenpaw:mcp-plugin-changed", refresh);
  }, [refresh]);

  const activate = async () => {
    setBusy(true);
    setError("");
    try {
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
      refresh();
    } catch (failure) {
      setError(String(failure));
    } finally {
      setBusy(false);
    }
  };

  return { state, busy, error, activate, refresh };
}
