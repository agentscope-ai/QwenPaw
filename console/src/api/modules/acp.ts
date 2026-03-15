import { request } from "../request";
import type { ACPConfig } from "../types";

export const acpApi = {
  /**
   * Get ACP configuration
   */
  getACPConfig: () => request<ACPConfig>("/config/acp"),

  /**
   * Update ACP configuration
   */
  updateACPConfig: (config: ACPConfig) =>
    request<ACPConfig>("/config/acp", {
      method: "PUT",
      body: JSON.stringify(config),
    }),
};
