import { request } from "../request";
import type { EnvOperation, EnvVar } from "../types";

export const envApi = {
  listEnvs: () => request<EnvVar[]>("/envs"),

  /** Apply explicit changes. Values are write-only and never returned. */
  updateEnvs: (operations: EnvOperation[]) =>
    request<EnvVar[]>("/envs", {
      method: "PUT",
      body: JSON.stringify({ operations }),
    }),
};
