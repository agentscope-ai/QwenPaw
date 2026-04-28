import { request } from "../request";
import type { SemanticRoutingConfig } from "../types/semanticRouting";

export const semanticRoutingApi = {
  getSemanticRoutingConfig: () =>
    request<SemanticRoutingConfig>("/config/semantic-routing"),

  updateSemanticRoutingConfig: (body: SemanticRoutingConfig) =>
    request<SemanticRoutingConfig>("/config/semantic-routing", {
      method: "PUT",
      body: JSON.stringify(body),
    }),
};
