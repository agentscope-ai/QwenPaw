import { request } from "../request";

// Root API
export const rootApi = {
  readRoot: () => request<unknown>("/"),
  getVersion: () => request<{ version: string }>("/version"),
};
