import { request } from "../request";

// Root API
export const rootApi = {
  readRoot: () => request<unknown>("/"),
  getVersion: (signal?: AbortSignal) =>
    request<{ version: string }>("/version", { signal }),
};
