import { create } from "zustand";
import { getApiToken } from "../../api/config";
import { platformAccessApi, type PlatformConnection } from "./api";

interface PlatformAccessState {
  connection: PlatformConnection | null;
  localAccount: string | null;
  panel: "account" | "mobile" | null;
  refresh: () => Promise<PlatformConnection>;
  open: (panel: "account" | "mobile" | null) => void;
}

let pending: { token: string; promise: Promise<PlatformConnection> } | null =
  null;
export const usePlatformAccess = create<PlatformAccessState>((set) => ({
  connection: null,
  localAccount: null,
  panel: null,
  refresh: () => {
    const token = getApiToken();
    if (pending?.token === token) return pending.promise;
    const promise = platformAccessApi
      .status()
      .then((connection) => {
        if (getApiToken() === token) set({ connection });
        return connection;
      })
      .finally(() => {
        if (pending?.promise === promise) pending = null;
      });
    pending = { token, promise };
    return promise;
  },
  open: (panel) => set({ panel }),
}));
