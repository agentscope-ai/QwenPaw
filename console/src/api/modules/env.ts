import { request } from "../request";
import type { EnvSpec, EnvVar } from "../types";

export const envApi = {
  listEnvs: () => request<EnvVar[]>("/envs"),

  listEnvCatalog: () => request<EnvSpec[]>("/envs/catalog"),

  /** Merge variables without removing keys omitted from the request. */
  patchEnvs: (envs: Record<string, string>) =>
    request<EnvVar[]>("/envs", {
      method: "PATCH",
      body: JSON.stringify(envs),
    }),

  /** Batch save – full replacement of all env vars. */
  saveEnvs: (envs: Record<string, string>) =>
    request<EnvVar[]>("/envs", {
      method: "PUT",
      body: JSON.stringify(envs),
    }),

  deleteEnv: (key: string) =>
    request<EnvVar[]>(`/envs/${encodeURIComponent(key)}`, {
      method: "DELETE",
    }),

  resetEnv: (key: string) =>
    request<EnvVar[]>(`/envs/${encodeURIComponent(key)}/reset`, {
      method: "POST",
    }),
};
