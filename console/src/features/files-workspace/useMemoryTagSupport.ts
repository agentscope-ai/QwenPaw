import { useCallback, useEffect, useRef, useState } from "react";
import { agentsApi } from "../../api/modules/agents";

export interface MemoryFileConfig {
  daily_dir: string;
  digest_dir: string;
}

/** Share capability and directory reads with file identity resolution. */
export function useMemoryFileConfig(agentId: string) {
  const [loaded, setLoaded] = useState<{
    agentId: string;
    config: MemoryFileConfig | null;
  } | null>(null);
  const pending = useRef<{
    agentId: string;
    controller: AbortController;
    promise: Promise<MemoryFileConfig | null>;
  }>();
  const refresh = useCallback(() => {
    pending.current?.controller.abort();
    const controller = new AbortController();
    const promise = agentsApi
      .getAgent(agentId, controller.signal)
      .then((config) => {
        if (controller.signal.aborted)
          throw new DOMException("Aborted", "AbortError");
        const running = config.running as
          | {
              memory_manager_backend?: string;
              reme_light_memory_config?: Partial<MemoryFileConfig>;
            }
          | undefined;
        const memory =
          running?.memory_manager_backend === "remelight"
            ? {
                daily_dir:
                  running.reme_light_memory_config?.daily_dir ?? "memory",
                digest_dir:
                  running.reme_light_memory_config?.digest_dir ?? "digest",
              }
            : null;
        setLoaded({ agentId, config: memory });
        return memory;
      })
      .catch((error: unknown) => {
        // An older request must not clear a newer agent/focus refresh.
        if (pending.current?.controller === controller) {
          pending.current = undefined;
          if (!controller.signal.aborted) setLoaded(null);
        }
        throw error;
      });
    pending.current = { agentId, controller, promise };
    return promise;
  }, [agentId]);
  const getConfig = useCallback(
    () =>
      pending.current?.agentId === agentId
        ? pending.current.promise
        : refresh(),
    [agentId, refresh],
  );
  useEffect(() => {
    const onFocus = () => {
      void refresh().catch(() => {});
    };
    onFocus();
    window.addEventListener("focus", onFocus);
    return () => {
      pending.current?.controller.abort();
      window.removeEventListener("focus", onFocus);
    };
  }, [refresh]);
  return {
    config: loaded?.agentId === agentId ? loaded.config : null,
    getConfig,
  };
}

export function useMemoryTagSupport(agentId: string): boolean {
  return useMemoryFileConfig(agentId).config !== null;
}
