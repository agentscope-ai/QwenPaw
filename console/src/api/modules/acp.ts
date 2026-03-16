import { request } from "../request";
import type { ACPConfig, ParsedExternalAgent } from "../types";

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

  /**
   * Parse external agent text to extract configuration
   */
  parseExternalAgentText: (text: string) =>
    request<ParsedExternalAgent>("/config/acp/parse-text", {
      method: "POST",
      body: JSON.stringify({ text }),
    }),
};
