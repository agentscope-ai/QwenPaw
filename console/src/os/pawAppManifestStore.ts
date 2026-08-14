import { create } from "zustand";

import { pawappApi, type PawAppInfo } from "../api/modules/pawapp";

interface PawAppManifestState {
  apps: PawAppInfo[];
  loaded: boolean;
  loading: boolean;
  error: string | null;
  refresh: () => Promise<void>;
  remove: (appId: string) => void;
  upsert: (app: PawAppInfo) => void;
}

let refreshPromise: Promise<void> | null = null;
let localMutationVersion = 0;

export const usePawAppManifestStore = create<PawAppManifestState>((set) => ({
  apps: [],
  loaded: false,
  loading: false,
  error: null,
  refresh: () => {
    if (refreshPromise) return refreshPromise;
    const mutationVersion = localMutationVersion;
    set({ loading: true, error: null });
    refreshPromise = pawappApi
      .list()
      .then((response) => {
        if (mutationVersion !== localMutationVersion) return;
        set({ apps: response.apps, loaded: true, error: null });
      })
      .catch((error: unknown) => {
        set({
          error: error instanceof Error ? error.message : String(error),
        });
        throw error;
      })
      .finally(() => {
        refreshPromise = null;
        set({ loading: false });
      });
    return refreshPromise;
  },
  remove: (appId) => {
    localMutationVersion += 1;
    set((state) => ({
      apps: state.apps.filter((app) => app.id !== appId),
      loaded: true,
    }));
  },
  upsert: (app) => {
    localMutationVersion += 1;
    set((state) => ({
      apps: [...state.apps.filter((item) => item.id !== app.id), app],
      loaded: true,
    }));
  },
}));

export function resetPawAppManifestStoreForTests(): void {
  refreshPromise = null;
  localMutationVersion = 0;
  usePawAppManifestStore.setState({
    apps: [],
    loaded: false,
    loading: false,
    error: null,
  });
}

/** Synchronize a list already fetched by another App surface. */
export function syncPawAppManifests(apps: PawAppInfo[]): void {
  localMutationVersion += 1;
  usePawAppManifestStore.setState({
    apps,
    loaded: true,
    error: null,
  });
}
