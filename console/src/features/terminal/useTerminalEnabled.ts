import { useEffect, useState } from "react";
import { request } from "../../api/request";
import { useAuthStatus } from "../../contexts/AuthStatusContext";

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

const AUTH_DISABLED_CAPABILITY: TerminalCapability = {
  enabled: false,
  reason: "",
  confirmed: true,
};

export function useTerminalEnabled() {
  const { enabled: authEnabled } = useAuthStatus();
  const [capability, setCapability] = useState(UNKNOWN_CAPABILITY);
  useEffect(() => {
    if (!authEnabled) return;

    const controller = new AbortController();
    let confirmed = false;
    let requesting = false;
    const refresh = async () => {
      if (confirmed || requesting) return;
      requesting = true;
      try {
        const status = await request<{ enabled: boolean; reason?: string }>(
          "/terminals/status",
          { signal: controller.signal },
        );
        if (!controller.signal.aborted) {
          confirmed = true;
          setCapability({
            enabled: status.enabled === true,
            reason: status.reason ?? "",
            confirmed: true,
          });
        }
      } catch {
        // Retry an unconfirmed transient failure when the window regains focus.
      } finally {
        requesting = false;
      }
    };
    void refresh();
    window.addEventListener("focus", refresh);
    return () => {
      controller.abort();
      window.removeEventListener("focus", refresh);
    };
  }, [authEnabled]);
  return authEnabled ? capability : AUTH_DISABLED_CAPABILITY;
}
