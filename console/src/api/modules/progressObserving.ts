import { request } from "../request";

export interface ProgressObservingConfigResponse {
  enabled: boolean;
  hook_type: string;
}

export const progressObservingApi = {
  getConfig: () =>
    request<ProgressObservingConfigResponse>("/progress-observing/config"),

  updateConfig: (body: ProgressObservingConfigResponse) =>
    request<ProgressObservingConfigResponse>("/progress-observing/config", {
      method: "PUT",
      body: JSON.stringify(body),
    }),
};
