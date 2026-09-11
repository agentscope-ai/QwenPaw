import type {
  PawApiNamespace,
  PawDependencyAction,
  PawDependencySnapshot,
  PawDependencyStatus,
  PawDependenciesNamespace,
  PawDisposable,
} from "./types";

export function createDependenciesNamespace(
  api: PawApiNamespace,
): PawDependenciesNamespace {
  const list = (force = false) =>
    api.get<PawDependencySnapshot>("/dependencies", {
      query: force ? { force: true } : undefined,
    });

  return {
    list,
    get: (dependencyId, force = false) =>
      api.get<PawDependencyStatus>(
        `/dependencies/${encodeURIComponent(dependencyId)}`,
        { query: force ? { force: true } : undefined },
      ),
    check: (dependencyId) =>
      api.post<PawDependencyStatus>(
        `/dependencies/${encodeURIComponent(dependencyId)}/actions/check`,
      ),
    action: (dependencyId, action, options) =>
      api.post<PawDependencyStatus>(
        `/dependencies/${encodeURIComponent(
          dependencyId,
        )}/actions/${encodeURIComponent(action)}`,
        undefined,
        options?.idempotencyKey
          ? { headers: { "Idempotency-Key": options.idempotencyKey } }
          : undefined,
      ),
    subscribe(listener, options = {}): PawDisposable {
      let disposed = false;
      let timer: ReturnType<typeof setTimeout> | undefined;
      const intervalMs = Math.max(1_000, options.intervalMs ?? 10_000);

      const poll = async () => {
        try {
          const snapshot = await list(Boolean(options.force));
          if (!disposed) listener(snapshot);
        } catch {
          // Transient failures are reflected by the next successful snapshot;
          // consumers can still issue an explicit list() call for typed errors.
        } finally {
          if (!disposed) timer = setTimeout(poll, intervalMs);
        }
      };

      void poll();
      return {
        dispose() {
          disposed = true;
          if (timer) clearTimeout(timer);
        },
      };
    },
  };
}

export type { PawDependencyAction };
