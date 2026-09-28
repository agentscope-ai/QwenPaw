import { useEffect, useState } from "react";
import { request } from "../../api/request";

interface TerminalCapability {
  enabled: boolean;
  reason: string;
  confirmed: boolean;
}

const UNKNOWN_CAPABILITY: TerminalCapability = {
  enabled: false,
  reason: "unavailable",
  confirmed: false,
};

export function useTerminalEnabled(agentId: string) {
  const [states, setStates] = useState<Record<string, TerminalCapability>>({});
  useEffect(() => {
    const controller = new AbortController();
    const refresh = async () => {
      try {
        const status = await request<{ enabled: boolean; reason?: string }>(
          "/terminals/status",
          {
            headers: { "X-Agent-Id": agentId },
            signal: controller.signal,
          },
        );
        if (!controller.signal.aborted) {
          setStates((current) => ({
            ...current,
            [agentId]: {
              enabled: status.enabled === true,
              reason: status.reason ?? "",
              confirmed: true,
            },
          }));
        }
      } catch {
        // Keep the last confirmed state during transient request failures.
      }
    };
    void refresh();
    window.addEventListener("focus", refresh);
    return () => {
      controller.abort();
      window.removeEventListener("focus", refresh);
    };
  }, [agentId]);
  return states[agentId] ?? UNKNOWN_CAPABILITY;
}
