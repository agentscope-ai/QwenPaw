import { useCallback, useEffect, useRef, useState } from "react";

import api from "../../../../../api";
import type {
  DiscoverModelsResponse,
  ExtendedModelInfo,
  ProviderInfo,
} from "../../../../../api/types";

export type ProviderDiscoveryState =
  | "idle"
  | "loading"
  | "failed"
  | "empty"
  | "ready";

interface UseProviderModelDiscoveryOptions {
  provider: ProviderInfo;
  autoPreview: boolean;
  fallbackError: string;
  onSaved: () => void | Promise<void>;
}

function providerModels(
  models: ProviderInfo["discovered_models"],
): ExtendedModelInfo[] {
  return (models ?? []) as unknown as ExtendedModelInfo[];
}

function providerState(
  models: ProviderInfo["discovered_models"],
  syncedAt: string | null | undefined,
  syncError: string | null | undefined,
): ProviderDiscoveryState {
  if (syncError) return "failed";
  if ((models?.length ?? 0) > 0) return "ready";
  if (syncedAt) return "empty";
  return "idle";
}

function providerTargetKey(provider: ProviderInfo): string {
  const revision = provider.meta?.provider_runtime_revision;
  const runtimeRevision =
    typeof revision === "number" && Number.isFinite(revision) ? revision : 0;
  return JSON.stringify([provider.id, runtimeRevision]);
}

export function useProviderModelDiscovery({
  provider,
  autoPreview,
  fallbackError,
  onSaved,
}: UseProviderModelDiscoveryOptions) {
  const {
    id: providerId,
    discovered_models: serverModels,
    models_last_synced_at: serverSyncedAt,
    models_last_sync_error: serverSyncError,
    models_syncing: modelsSyncing,
  } = provider;
  const targetKey = providerTargetKey(provider);
  const [models, setModels] = useState<ExtendedModelInfo[]>(() =>
    providerModels(serverModels),
  );
  const [state, setState] = useState<ProviderDiscoveryState>(() =>
    providerState(serverModels, serverSyncedAt, serverSyncError),
  );
  const [error, setError] = useState<string | null>(serverSyncError ?? null);
  const [requestRunning, setRequestRunning] = useState(false);
  const targetKeyRef = useRef(targetKey);
  const requestRevisionRef = useRef(0);
  const inFlightRef = useRef<Promise<DiscoverModelsResponse | null> | null>(
    null,
  );
  const previewAttemptedProviderRef = useRef<string | null>(null);

  useEffect(() => {
    if (targetKeyRef.current !== targetKey) {
      targetKeyRef.current = targetKey;
      requestRevisionRef.current += 1;
      inFlightRef.current = null;
      previewAttemptedProviderRef.current = null;
      setRequestRunning(false);
    }
    if (inFlightRef.current) return;
    setModels(providerModels(serverModels));
    setState(providerState(serverModels, serverSyncedAt, serverSyncError));
    setError(serverSyncError ?? null);
  }, [serverModels, serverSyncedAt, serverSyncError, targetKey]);

  useEffect(
    () => () => {
      requestRevisionRef.current += 1;
      inFlightRef.current = null;
    },
    [],
  );

  const discover = useCallback(async () => {
    if (modelsSyncing) return null;
    if (inFlightRef.current) return inFlightRef.current;

    const requestProviderId = providerId;
    const requestTargetKey = targetKey;
    const requestRevision = ++requestRevisionRef.current;
    const request = (async (): Promise<DiscoverModelsResponse | null> => {
      setRequestRunning(true);
      setState("loading");
      setError(null);
      try {
        const result = await api.discoverModels(
          requestProviderId,
          undefined,
          true,
        );
        if (
          requestRevision !== requestRevisionRef.current ||
          requestTargetKey !== targetKeyRef.current
        ) {
          return result;
        }
        setModels((result.models ?? []) as ExtendedModelInfo[]);
        setState(
          result.success
            ? result.models.length > 0
              ? "ready"
              : "empty"
            : "failed",
        );
        setError(result.success ? null : result.message || null);
        try {
          await onSaved();
        } catch {
          // Discovery succeeded even if the parent refresh is unavailable.
        }
        return result;
      } catch (requestError) {
        if (
          requestRevision === requestRevisionRef.current &&
          requestTargetKey === targetKeyRef.current
        ) {
          setState("failed");
          setError(
            requestError instanceof Error
              ? requestError.message
              : fallbackError,
          );
        }
        throw requestError;
      } finally {
        if (
          requestRevision === requestRevisionRef.current &&
          requestTargetKey === targetKeyRef.current
        ) {
          setRequestRunning(false);
        }
      }
    })();
    inFlightRef.current = request;
    void request.then(
      () => {
        if (inFlightRef.current === request) inFlightRef.current = null;
      },
      () => {
        if (inFlightRef.current === request) inFlightRef.current = null;
      },
    );
    return request;
  }, [fallbackError, modelsSyncing, onSaved, providerId, targetKey]);

  const serverHasModels = (serverModels?.length ?? 0) > 0;
  const hasServerOutcome = Boolean(serverSyncedAt) || Boolean(serverSyncError);
  useEffect(() => {
    if (
      !autoPreview ||
      modelsSyncing ||
      requestRunning ||
      serverHasModels ||
      hasServerOutcome ||
      models.length > 0 ||
      previewAttemptedProviderRef.current === targetKey
    ) {
      return;
    }
    previewAttemptedProviderRef.current = targetKey;
    void discover().catch(() => {});
  }, [
    autoPreview,
    discover,
    hasServerOutcome,
    models.length,
    modelsSyncing,
    requestRunning,
    serverHasModels,
    targetKey,
  ]);

  const removeModels = useCallback((modelIds: Set<string>) => {
    setModels((current) => current.filter((model) => !modelIds.has(model.id)));
  }, []);

  const isDiscovering = requestRunning || Boolean(modelsSyncing);
  return {
    discover,
    error,
    isDiscovering,
    models,
    removeModels,
    replaceModels: setModels,
    state: isDiscovering ? "loading" : state,
  };
}
