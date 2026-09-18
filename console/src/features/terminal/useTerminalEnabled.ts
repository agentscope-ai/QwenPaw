import { useEffect, useState } from "react";
import { request } from "../../api/request";

export function useTerminalEnabled(agentId: string) {
  const [state, setState] = useState({ agentId: "", enabled: false });
  useEffect(() => {
    const controller = new AbortController();
    const refresh = async () => {
      try {
        const status = await request<{ enabled: boolean }>(
          "/terminals/status",
          {
            headers: { "X-Agent-Id": agentId },
            signal: controller.signal,
          },
        );
        if (!controller.signal.aborted)
          setState({ agentId, enabled: status.enabled === true });
      } catch {
        if (!controller.signal.aborted) setState({ agentId, enabled: false });
      }
    };
    void refresh();
    window.addEventListener("focus", refresh);
    return () => {
      controller.abort();
      window.removeEventListener("focus", refresh);
    };
  }, [agentId]);
  return state.agentId === agentId && state.enabled;
}
